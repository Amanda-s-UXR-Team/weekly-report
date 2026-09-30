"""Resolve publisher URLs and extract original article text before AI review."""

from __future__ import annotations

import asyncio
import io
import ipaddress
import re
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urljoin, urlparse

import aiohttp
import trafilatura

from .base import NewsItem


DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)
GOOGLE_NEWS_HOSTS = {"news.google.com"}
INVALID_PAGE_MARKERS = (
    "enable javascript",
    "javascript is disabled",
    "access denied",
    "security check",
    "verify you are human",
    "checking your browser",
    "cloudflare ray id",
)


class ArticleFetchError(RuntimeError):
    """Expected per-article failure that should not stop the whole run."""


@dataclass
class ArticleFetchStats:
    total: int = 0
    resolved: int = 0
    extracted: int = 0
    failed: int = 0

    def to_dict(self) -> dict[str, int]:
        return asdict(self)


@dataclass
class FetchedDocument:
    body: bytes
    content_type: str
    final_url: str
    encoding: str = "utf-8"


def _is_google_news_url(url: str) -> bool:
    return (urlparse(url).hostname or "").lower() in GOOGLE_NEWS_HOSTS


def _is_safe_public_url(url: str) -> bool:
    """Reject unsupported schemes and obvious local/private destinations."""
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
        return False
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        return True
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
    )


def _clean_extracted_text(text: str) -> str:
    paragraphs = []
    for block in re.split(r"\n{2,}", text or ""):
        cleaned = re.sub(r"\s+", " ", block).strip()
        if cleaned:
            paragraphs.append(cleaned)
    return "\n\n".join(paragraphs)


