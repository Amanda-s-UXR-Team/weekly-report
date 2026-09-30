from __future__ import annotations
import json
import unittest
from unittest.mock import AsyncMock, MagicMock, patch
from monitoring import empty_feishu_receipt
from publishers.feishu_publisher import (
    FeishuOwnershipError,
    FeishuPublisher,
    FeishuSendError,
)

class FakeResponse:
    def __init__(self, status: int, payload: dict):
        self.status = status
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self.payload


class UnreadableResponse(FakeResponse):
    async def json(self):
        raise ValueError("invalid json")


class FakeSession:
    def __init__(self, response: FakeResponse):
        self.response = response
        self.request = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, url, *, json, headers):
        self.request = (url, json, headers)
        return self.response


class FeishuReceiptTests(unittest.IsolatedAsyncioTestCase):

    async def test_owner_transfer_keeps_bot_access_and_verifies_owner(self):
        publisher = FeishuPublisher()
        publisher.get_file_meta = AsyncMock(side_effect=[
            {"owner_id": "app_owner"},
            {"owner_id": "ou_owner_fixture"},
        ])
        publisher._request_drive_json = AsyncMock(return_value={})

        result = await publisher.transfer_file_owner(
            "offline-file",
            owner_open_id="ou_owner_fixture",
        )

        self.assertTrue(result)
        transfer_call = publisher._request_drive_json.call_args
        self.assertEqual(
            transfer_call.args,
            (
                "POST",
                "/drive/v1/permissions/offline-file/members/transfer_owner",
            ),
        )
        self.assertEqual(
            transfer_call.kwargs["params"],
            {
                "type": "file",
                "need_notification": "false",
                "remove_old_owner": "false",
                "old_owner_perm": "full_access",
                "stay_put": "true",
            },
        )
        self.assertEqual(
            transfer_call.kwargs["payload"],
            {"member_type": "openid", "member_id": "ou_owner_fixture"},
        )

    async def test_owner_transfer_fails_when_fresh_read_does_not_match(self):
        publisher = FeishuPublisher()
        publisher.get_file_meta = AsyncMock(return_value={"owner_id": "app_owner"})
        publisher._request_drive_json = AsyncMock(return_value={})

        with self.assertRaisesRegex(FeishuOwnershipError, "could not be verified"):
            await publisher.transfer_file_owner(
                "offline-file",
                owner_open_id="ou_owner_fixture",
            )

    async def test_pdf_upload_requires_verified_owner_transfer(self):
        publisher = FeishuPublisher()
        publisher.app_id = "fixture"
        publisher.app_secret = "fixture"
        publisher.upload_file = AsyncMock(return_value={
            "file_token": "offline-file",
            "url": "https://example.invalid/file",
        })
        publisher.set_file_permission = AsyncMock(return_value=True)
        publisher.transfer_file_owner = AsyncMock(return_value=True)
        publisher._record_document = MagicMock()

        result = await publisher.upload_pdf(
            "offline.pdf",
            "Offline report",
            "ou_receiver_fixture",
            "open_id",
        )

        self.assertEqual(result, "https://example.invalid/file")
        publisher.transfer_file_owner.assert_awaited_once_with("offline-file")
        publisher._record_document.assert_called_once_with(
            "offline-file", "Offline report"
        )

    async def test_success_returns_sanitized_acknowledgement(self):
        publisher = FeishuPublisher()
        publisher._get_tenant_access_token = AsyncMock(return_value="secret-token")
        session = FakeSession(
            FakeResponse(
                200,
                {
                    "code": 0,
                    "data": {
                        "message_id": "om_sensitive_message_id",
                        "create_time": "1788067494000",
                    },
                },
            )
        )
        with patch(
            "publishers.feishu_publisher.aiohttp.ClientSession",
            return_value=session,
        ):
            result = await publisher._send_message(
                "oc_sensitive_chat_id", "text", "hello"
            )

        self.assertTrue(session.request[0].endswith("receive_id_type=chat_id"))
        self.assertEqual(result["status"], "acknowledged")
        self.assertEqual(result["http_status"], 200)
        self.assertEqual(result["provider_code"], 0)
        self.assertEqual(result["attempt_count"], 1)
        self.assertTrue(result["request_started_at"].endswith("Z"))
        self.assertTrue(result["api_ack_at"].endswith("Z"))
        self.assertTrue(result["message_ref"].startswith("sha256:"))
        serialized = json.dumps(result)
        self.assertNotIn("om_sensitive_message_id", serialized)
        self.assertNotIn("oc_sensitive_chat_id", serialized)
        self.assertNotIn("secret-token", serialized)

    async def test_personal_message_uses_open_id_receiver_type(self):
        publisher = FeishuPublisher()
        publisher._get_tenant_access_token = AsyncMock(return_value="secret-token")
        session = FakeSession(FakeResponse(200, {"code": 0, "data": {}}))
        with patch(
            "publishers.feishu_publisher.aiohttp.ClientSession",
            return_value=session,
        ):
            result = await publisher._send_message(
                "ou_sensitive_user",
                "text",
                "hello",
                "open_id",
            )

        self.assertTrue(session.request[0].endswith("receive_id_type=open_id"))
        self.assertEqual(session.request[1]["receive_id"], "ou_sensitive_user")
        self.assertEqual(result["status"], "acknowledged")

    async def test_digest_card_forwards_personal_receiver_type(self):
        publisher = FeishuPublisher()
        publisher.app_id = "fixture"
        publisher.app_secret = "fixture"
        publisher._send_message = AsyncMock(return_value={"status": "acknowledged"})

        await publisher.send_digest_card(
            "ou_sensitive_user",
            "Daily insights",
            "Highlights",
            {},
            {},
            receive_id_type="open_id",
        )

        self.assertEqual(publisher._send_message.call_args.args[0], "ou_sensitive_user")
        self.assertEqual(publisher._send_message.call_args.args[-1], "open_id")

    def test_digest_card_preserves_structured_highlight_labels(self):
        highlights = (
            '<div class="highlight-item"><span class="highlight-number">1</span>'
            '<div class="highlight-text">'
            '<p class="highlight-section"><strong>发生了什么</strong><br>发布了新优惠。</p>'
            '<p class="highlight-section"><strong>为什么值得关注</strong><br>影响总成本比较。</p>'
            '<p class="highlight-section"><strong>适用边界</strong><br>仅限指定用户。</p>'
            '</div></div>'
        )
        publisher = FeishuPublisher()
        card = json.loads(
            publisher._build_card_content(
                "手机分期资讯｜2026-09-30",
                highlights,
                {},
                {},
            )
        )
        content = card["elements"][0]["text"]["content"]
        self.assertIn("1.", content)
        self.assertIn("**发生了什么**", content)
        self.assertIn("**为什么值得关注**", content)
        self.assertIn("**适用边界**", content)
        self.assertIn("发布了新优惠。\n\n**为什么值得关注**", content)

    async def test_file_permission_maps_receiver_types(self):
        publisher = FeishuPublisher()
        publisher._get_tenant_access_token = AsyncMock(return_value="secret-token")

        for receive_id, receive_id_type, member_type in (
            ("oc_sensitive_chat", "chat_id", "openchat"),
            ("ou_sensitive_user", "open_id", "openid"),
        ):
            with self.subTest(receive_id_type=receive_id_type):
                session = FakeSession(FakeResponse(200, {"code": 0}))
                with patch.object(FeishuPublisher, "ADMIN_OPEN_ID", ""), patch(
                    "publishers.feishu_publisher.aiohttp.ClientSession",
                    return_value=session,
                ):
                    result = await publisher.set_file_permission(
                        "offline-file",
                        receive_id,
                        receive_id_type,
                    )
                self.assertTrue(result)
                self.assertEqual(session.request[1]["member_type"], member_type)
                self.assertEqual(session.request[1]["member_id"], receive_id)

    async def test_invalid_receiver_type_is_rejected_before_network(self):
        publisher = FeishuPublisher()
        publisher._get_tenant_access_token = AsyncMock(return_value="secret-token")
        with self.assertRaisesRegex(ValueError, "chat_id.*open_id"):
            await publisher._send_message(
                "ou_sensitive_user",
                "text",
                "hello",
                "user_id",
            )
        publisher._get_tenant_access_token.assert_not_awaited()

    async def test_provider_failure_raises_with_sanitized_receipt(self):
        publisher = FeishuPublisher()
        publisher._get_tenant_access_token = AsyncMock(return_value="secret-token")
        session = FakeSession(
            FakeResponse(
                400,
                {"code": 230001, "msg": "chat oc_sensitive does not exist"},
            )
        )
        with patch(
            "publishers.feishu_publisher.aiohttp.ClientSession",
            return_value=session,
        ):
            with self.assertRaises(FeishuSendError) as caught:
                await publisher._send_message(
                    "oc_sensitive_chat_id", "text", "hello"
                )

        receipt = caught.exception.receipt
        self.assertEqual(receipt["status"], "failed")
        self.assertEqual(receipt["http_status"], 400)
        self.assertEqual(receipt["provider_code"], 230001)
        self.assertEqual(receipt["error_code"], "provider_rejected")
        self.assertIsNone(receipt["api_ack_at"])
        self.assertNotIn("oc_sensitive", json.dumps(receipt))
        self.assertNotIn("oc_sensitive", str(caught.exception))

    async def test_unreadable_response_is_unknown_not_failed(self):
        publisher = FeishuPublisher()
        publisher._get_tenant_access_token = AsyncMock(return_value="secret-token")
        with patch(
            "publishers.feishu_publisher.aiohttp.ClientSession",
            return_value=FakeSession(UnreadableResponse(200, {})),
        ):
            with self.assertRaises(FeishuSendError) as caught:
                await publisher._send_message("oc_sensitive_chat_id", "text", "hello")
        self.assertEqual(caught.exception.receipt["status"], "unknown")
        self.assertEqual(caught.exception.receipt["error_code"], "response_unreadable")
