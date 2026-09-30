import unittest
from unittest.mock import AsyncMock, patch

from collectors.article_extractor import (
    FetchedDocument,
    OriginalArticleFetcher,
    _is_safe_public_url,
    enrich_original_articles,
)
from collectors.base import NewsItem


def make_item(url="https://news.google.com/rss/articles/example"):
    return NewsItem(
        title="Kenya smartphone financing update",
        url=url,
        source="Fixture",
        category="competitor_product",
        country="kenya",
        summary="Google News snippet only",
    )


class URLSafetyTests(unittest.TestCase):
    def test_public_http_urls_are_allowed(self):
        self.assertTrue(_is_safe_public_url("https://example.com/story"))

    def test_local_and_non_http_urls_are_rejected(self):
        self.assertFalse(_is_safe_public_url("http://127.0.0.1/private"))
        self.assertFalse(_is_safe_public_url("http://localhost/private"))
        self.assertFalse(_is_safe_public_url("file:///etc/passwd"))


class OriginalArticleFetcherTests(unittest.IsolatedAsyncioTestCase):
    async def test_google_news_candidate_uses_publisher_fulltext(self):
        item = make_item()
        original_url = "https://publisher.example/phone-financing"
        fetcher = OriginalArticleFetcher({"min_content_chars": 100})
        fetcher._resolve_google_news_urls = AsyncMock(
            return_value={item.url: original_url}
        )
        fetcher._fetch_document = AsyncMock(
            return_value=FetchedDocument(
                body=b"<html>fixture</html>",
                content_type="text/html",
                final_url=original_url,
            )
        )
        article = "Original publisher evidence. " * 20

        with patch.object(fetcher, "_extract_text", return_value=article):
            stats = await fetcher.enrich_items([item])

        self.assertEqual(stats.extracted, 1)
        self.assertEqual(stats.resolved, 1)
        self.assertEqual(item.discovery_url, make_item().url)
        self.assertEqual(item.original_url, original_url)
        self.assertEqual(item.url, original_url)
        self.assertEqual(item.content_access, "fulltext")
        self.assertEqual(item.content, article)
        self.assertGreater(item.content_chars, 100)

    async def test_unresolved_google_news_candidate_is_not_sent_to_ai(self):
        item = make_item()
        fetcher = OriginalArticleFetcher({"min_content_chars": 100})
        fetcher._resolve_google_news_urls = AsyncMock(
            return_value={item.url: item.url}
        )

        with patch(
            "collectors.article_extractor.OriginalArticleFetcher",
            return_value=fetcher,
        ):
            categories, stats = await enrich_original_articles(
                {"competitor_product": [item]},
                {
                    "enabled": True,
                    "require_fulltext": True,
                    "min_content_chars": 100,
                },
            )

        self.assertEqual(categories, {})
        self.assertEqual(stats["eligible"], 0)
        self.assertEqual(stats["failed"], 1)
        self.assertEqual(item.content_access, "unavailable")

    async def test_all_prefiltered_candidates_are_attempted(self):
        items = [
            make_item("https://publisher.example/a"),
            make_item("https://publisher.example/b"),
        ]
        fetcher = OriginalArticleFetcher({"min_content_chars": 100})
        fetcher._resolve_google_news_urls = AsyncMock(
            return_value={item.url: item.url for item in items}
        )
        fetcher._fetch_document = AsyncMock(
            side_effect=[
                FetchedDocument(b"<html>a</html>", "text/html", items[0].url),
                FetchedDocument(b"<html>b</html>", "text/html", items[1].url),
            ]
        )

        with patch.object(
            fetcher,
            "_extract_text",
            return_value="Publisher article text. " * 20,
        ):
            stats = await fetcher.enrich_items(items)

        self.assertEqual(stats.total, 2)
        self.assertEqual(stats.extracted, 2)
        self.assertEqual(fetcher._fetch_document.await_count, 2)

    async def test_pdf_original_is_extracted_as_fulltext(self):
        item = make_item("https://publisher.example/notice.pdf")
        fetcher = OriginalArticleFetcher({"min_content_chars": 100})
        fetcher._resolve_google_news_urls = AsyncMock(return_value={item.url: item.url})
        fetcher._fetch_document = AsyncMock(
            return_value=FetchedDocument(
                body=b"%PDF-fixture",
                content_type="application/pdf",
                final_url=item.url,
            )
        )
        with patch.object(
            fetcher,
            "_extract_pdf_text",
            return_value="Official regulatory PDF evidence. " * 20,
        ):
            stats = await fetcher.enrich_items([item])

        self.assertEqual(stats.extracted, 1)
        self.assertEqual(item.content_access, "fulltext")
        self.assertGreater(item.content_chars, 100)

    async def test_disabled_fetch_preserves_candidates(self):
        item = make_item("https://publisher.example/a")
        categories, stats = await enrich_original_articles(
            {"competitor_product": [item]},
            {"enabled": False, "require_fulltext": True},
        )
        self.assertEqual(categories["competitor_product"], [item])
        self.assertEqual(stats["eligible"], 1)


if __name__ == "__main__":
    unittest.main()