class OriginalArticleFetcher:
    """Fetch publisher pages, extract main text and attach it to NewsItem."""

    def __init__(self, config: dict[str, Any] | None = None):
        config = config or {}
        self.enabled = bool(config.get("enabled", True))
        self.max_concurrency = max(1, int(config.get("max_concurrency", 6)))
        self.timeout_seconds = max(5.0, float(config.get("timeout_seconds", 20)))
        self.min_content_chars = max(80, int(config.get("min_content_chars", 300)))
        self.max_content_chars = max(
            self.min_content_chars,
            int(config.get("max_content_chars", 15000)),
        )
        self.max_download_bytes = max(
            100_000,
            int(config.get("max_download_bytes", 2_500_000)),
        )
        self.user_agent = str(config.get("user_agent") or DEFAULT_USER_AGENT)

    async def enrich_items(self, items: list[NewsItem]) -> ArticleFetchStats:
        stats = ArticleFetchStats(total=len(items))
        if not self.enabled or not items:
            return stats

        source_urls = [item.url for item in items]
        resolved_urls = await self._resolve_google_news_urls(source_urls)
        stats.resolved = sum(
            1
            for source in source_urls
            if resolved_urls.get(source, source) != source
        )

        timeout = aiohttp.ClientTimeout(
            total=self.timeout_seconds,
            connect=min(10.0, self.timeout_seconds),
        )
        connector = aiohttp.TCPConnector(limit=self.max_concurrency)
        headers = {
            "User-Agent": self.user_agent,
            "Accept": (
                "text/html,application/xhtml+xml,application/pdf,"
                "text/plain;q=0.9,*/*;q=0.5"
            ),
            "Accept-Language": "en-US,en;q=0.8",
        }
        semaphore = asyncio.Semaphore(self.max_concurrency)
        async with aiohttp.ClientSession(
            timeout=timeout,
            connector=connector,
            headers=headers,
        ) as session:
            tasks = [
                self._enrich_one(
                    session,
                    semaphore,
                    item,
                    resolved_urls.get(item.url, item.url),
                )
                for item in items
            ]
            results = await asyncio.gather(*tasks, return_exceptions=True)

        for item, result in zip(items, results):
            if result is True:
                stats.extracted += 1
                continue
            stats.failed += 1
            item.content_access = "unavailable"
            if isinstance(result, Exception):
                item.extraction_error = str(result)[:200]
            elif not item.extraction_error:
                item.extraction_error = "original article text unavailable"
        if stats.failed:
            reasons = Counter(
                item.extraction_error or "unknown"
                for item in items
                if item.content_access != "fulltext"
            )
            summary = ", ".join(
                f"{reason}: {count}"
                for reason, count in reasons.most_common(5)
            )
            print(f"   Original text failures: {summary}")
        return stats

    async def _resolve_google_news_urls(self, urls: list[str]) -> dict[str, str]:
        mapping = {url: url for url in urls}
        google_urls = list(dict.fromkeys(url for url in urls if _is_google_news_url(url)))
        if not google_urls:
            return mapping

        try:
            from googlenewsdecoder import gnews_decoder_async

            results = await gnews_decoder_async(
                google_urls,
                timeout=self.timeout_seconds,
                concurrency=self.max_concurrency,
            )
            if isinstance(results, dict):
                results = [results]
            for source_url, result in zip(google_urls, results):
                decoded = result.get("decoded_url") if result.get("success") else None
                if decoded and _is_safe_public_url(decoded):
                    mapping[source_url] = decoded
        except Exception as exc:
            print(f"   ⚠️ Google News link resolution failed: {type(exc).__name__}")
        return mapping

    async def _enrich_one(
        self,
        session: aiohttp.ClientSession,
        semaphore: asyncio.Semaphore,
        item: NewsItem,
        resolved_url: str,
    ) -> bool:
        item.discovery_url = item.discovery_url or item.url
        if _is_google_news_url(resolved_url):
            raise ArticleFetchError("Google News URL could not be resolved")
        if not _is_safe_public_url(resolved_url):
            raise ArticleFetchError("unsupported or non-public article URL")

        item.original_url = resolved_url
        item.url = resolved_url
        async with semaphore:
            document = await self._fetch_document(session, resolved_url)
        if not _is_safe_public_url(document.final_url):
            raise ArticleFetchError("article redirected to a non-public URL")

        extracted = await asyncio.to_thread(self._extract_document, document)
        if len(extracted) < self.min_content_chars:
            raise ArticleFetchError(
                f"extracted text too short ({len(extracted)} chars)"
            )

        item.original_url = document.final_url
        item.url = document.final_url
        item.content = extracted[: self.max_content_chars]
        item.content_access = "fulltext"
        item.content_chars = len(item.content)
        item.fetched_at = datetime.now(timezone.utc)
        item.extraction_error = None
        return True

    async def _fetch_document(
        self,
        session: aiohttp.ClientSession,
        url: str,
    ) -> FetchedDocument:
        try:
            current_url = url
            for _ in range(6):
                if not _is_safe_public_url(current_url):
                    raise ArticleFetchError("redirected to a non-public URL")
                async with session.get(current_url, allow_redirects=False) as response:
                    if 300 <= response.status < 400:
                        location = response.headers.get("Location")
                        if not location:
                            raise ArticleFetchError(
                                f"HTTP {response.status} without redirect location"
                            )
                        current_url = urljoin(current_url, location)
                        continue
                    if response.status != 200:
                        raise ArticleFetchError(f"HTTP {response.status}")
                    content_type = response.headers.get("Content-Type", "").lower()

                    chunks = bytearray()
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        chunks.extend(chunk)
                        if len(chunks) > self.max_download_bytes:
                            raise ArticleFetchError(
                                "article response exceeded size limit"
                            )
                    body = bytes(chunks)
                    if body.startswith(b"%PDF-"):
                        content_type = "application/pdf"
                    elif not any(allowed in content_type for allowed in (
                        "text/html",
                        "application/xhtml+xml",
                        "text/plain",
                    )):
                        raise ArticleFetchError(
                            f"unsupported content type: {content_type or 'unknown'}"
                        )
                    return FetchedDocument(
                        body=body,
                        content_type=content_type,
                        final_url=str(response.url),
                        encoding=response.charset or "utf-8",
                    )
            raise ArticleFetchError("too many redirects")
        except ArticleFetchError:
            raise
        except (aiohttp.ClientError, asyncio.TimeoutError) as exc:
            raise ArticleFetchError(type(exc).__name__) from exc

    def _extract_document(self, document: FetchedDocument) -> str:
        if "application/pdf" in document.content_type:
            return self._extract_pdf_text(document.body)
        html = document.body.decode(document.encoding, errors="replace")
        return self._extract_text(html, document.final_url)

    def _extract_pdf_text(self, body: bytes) -> str:
        try:
            from pypdf import PdfReader

            reader = PdfReader(io.BytesIO(body))
            text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as exc:
            raise ArticleFetchError(f"PDF extraction failed: {type(exc).__name__}") from exc
        return _clean_extracted_text(text)

    def _extract_text(self, html: str, url: str) -> str:
        lower = html.lower()
        if any(marker in lower for marker in INVALID_PAGE_MARKERS):
            raise ArticleFetchError("publisher returned a bot/interstitial page")
        text = trafilatura.extract(
            html,
            url=url,
            output_format="txt",
            include_comments=False,
            include_tables=True,
            favor_precision=True,
        )
        return _clean_extracted_text(text or "")


async def enrich_original_articles(
    categories: dict[str, list[NewsItem]],
    config: dict[str, Any] | None = None,
) -> tuple[dict[str, list[NewsItem]], dict[str, int]]:
    """Enrich every prefiltered candidate and optionally require full text."""
    config = config or {}
    items = [item for group in categories.values() for item in group]
    fetcher = OriginalArticleFetcher(config)
    stats = await fetcher.enrich_items(items)

    if fetcher.enabled and bool(config.get("require_fulltext", True)):
        categories = {
            category: [item for item in group if item.content_access == "fulltext"]
            for category, group in categories.items()
        }
        categories = {category: group for category, group in categories.items() if group}
    result = stats.to_dict()
    result["eligible"] = sum(len(group) for group in categories.values())
    return categories, result
