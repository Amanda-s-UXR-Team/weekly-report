"""Exercise the installed decoder; mock HTTP rather than the resolver itself."""

import inspect
import json
import unittest
from unittest.mock import AsyncMock, patch

import httpx

from collectors.article_extractor import OriginalArticleFetcher


class GoogleNewsDecoderDependencyTests(unittest.IsolatedAsyncioTestCase):
    def test_installed_decoder_exports_async_api(self):
        # Keep this real import: a transitive dependency can break it even when
        # every test that mocks _resolve_google_news_urls still passes.
        from googlenewsdecoder import gnews_decoder_async

        self.assertTrue(inspect.iscoroutinefunction(gnews_decoder_async))

    async def test_installed_decoder_resolves_batch_with_mocked_http(self):
        source_urls = [
            "https://news.google.com/rss/articles/fixture-first",
            "https://news.google.com/rss/articles/fixture-second",
        ]
        publisher_urls = [
            "https://publisher.example/first",
            "https://publisher.example/second",
        ]
        page = (
            '<c-wiz><div jscontroller="fixture" '
            'data-n-a-sg="fixture-signature" data-n-a-ts="123">'
            "</div></c-wiz>"
        )
        page_response = httpx.Response(
            200, text=page, request=httpx.Request("GET", source_urls[0])
        )
        # Google may return batch rows out of order. The real decoder must
        # associate each publisher URL with the original request ID.
        rows = [
            ["wrb.fr", "Fbv4je", json.dumps(["garturlres", publisher_urls[i]]),
             None, None, str(i)]
            for i in (1, 0)
        ]
        decode_response = httpx.Response(
            200,
            text=")]}'\n\n" + json.dumps(rows),
            request=httpx.Request(
                "POST", "https://news.google.com/_/DotsSplashUi/data/batchexecute"
            ),
        )
        with (
            patch.object(httpx.AsyncClient, "get", new=AsyncMock(
                return_value=page_response
            )) as get,
            patch.object(httpx.AsyncClient, "post", new=AsyncMock(
                return_value=decode_response
            )) as post,
        ):
            mapping = await OriginalArticleFetcher()._resolve_google_news_urls(
                source_urls
            )

        self.assertEqual(mapping, dict(zip(source_urls, publisher_urls)))
        self.assertEqual(get.await_count, 2)
        post.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
