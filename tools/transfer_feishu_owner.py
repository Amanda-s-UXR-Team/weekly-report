#!/usr/bin/env python3
"""Transfer one existing Feishu PDF to the configured report owner."""

import argparse
import asyncio
import re
import sys
from pathlib import Path

from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from publishers.feishu_publisher import FeishuOwnershipError, FeishuPublisher


FILE_TOKEN_PATTERN = re.compile(r"^[A-Za-z0-9_-]{10,128}$")


async def transfer(file_token: str) -> None:
    publisher = FeishuPublisher()
    if not publisher.is_configured():
        raise FeishuOwnershipError("Feishu publisher is not configured.")
    await publisher.transfer_file_owner(file_token, "file")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Transfer one Feishu PDF to FEISHU_ADMIN_OPEN_ID."
    )
    parser.add_argument("--file-token", required=True)
    args = parser.parse_args()

    file_token = args.file_token.strip()
    if not FILE_TOKEN_PATTERN.fullmatch(file_token):
        parser.error("--file-token is not a valid Feishu file token")

    load_dotenv()
    asyncio.run(transfer(file_token))
    print("Existing PDF ownership transfer completed and verified.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
