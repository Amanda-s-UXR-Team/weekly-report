
import os
import re
import json
import asyncio
import hashlib
from html import unescape
import aiohttp
from datetime import datetime, timedelta, timezone
from pathlib import Path

from reporting import sanitize_public_text


class FeishuSendError(RuntimeError):
    """A send failure carrying only a sanitized monitoring receipt."""

    def __init__(self, message: str, receipt: dict):
        super().__init__(message)
        self.receipt = receipt


class FeishuOwnershipError(RuntimeError):
    """Raised when a PDF cannot be transferred to its configured owner."""

class FeishuPublisher:
    """Publish content to Feishu (Lark) Cloud Documents."""

    BASE_URL = "https://open.feishu.cn/open-apis"
    RECEIVE_ID_TYPES = frozenset({"chat_id", "open_id"})
    PERMISSION_MEMBER_TYPES = {
        "chat_id": "openchat",
        "open_id": "openid",
    }
    # Document admin - will be granted full access to all created documents
    # TODO: Replace with your own Feishu Open ID
    ADMIN_OPEN_ID = os.environ.get("FEISHU_ADMIN_OPEN_ID", "")
    # Document retention period in days
    RETENTION_DAYS = 180
    # Path to store document records
    DOCUMENTS_DB = Path(__file__).parent.parent / "data" / "documents.json"

    def __init__(self):
        self.app_id = os.environ.get("FEISHU_APP_ID", "").strip()
        self.app_secret = os.environ.get("FEISHU_APP_SECRET", "").strip()
        # Folder token (optional, not used if can't add app as collaborator)
        self.folder_token = os.environ.get("FEISHU_FOLDER_TOKEN", "").strip()
        self._tenant_access_token = None
        self._token_expiry = 0

    @property
    def owner_open_id(self) -> str:
        """Return the configured report owner without logging the identifier."""
        return (
            os.environ.get("FEISHU_ADMIN_OPEN_ID", "")
            or self.ADMIN_OPEN_ID
        ).strip()

    def is_configured(self) -> bool:
        """Check if Feishu credentials are present."""
        return bool(self.app_id and self.app_secret)

    @classmethod
    def _validate_receive_id_type(cls, receive_id_type: str) -> str:
        """Return a supported Feishu receiver type or reject the configuration."""
        normalized = (receive_id_type or "chat_id").strip()
        if normalized not in cls.RECEIVE_ID_TYPES:
            raise ValueError(
                "receive_id_type must be 'chat_id' or 'open_id'"
            )
        return normalized

    async def _get_tenant_access_token(self) -> str:
        """Get or refresh tenant access token."""
        if self._tenant_access_token and datetime.now().timestamp() < self._token_expiry:
            return self._tenant_access_token

        url = f"{self.BASE_URL}/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.app_id,
            "app_secret": self.app_secret
        }

        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=payload) as response:
                if response.status != 200:
                    raise Exception(f"Feishu Auth Failed: {await response.text()}")

                data = await response.json()
                if data.get("code") != 0:
                    raise Exception(f"Feishu Auth Error: {data.get('msg')}")

                self._tenant_access_token = data["tenant_access_token"]
                # Expires in 2 hours, refresh slightly earlier
                self._token_expiry = datetime.now().timestamp() + data["expire"] - 300
                return self._tenant_access_token


    async def delete_document(self, doc_token: str) -> bool:
        """Delete a file or document by its token.

        Args:
            doc_token: The file/document token to delete

        Returns:
            True if deleted successfully, False otherwise
        """
        token = await self._get_tenant_access_token()
        headers = {"Authorization": f"Bearer {token}"}

        # The API is generic for files, type param is optional but safer to omit for generic files
        url = f"{self.BASE_URL}/drive/v1/files/{doc_token}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.delete(url, headers=headers) as response:
                    data = await response.json()
                    if data.get("code") == 0:
                        print(f"   ✅ Deleted file/document: {doc_token}")
                        return True
                    else:
                        print(f"   ❌ Delete failed: {data.get('msg', '')}")
                        return False
        except Exception as e:
            print(f"   ❌ Delete error: {e}")
            return False









    async def upload_file(self, file_path: str, file_name: str = None, parent_type: str = "explorer") -> dict:
        """Upload a file to Feishu Drive.

        Requires Permissions:
        - drive:drive (查看、评论、编辑和管理云空间所有文件)
        - OR drive:file:upload (上传文件到云空间)

        Args:
            file_path: Local path to the file
            file_name: Name for the uploaded file (defaults to original filename)
            parent_type: Parent type, "explorer" for app root folder

        Returns:
            Dict with file_token and url, or None on failure
        """
        if not self.is_configured():
            print("Feishu publisher not configured (missing APP_ID/SECRET)")
            return None

        token = await self._get_tenant_access_token()

        if not file_name:
            file_name = Path(file_path).name

        # Get file size
        file_size = Path(file_path).stat().st_size

        url = f"{self.BASE_URL}/drive/v1/files/upload_all"
        headers = {"Authorization": f"Bearer {token}"}

        try:
            with open(file_path, "rb") as f:
                # Use FormData for multipart upload
                form_data = aiohttp.FormData()
                form_data.add_field("file_name", file_name)
                form_data.add_field("parent_type", parent_type)
                form_data.add_field("parent_node", self.folder_token or "")
                form_data.add_field("size", str(file_size))
                form_data.add_field("file", f, filename=file_name, content_type="application/pdf")

                async with aiohttp.ClientSession() as session:
                    async with session.post(url, data=form_data, headers=headers) as response:
                        data = await response.json()
                        if data.get("code") != 0:
                            msg = data.get('msg')
                            print(f"   ❌ Upload failed: {msg}")
                            if "permission" in str(msg).lower() or "access denied" in str(msg).lower():
                                print("   💡 Check permissions: 'drive:drive' or 'drive:file:upload' is required.")
                                print("   💡 Remember to release a new version of your app after adding permissions!")
                            return None

                        file_token = data.get("data", {}).get("file_token")
                        if file_token:
                            file_url = f"https://feishu.cn/file/{file_token}"
                            print(f"   ✅ File uploaded: {file_url}")
                            return {"file_token": file_token, "url": file_url}
                        return None

        except Exception as e:
            print(f"   ❌ Upload error: {e}")
            return None

    async def _request_drive_json(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        payload: dict | None = None,
    ) -> dict:
        """Call a Drive endpoint and return its data envelope."""
        token = await self._get_tenant_access_token()
        headers = {"Authorization": f"Bearer {token}"}
        if payload is not None:
            headers["Content-Type"] = "application/json"

        async with aiohttp.ClientSession() as session:
            async with session.request(
                method,
                f"{self.BASE_URL}{path}",
                params=params,
                json=payload,
                headers=headers,
            ) as response:
                try:
                    data = await response.json()
                except Exception as exc:
                    raise FeishuOwnershipError(
                        "Feishu returned an unreadable ownership response."
                    ) from exc

        if response.status != 200 or data.get("code") != 0:
            raise FeishuOwnershipError(
                "Feishu ownership request failed: "
                f"HTTP {response.status}, code={data.get('code')}, "
                f"msg={data.get('msg', '')}"
            )
        return data.get("data", {})

    async def get_file_meta(self, file_token: str, resource_type: str) -> dict:
        """Read fresh ownership metadata for one Drive resource."""
        data = await self._request_drive_json(
            "POST",
            "/drive/v1/metas/batch_query",
            params={"user_id_type": "open_id"},
            payload={
                "request_docs": [
                    {"doc_token": file_token, "doc_type": resource_type}
                ],
                "with_url": True,
            },
        )
        metas = data.get("metas", [])
        return metas[0] if metas else {}

    async def transfer_file_owner(
        self,
        file_token: str,
        resource_type: str = "file",
        *,
        owner_open_id: str | None = None,
    ) -> bool:
        """Transfer a report to the configured owner and verify the result.

        The bot remains a full-access collaborator and the resource stays in
        its current folder. Failure is fatal so a report is never announced as
        delivered before the requested ownership state is confirmed.
        """
        target_owner = (owner_open_id or self.owner_open_id).strip()
        if not target_owner:
            raise FeishuOwnershipError(
                "FEISHU_ADMIN_OPEN_ID is required for PDF ownership transfer."
            )
        if resource_type != "file":
            raise FeishuOwnershipError(
                f"Unsupported ownership resource type: {resource_type}"
            )

        before = await self.get_file_meta(file_token, resource_type)
        if before.get("owner_id") != target_owner:
            await self._request_drive_json(
                "POST",
                f"/drive/v1/permissions/{file_token}/members/transfer_owner",
                params={
                    "type": resource_type,
                    "need_notification": "false",
                    "remove_old_owner": "false",
                    "old_owner_perm": "full_access",
                    "stay_put": "true",
                },
                payload={
                    "member_type": "openid",
                    "member_id": target_owner,
                },
            )

        verified = await self.get_file_meta(file_token, resource_type)
        if verified.get("owner_id") != target_owner:
            raise FeishuOwnershipError(
                "PDF ownership transfer could not be verified."
            )
        print("   ✅ PDF ownership transferred and verified")
        return True

    async def set_file_permission(
        self,
        file_token: str,
        receive_id: str = None,
        receive_id_type: str = "chat_id",
    ) -> bool:
        """Set file permission for the configured receiver and admin.

        Args:
            file_token: The file token
            receive_id: Optional chat_id/open_id to add as viewer
            receive_id_type: Message API receiver type (chat_id or open_id)

        Returns:
            True if successful
        """
        token = await self._get_tenant_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        members_url = f"{self.BASE_URL}/drive/v1/permissions/{file_token}/members?type=file&need_notification=false"
        success = False

        # Add admin user with full access
        if self.owner_open_id:
            admin_payload = {
                "member_type": "openid",
                "member_id": self.owner_open_id,
                "perm": "full_access"
            }
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(members_url, json=admin_payload, headers=headers) as response:
                        data = await response.json()
                        if data.get("code") == 0:
                            print(f"   ✅ Added admin with full_access to file")
                            success = True
                        else:
                            print(f"   ⚠️ Add admin to file warning: {data.get('msg', '')}")
            except Exception as e:
                print(f"   ⚠️ Add admin to file error: {e}")

        # The message API and Drive permission API use different type names.
        if receive_id:
            receive_id_type = self._validate_receive_id_type(receive_id_type)
            member_payload = {
                "member_type": self.PERMISSION_MEMBER_TYPES[receive_id_type],
                "member_id": receive_id,
                "perm": "view"
            }

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.post(members_url, json=member_payload, headers=headers) as response:
                        data = await response.json()
                        if data.get("code") == 0:
                            print("   ✅ Added report receiver as file viewer")
                            success = True
                        else:
                            print(f"   ⚠️ Add receiver to file warning: {data.get('msg', '')}")
            except Exception as e:
                print(f"   ⚠️ Add receiver to file error: {e}")

        return success

    async def upload_pdf(
        self,
        pdf_path: str,
        title: str,
        receive_id: str = None,
        receive_id_type: str = "chat_id",
    ) -> str:
        """Upload PDF and set permissions.

        Args:
            pdf_path: Local path to PDF file
            title: Title for the file
            receive_id: Chat ID or user Open ID for permission granting
            receive_id_type: Message API receiver type (chat_id or open_id)

        Returns:
            URL to access the PDF, or None on failure
        """
        if not self.is_configured():
            print("Feishu publisher not configured (missing APP_ID/SECRET)")
            return None

        try:
            print(f"📄 Uploading PDF to Feishu: {title}...")
            result = await self.upload_file(pdf_path, f"{title}.pdf")

            if not result:
                return None

            file_token = result["file_token"]

            # Set permissions
            print("   Setting file permissions...")
            await self.set_file_permission(
                file_token,
                receive_id,
                receive_id_type,
            )

            print("   Transferring PDF ownership...")
            await self.transfer_file_owner(file_token)

            # Record for cleanup
            self._record_document(file_token, title)

            return result["url"]

        except FeishuOwnershipError as e:
            print(f"❌ PDF ownership transfer failed: {e}")
            raise
        except Exception as e:
            print(f"❌ PDF Upload Error: {e}")
            return None


    def _record_document(self, doc_token: str, title: str):
        """Record document info for future cleanup."""
        try:
            # Ensure data directory exists
            self.DOCUMENTS_DB.parent.mkdir(parents=True, exist_ok=True)

            # Load existing records
            if self.DOCUMENTS_DB.exists():
                with open(self.DOCUMENTS_DB, 'r', encoding='utf-8') as f:
                    data = json.load(f)
            else:
                data = {"documents": []}

            # Add new record
            data["documents"].append({
                "token": doc_token,
                "title": title,
                "created_at": datetime.now().isoformat()
            })

            # Save
            with open(self.DOCUMENTS_DB, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=2)

        except Exception as e:
            print(f"   ⚠️ Failed to record document: {e}")

    async def cleanup_old_documents(self) -> int:
        """Delete documents older than RETENTION_DAYS.

        Returns:
            Number of documents deleted
        """
        if not self.DOCUMENTS_DB.exists():
            return 0

        try:
            with open(self.DOCUMENTS_DB, 'r', encoding='utf-8') as f:
                data = json.load(f)
        except Exception as e:
            print(f"   ⚠️ Failed to load document records: {e}")
            return 0

        cutoff_date = datetime.now() - timedelta(days=self.RETENTION_DAYS)
        deleted_count = 0
        remaining_docs = []

        for doc in data.get("documents", []):
            created_at = datetime.fromisoformat(doc["created_at"])

            if created_at < cutoff_date:
                # Delete old document
                print(f"   🗑️ Cleaning up old document: {doc['title']}")
                success = await self.delete_document(doc["token"])
                if success:
                    deleted_count += 1
                else:
                    # Keep in list if deletion failed
                    remaining_docs.append(doc)
            else:
                remaining_docs.append(doc)

        # Update records
        data["documents"] = remaining_docs
        with open(self.DOCUMENTS_DB, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)

        if deleted_count > 0:
            print(f"   ✅ Cleaned up {deleted_count} old documents")

        return deleted_count

    async def _send_message(
        self,
        receive_id: str,
        msg_type: str,
        content: str,
        receive_id_type: str = "chat_id",
    ) -> dict:
        """Send a message and return a strictly sanitized API receipt.

        ``api_ack_at`` means that Feishu accepted the API request. It does not
        prove that every group member received or read the message.
        """
        receive_id_type = self._validate_receive_id_type(receive_id_type)
        receipt = self._empty_send_receipt(None)
        try:
            token = await self._get_tenant_access_token()
            url = (
                f"{self.BASE_URL}/im/v1/messages"
                f"?receive_id_type={receive_id_type}"
            )
            headers = {
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json; charset=utf-8"
            }
            payload = {
                "receive_id": receive_id,
                "msg_type": msg_type,
                "content": sanitize_public_text(content)
            }
            receipt["request_started_at"] = self._monitor_timestamp()

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as response:
                    response_status = getattr(response, "status", None)
                    receipt["http_status"] = (
                        response_status if isinstance(response_status, int) else None
                    )
                    try:
                        data = await response.json()
                    except Exception:
                        receipt["status"] = "unknown"
                        receipt["error_code"] = "response_unreadable"
                        raise FeishuSendError(
                            "Feishu send outcome is unknown because the response was unreadable",
                            receipt,
                        ) from None

                    receipt["provider_code"] = self._safe_provider_code(data.get("code"))
                    http_failed = isinstance(response_status, int) and not (
                        200 <= response_status < 300
                    )
                    if http_failed or data.get("code") != 0:
                        receipt["status"] = "failed"
                        receipt["error_code"] = "provider_rejected"
                        raise FeishuSendError(
                            "Feishu send was rejected by the provider",
                            receipt,
                        )

                    result = data.get("data") if isinstance(data.get("data"), dict) else {}
                    message = result.get("message") if isinstance(result.get("message"), dict) else {}
                    message_id = result.get("message_id") or message.get("message_id")
                    receipt.update(
                        {
                            "api_ack_at": self._monitor_timestamp(),
                            "feishu_create_time": (
                                result.get("create_time") or message.get("create_time")
                            ),
                            "message_ref": self._message_ref(message_id),
                            "status": "acknowledged",
                        }
                    )
                    print("✅ Feishu API acknowledged message")
                    return receipt
        except FeishuSendError:
            raise
        except Exception:
            receipt["status"] = (
                "unknown" if receipt["request_started_at"] else "not_sent"
            )
            receipt["error_code"] = (
                "transport_error" if receipt["request_started_at"] else "auth_token_failed"
            )
            raise FeishuSendError(
                "Feishu send did not obtain a provider acknowledgement",
                receipt,
            ) from None

    @staticmethod
    def _monitor_timestamp() -> str:
        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )

    @staticmethod
    def _empty_send_receipt(started_at: str | None) -> dict:
        return {
            "request_started_at": started_at,
            "api_ack_at": None,
            "feishu_create_time": None,
            "http_status": None,
            "provider_code": None,
            "message_ref": None,
            "attempt_count": 1,
            "status": "sending",
            "error_code": None,
        }

    @staticmethod
    def _message_ref(message_id) -> str | None:
        if not message_id:
            return None
        digest = hashlib.sha256(str(message_id).encode("utf-8")).hexdigest()
        return f"sha256:{digest[:16]}"

    @staticmethod
    def _safe_provider_code(value):
        if isinstance(value, (int, float)):
            return value
        if isinstance(value, str) and len(value) <= 32:
            return value
        return None

    def _build_card_content(
        self,
        title: str,
        highlights: str,
        categories: dict,
        category_names: dict,
        doc_url: str = None,
        bilingual: bool = False,
    ) -> str:
        """Construct Feishu Interactive Card JSON content.

        Args:
            title: Card title
            highlights: Today's highlights text (top 3 eye-catching items)
            categories: Dict of category -> list of NewsItem (unused in simplified card)
            category_names: Dict of category_id -> display name (unused in simplified card)
            doc_url: Optional URL to the full document for click-through
        """
        elements = []

        # Only show highlights - top 3 eye-catching items
        if highlights:
            # Convert the shared structured HTML into readable Lark Markdown.
            readable_highlights = re.sub(
                r'<span class="highlight-number">(\d+)</span>',
                r'\n\1.\n',
                highlights,
                flags=re.IGNORECASE,
            )
            readable_highlights = re.sub(
                r'<br\s*/?>', '\n', readable_highlights, flags=re.IGNORECASE
            )
            readable_highlights = re.sub(
                r'</?strong>', '**', readable_highlights, flags=re.IGNORECASE
            )
            readable_highlights = re.sub(
                r'</p>', '\n\n', readable_highlights, flags=re.IGNORECASE
            )
            readable_highlights = re.sub(
                r'</div>', '\n', readable_highlights, flags=re.IGNORECASE
            )
            clean_highlights = sanitize_public_text(
                unescape(re.sub(r'<[^>]+>', '', readable_highlights)).strip()
            )
            clean_highlights = re.sub(r'\n{3,}', '\n\n', clean_highlights)
            elements.append({
                "tag": "div",
                "text": {
                    "tag": "lark_md",
                    "content": (
                        f"**⚡ {'本周要点 / Weekly Highlights' if bilingual else '今日要点'}**"
                        f"\n\n{clean_highlights}"
                    )
                }
            })

        # Action button to view full document (if doc_url provided)
        if doc_url:
            elements.append({"tag": "hr"})
            elements.append({
                "tag": "action",
                "actions": [
                    {
                        "tag": "button",
                        "text": {
                            "tag": "plain_text",
                            "content": (
                                "📖 查看双语报告 / View report"
                                if bilingual
                                else "📖 查看完整内容"
                            )
                        },
                        "type": "primary",
                        "multi_url": {
                            "url": doc_url,
                            "pc_url": doc_url,
                            "ios_url": doc_url,
                            "android_url": doc_url
                        }
                    }
                ]
            })

        # Footer / Note
        elements.append({
            "tag": "note",
            "elements": [
                {
                    "tag": "plain_text",
                    "content": "Generated by 手机分期资讯"
                }
            ]
        })

        card = {
            "config": {
                "wide_screen_mode": True
            },
            "header": {
                "template": "blue",
                "title": {
                    "tag": "plain_text",
                    "content": sanitize_public_text(title)
                }
            },
            "elements": elements
        }

        return json.dumps(card)

    async def send_digest_card(
        self,
        receive_id: str,
        title: str,
        highlights: str,
        categories: dict,
        category_names: dict,
        doc_url: str = None,
        bilingual: bool = False,
        receive_id_type: str = "chat_id",
    ):
        """Send the news digest as an interactive card.

        Args:
            receive_id: Feishu chat ID or user Open ID to send to
            title: Card title
            highlights: Today's highlights text
            categories: Dict of category -> list of NewsItem
            category_names: Dict of category_id -> display name
            doc_url: Optional URL to the full document for click-through
        """
        if not self.is_configured():
             print("Feishu publisher not configured.")
             return

        print("Sending Feishu card...")
        card_content = self._build_card_content(
            title,
            highlights,
            categories,
            category_names,
            doc_url,
            bilingual=bilingual,
        )
        return await self._send_message(
            receive_id,
            "interactive",
            card_content,
            receive_id_type,
        )

    @staticmethod
    def _safe_lark_md_line(value: str, limit: int = 260) -> str:
        compact = re.sub(
            r"\s+", " ", sanitize_public_text(value)
        ).strip()[:limit]
        return re.sub(r"([\\*_~\[\]()#>])", r"\\\1", compact)
