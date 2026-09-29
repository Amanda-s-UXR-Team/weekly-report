#!/usr/bin/env python3
"""Check configuration names/formats offline without logging secret values."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

REQUIRED = ('DEEPSEEK_API_KEY', 'FEISHU_APP_ID', 'FEISHU_APP_SECRET', 'FEISHU_BOT_CHAT_ID')

def validate_config(env):
    errors = [f'Missing Secret: {key}' for key in REQUIRED if not env.get(key, '').strip()]
    chat_id = env.get('FEISHU_BOT_CHAT_ID', '').strip()
    if chat_id and not chat_id.startswith('oc_'):
        errors.append('FEISHU_BOT_CHAT_ID must be a group chat_id beginning with oc_')
    base = env.get('DEEPSEEK_BASE_URL') or 'https://api.deepseek.com'
    try:
        parsed = urlsplit(base.strip())
        valid = parsed.scheme == 'https' and parsed.hostname and not any((parsed.username, parsed.password, parsed.query, parsed.fragment))
    except ValueError:
        valid = False
    if not valid:
        errors.append('DEEPSEEK_BASE_URL must be an HTTPS API base URL without credentials or query')
    return errors

def main():
    load_dotenv(Path(__file__).resolve().parents[1] / '.env')
    errors = validate_config(os.environ)
    if errors:
        for error in errors:
            print(error)
        return 1
    print('Required configuration is present. This offline check does not verify API access, balance, Feishu permissions or membership.')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
