"""Exercise the actual adapter with mocked HTTP, no live model calls."""
import os
import unittest
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from collectors.base import NewsItem
from processors.summarizer import DeepSeekSummarizer, format_structured_highlights
from tools.check_config import validate_config

class DeepSeekTests(unittest.IsolatedAsyncioTestCase):
    def response(self, status=200, content='中文摘要', finish='stop'):
        response = MagicMock(status=status)
        response.__aenter__ = AsyncMock(return_value=response)
        response.__aexit__ = AsyncMock(return_value=False)
        response.json = AsyncMock(return_value={'choices': [{'message': {'content': content}, 'finish_reason': finish}]})
        return response

    async def invoke(self, responses, *, json_mode=False):
        session = MagicMock()
        session.__aenter__ = AsyncMock(return_value=session)
        session.__aexit__ = AsyncMock(return_value=False)
        session.post.side_effect = responses
        with patch.dict(os.environ, {}, clear=True), patch('processors.summarizer.aiohttp.ClientSession', return_value=session), patch('processors.summarizer.asyncio.sleep', new_callable=AsyncMock):
            ai = DeepSeekSummarizer(api_key='synthetic-test-key')
            result = await ai._call('Summarize article', json_mode=json_mode)
        return ai, session, result

    async def test_official_model_auth_and_json_mode(self):
        ai, session, result = await self.invoke([self.response(content='{"groups": []}')], json_mode=True)
        args, kwargs = session.post.call_args
        self.assertEqual(args[0], 'https://api.deepseek.com/chat/completions')
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer synthetic-test-key')
        self.assertEqual(kwargs['json']['model'], 'deepseek-flash')
        self.assertEqual(kwargs['json']['thinking'], {'type': 'disabled'})
        self.assertEqual(kwargs['json']['response_format'], {'type': 'json_object'})
        self.assertIn('JSON', kwargs['json']['messages'][0]['content'])
        self.assertFalse(kwargs['allow_redirects'])
        self.assertEqual(result, '{"groups": []}')
        self.assertEqual(ai.successful_calls, 1)

    async def test_text_translation_does_not_request_json(self):
        _, session, result = await self.invoke([self.response()])
        self.assertEqual(result, '中文摘要')
        self.assertNotIn('response_format', session.post.call_args.kwargs['json'])

    async def test_rate_limit_retries_and_recovers(self):
        _, session, _ = await self.invoke([self.response(429), self.response()])
        self.assertEqual(session.post.call_count, 2)

    async def test_invalid_key_fails_without_provider_body(self):
        response = self.response(401, content='sensitive provider error')
        with self.assertRaisesRegex(RuntimeError, 'HTTP 401') as caught:
            await self.invoke([response])
        self.assertNotIn('sensitive', str(caught.exception))
        response.json.assert_not_awaited()

    async def test_truncated_response_is_not_accepted(self):
        with self.assertRaisesRegex(RuntimeError, 'truncated'):
            await self.invoke([self.response(finish='length')])

    def test_model_and_base_url_can_be_overridden(self):
        with patch.dict(os.environ, {'DEEPSEEK_MODEL': 'another-model', 'DEEPSEEK_BASE_URL': 'https://api.deepseek.com/v1/'}, clear=True):
            ai = DeepSeekSummarizer(api_key='synthetic-test-key')
        self.assertEqual(ai.model_name, 'another-model')
        self.assertEqual(ai.base_url, 'https://api.deepseek.com/v1')

    def test_highlights_reuse_structured_grounded_fields(self):
        item = NewsItem(
            title='测试资讯',
            url='https://example.invalid/story',
            source='离线测试',
            category='competitor_product',
            country='kenya',
            published=datetime.now(timezone.utc),
            editorial_score=9,
            what_happened='原文披露了指定手机的分期优惠。',
            why_it_matters='会影响客户对总成本的比较。',
            scope_limits='仅限指定用户和机型。',
        )
        html = format_structured_highlights({'competitor_product': [item]})
        self.assertIn('<strong>发生了什么</strong>', html)
        self.assertIn('<strong>为什么值得关注</strong>', html)
        self.assertIn('<strong>适用边界</strong>', html)
        self.assertIn(item.what_happened, html)

class ConfigTests(unittest.TestCase):
    def test_missing_configuration(self):
        self.assertEqual(len(validate_config({})), 4)

    def test_new_group_configuration(self):
        env = dict(
            DEEPSEEK_API_KEY='fixture',
            FEISHU_APP_ID='fixture',
            FEISHU_APP_SECRET='fixture',
            FEISHU_RECEIVE_ID='oc_fixture',
            FEISHU_RECEIVE_ID_TYPE='chat_id',
        )
        self.assertEqual(validate_config(env), [])
        env['FEISHU_RECEIVE_ID'] = 'ou_private-value'
        errors = validate_config(env)
        self.assertEqual(len(errors), 1)
        self.assertNotIn('private-value', errors[0])

    def test_personal_configuration(self):
        env = dict(
            DEEPSEEK_API_KEY='fixture',
            FEISHU_APP_ID='fixture',
            FEISHU_APP_SECRET='fixture',
            FEISHU_RECEIVE_ID='ou_fixture',
            FEISHU_RECEIVE_ID_TYPE='open_id',
        )
        self.assertEqual(validate_config(env), [])

    def test_legacy_group_configuration(self):
        env = dict(
            DEEPSEEK_API_KEY='fixture',
            FEISHU_APP_ID='fixture',
            FEISHU_APP_SECRET='fixture',
            FEISHU_BOT_CHAT_ID='oc_fixture',
        )
        self.assertEqual(validate_config(env), [])
        env['FEISHU_BOT_CHAT_ID'] = 'ou_private-value'
        errors = validate_config(env)
        self.assertEqual(len(errors), 1)
        self.assertNotIn('private-value', errors[0])

    def test_invalid_receiver_type(self):
        env = dict(
            DEEPSEEK_API_KEY='fixture',
            FEISHU_APP_ID='fixture',
            FEISHU_APP_SECRET='fixture',
            FEISHU_RECEIVE_ID='ou_fixture',
            FEISHU_RECEIVE_ID_TYPE='user_id',
        )
        self.assertEqual(
            validate_config(env),
            ['FEISHU_RECEIVE_ID_TYPE must be chat_id or open_id'],
        )
