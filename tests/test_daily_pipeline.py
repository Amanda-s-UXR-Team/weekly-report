"""Offline integration checks for the extracted entry point. No live services."""
import json
import os
import tempfile
import unittest
from contextlib import ExitStack
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import main as app
from collectors.base import NewsItem
from monitoring import empty_feishu_receipt
from publishers.feishu_archive import FeishuArchiveManager, SIX_COUNTRY
from publishers.feishu_publisher import FeishuSendError


class DailyPipelineTests(unittest.IsolatedAsyncioTestCase):
    async def run_pipeline(
        self,
        root,
        *,
        empty=False,
        send_failure=False,
        ai_error=False,
        ai_filters_all=False,
        fetch_failure=False,
        missing_key=False,
        receive_id='oc_offline_fixture',
        receive_id_type='chat_id',
        legacy_receiver=False,
    ):
        item = NewsItem(
            title='离线样例：肯尼亚移动服务变化',
            url='https://example.invalid/offline-story', source='Offline fixture',
            category='digital_ecosystem', country='kenya',
            summary='此条是用于验证打包后流程的人工样例，不是真实新闻。' * 4,
            published=datetime.now(timezone.utc),
        )
        config = {
            'rss_sources': {},
            'article_fetch': {'enabled': True, 'require_fulltext': True},
            'output': {'category_names': {'digital_ecosystem': '数字生态'},
                       'max_per_category': 15, 'pre_ai_max_per_category': 30},
            'publishers': {'feishu': {'enabled': True}, 'feishu_bot': {'enabled': True}},
        }
        ai = MagicMock()
        ai.fatal_error = "DeepSeek HTTP 401" if ai_error else None
        ai.successful_calls = 3
        ai.semantic_deduplicate = AsyncMock(side_effect=lambda x: x)
        ai.process_and_filter_items = AsyncMock(
            side_effect=lambda x: ([], 0) if ai_filters_all else (x, 0)
        )
        ai.generate_daily_highlights = AsyncMock(return_value='离线样例：今日三条要点。')
        publisher = MagicMock()
        publisher.is_configured.return_value = True
        publisher.upload_pdf = AsyncMock(return_value='https://example.invalid/daily.pdf')
        ack = {**empty_feishu_receipt('acknowledged'), 'api_ack_at': '2026-09-29T05:00:00Z'}
        publisher.send_digest_card = AsyncMock(return_value=ack)
        if send_failure:
            publisher.send_digest_card.side_effect = FeishuSendError(
                'fixture rejection', {**empty_feishu_receipt('failed'), 'error_code': 'provider_rejected'})
        publisher.cleanup_old_documents = AsyncMock(return_value=0)

        def fake_pdf(_self, html, path):
            self.assertIn('离线样例', html)
            Path(path).write_bytes(b'%PDF-1.4\nOffline orchestration fixture only\n')
            return True

        env = {
            'DEEPSEEK_API_KEY': 'offline-fixture',
            'REQUIRE_FEISHU_DELIVERY': 'true',
            'MONITOR_RECEIPT_PATH': str(root / 'receipt.json'),
        }
        if legacy_receiver:
            env['FEISHU_BOT_CHAT_ID'] = receive_id
        else:
            env['FEISHU_RECEIVE_ID'] = receive_id
            env['FEISHU_RECEIVE_ID_TYPE'] = receive_id_type
        if missing_key:
            env.pop('DEEPSEEK_API_KEY')

        async def fake_original_fetch(categories, _config):
            if fetch_failure:
                return {}, {
                    'total': sum(len(items) for items in categories.values()),
                    'resolved': 0,
                    'extracted': 0,
                    'failed': 1,
                    'eligible': 0,
                }
            for items in categories.values():
                for candidate in items:
                    candidate.discovery_url = candidate.url
                    candidate.original_url = candidate.url
                    candidate.content_access = 'fulltext'
                    candidate.content = candidate.summary
                    candidate.content_chars = len(candidate.content or '')
            total = sum(len(items) for items in categories.values())
            return categories, {
                'total': total,
                'resolved': 0,
                'extracted': total,
                'failed': 0,
                'eligible': total,
            }

        original_fetch = AsyncMock(side_effect=fake_original_fetch)
        ai.original_fetch = original_fetch
        with ExitStack() as stack:
            stack.enter_context(patch.dict(os.environ, env, clear=True))
            stack.enter_context(patch.object(app, '__file__', str(root / 'main.py')))
            stack.enter_context(patch.object(app, 'load_config', return_value=config))
            stack.enter_context(patch.object(app, 'collect_all_sources', AsyncMock(return_value=[] if empty else [item])))
            stack.enter_context(patch.object(app, 'enrich_original_articles', original_fetch))
            stack.enter_context(patch.object(app, 'DeepSeekSummarizer', return_value=ai))
            stack.enter_context(patch.object(app, 'FeishuPublisher', return_value=publisher))
            stack.enter_context(patch.object(app, 'WEASYPRINT_AVAILABLE', True))
            stack.enter_context(patch.object(app.EmailSender, 'generate_pdf', fake_pdf))
            stack.enter_context(patch('aiohttp.ClientSession', side_effect=AssertionError('Live HTTP is forbidden in offline tests')))
            result = await app.main_async()
        return result, ai, publisher

    async def test_collection_to_pdf_linked_card_and_receipt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            code, ai, publisher = await self.run_pipeline(root)
            self.assertEqual(code, 0)
            ai.original_fetch.assert_awaited_once()
            ai.semantic_deduplicate.assert_awaited_once()
            ai.process_and_filter_items.assert_awaited_once()
            ai.generate_daily_highlights.assert_awaited_once()
            publisher.upload_pdf.assert_awaited_once()
            publisher.send_digest_card.assert_awaited_once()
            self.assertEqual(
                publisher.upload_pdf.call_args.args[2:],
                ('oc_offline_fixture', 'chat_id'),
            )
            self.assertEqual(publisher.send_digest_card.call_args.args[-1], 'https://example.invalid/daily.pdf')
            self.assertEqual(
                publisher.send_digest_card.call_args.kwargs['receive_id_type'],
                'chat_id',
            )
            receipt = json.loads((root / 'receipt.json').read_text())
            self.assertEqual(receipt['deliveries'][0]['status'], 'acknowledged')

    async def test_personal_receiver_is_used_for_pdf_and_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, publisher = await self.run_pipeline(
                Path(tmp),
                receive_id='ou_offline_fixture',
                receive_id_type='open_id',
            )
            self.assertEqual(
                publisher.upload_pdf.call_args.args[2:],
                ('ou_offline_fixture', 'open_id'),
            )
            self.assertEqual(
                publisher.send_digest_card.call_args.args[0],
                'ou_offline_fixture',
            )
            self.assertEqual(
                publisher.send_digest_card.call_args.kwargs['receive_id_type'],
                'open_id',
            )

    async def test_legacy_group_receiver_defaults_to_chat_id(self):
        with tempfile.TemporaryDirectory() as tmp:
            _, _, publisher = await self.run_pipeline(
                Path(tmp),
                receive_id='oc_legacy_fixture',
                legacy_receiver=True,
            )
            self.assertEqual(
                publisher.upload_pdf.call_args.args[2:],
                ('oc_legacy_fixture', 'chat_id'),
            )
            self.assertEqual(
                publisher.send_digest_card.call_args.kwargs['receive_id_type'],
                'chat_id',
            )

    async def test_no_news_exits_before_ai_or_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, ai, publisher = await self.run_pipeline(Path(tmp), empty=True)
            self.assertEqual(code, 1)
            ai.semantic_deduplicate.assert_not_awaited()
            publisher.send_digest_card.assert_not_awaited()

    async def test_missing_original_text_stops_before_ai_or_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, ai, publisher = await self.run_pipeline(
                Path(tmp),
                fetch_failure=True,
            )
            self.assertEqual(code, 1)
            ai.original_fetch.assert_awaited_once()
            ai.semantic_deduplicate.assert_not_awaited()
            publisher.upload_pdf.assert_not_awaited()
            publisher.send_digest_card.assert_not_awaited()

    async def test_zero_ai_qualified_items_stops_empty_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, ai, publisher = await self.run_pipeline(
                Path(tmp),
                ai_filters_all=True,
            )
            self.assertEqual(code, 1)
            ai.generate_daily_highlights.assert_not_awaited()
            publisher.upload_pdf.assert_not_awaited()
            publisher.send_digest_card.assert_not_awaited()

    async def test_ai_auth_failure_stops_before_upload_and_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, publisher = await self.run_pipeline(Path(tmp), ai_error=True)
            self.assertEqual(code, 1)
            publisher.upload_pdf.assert_not_awaited()
            publisher.send_digest_card.assert_not_awaited()

    async def test_missing_ai_key_stops_before_upload_and_send(self):
        with tempfile.TemporaryDirectory() as tmp:
            code, _, publisher = await self.run_pipeline(Path(tmp), missing_key=True)
            self.assertEqual(code, 1)
            publisher.upload_pdf.assert_not_awaited()
            publisher.send_digest_card.assert_not_awaited()

    async def test_failed_send_persists_failure_and_raises(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(FeishuSendError):
                await self.run_pipeline(root, send_failure=True)
            receipt = json.loads((root / 'receipt.json').read_text())
            self.assertEqual(receipt['deliveries'][0]['status'], 'failed')


class StandaloneArchiveTests(unittest.IsolatedAsyncioTestCase):
    async def test_daily_folder_does_not_require_ai_folder(self):
        archive = FeishuArchiveManager(MagicMock(), root_folder_token='offline-root')
        archive.list_folder = AsyncMock(return_value=[
            {'type': 'folder', 'name': '六国洞察报告', 'token': 'offline-daily-folder'}
        ])
        self.assertEqual(await archive.resolve_report_folders(), {SIX_COUNTRY: 'offline-daily-folder'})

    def test_no_original_archive_destination_by_default(self):
        with patch.dict(os.environ, {}, clear=True):
            self.assertFalse(FeishuArchiveManager(MagicMock()).is_enabled)

    async def test_archive_passes_personal_receiver_type_to_permissions(self):
        publisher = MagicMock()
        publisher.upload_file = AsyncMock(return_value={
            'file_token': 'offline-file',
            'url': 'https://example.invalid/file',
        })
        publisher.set_file_permission = AsyncMock(return_value=True)
        archive = FeishuArchiveManager(
            publisher,
            root_folder_token='offline-root',
        )
        archive.configure_publisher_folder = AsyncMock(
            return_value='offline-daily-folder'
        )
        await archive.upload_pdf(
            'offline.pdf',
            'Offline report',
            'ou_offline_fixture',
            SIX_COUNTRY,
            receive_id_type='open_id',
        )
        publisher.set_file_permission.assert_awaited_once_with(
            'offline-file',
            'ou_offline_fixture',
            'open_id',
        )
