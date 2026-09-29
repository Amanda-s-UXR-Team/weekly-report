#!/usr/bin/env python3
"""Check configuration names/formats offline without logging secret values."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from dotenv import load_dotenv

REQUIRED = ('DEEPSEEK_API_KEY', 'FEISHU_APP_ID', 'FEISHU_APP_SECRET')
RECEIVE_ID_TYPES = {'chat_id': 'oc_', 'open_id': 'ou_'}

def validate_config(env):
    errors = [f'Missing Secret: {key}' for key in REQUIRED if not env.get(key, '').strip()]
    receive_id = env.get('FEISHU_RECEIVE_ID', '').strip()
    legacy_chat_id = env.get('FEISHU_BOT_CHAT_ID', '').strip()
    if receive_id:
        receive_id_type = (
            env.get('FEISHU_RECEIVE_ID_TYPE') or 'chat_id'
        ).strip().lower()
        expected_prefix = RECEIVE_ID_TYPES.get(receive_id_type)
        if not expected_prefix:
            errors.append(
                'FEISHU_RECEIVE_ID_TYPE must be chat_id or open_id'
            )
        elif any(
            not item.strip().startswith(expected_prefix)
            for item in receive_id.split(',')
            if item.strip()
        ):
            errors.append(
                f'FEISHU_RECEIVE_ID must begin with {expected_prefix} '
                f'when FEISHU_RECEIVE_ID_TYPE is {receive_id_type}'
            )
    elif legacy_chat_id:
        if any(
            not item.strip().startswith('oc_')
            for item in legacy_chat_id.split(',')
            if item.strip()
        ):
            errors.append(
                'FEISHU_BOT_CHAT_ID must be a group chat_id beginning with oc_'
            )
    else:
        errors.append(
            'Missing Secret: FEISHU_RECEIVE_ID '
            '(or legacy FEISHU_BOT_CHAT_ID)'
        )
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
