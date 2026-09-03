#!/usr/bin/env python3
"""Outlook 메일 회신 (쓰기).

어디에 쓰는가
-------------
R4 답변 초안. 되돌릴 수 없으므로 훅이 본부장 확인을 받는다. 확인을
요청하기 전에 반드시 `--dry-run` 으로 무엇이 나갈지 먼저 보여드릴 것.
`--dry-run` 은 로그인 없이 돈다.

    bin/graph mail --unread --json          # message_id 확인
    bin/graph mail-reply <id> --message "..." --dry-run
    bin/graph mail-reply <id> --message "..."
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_teams_message import (
    ENV_CLIENT_ID,
    ENV_CLIENT_SECRET,
    ENV_TENANT_ID,
    GRAPH_BASE,
    HttpRequestError,
    KEYCHAIN_CLIENT_ID,
    KEYCHAIN_CLIENT_SECRET,
    KEYCHAIN_TENANT_ID,
    get_auth_code_token,
    get_client_credentials_token,
    get_device_code_token,
    get_secret,
    load_dotenv,
)


def http_post_json(url: str, token: str, data: dict) -> dict:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            if not body:
                return {}
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HttpRequestError("POST", url, exc.code, body) from exc


def read_body(args: argparse.Namespace) -> str:
    if args.message_file:
        with open(args.message_file, encoding="utf-8") as handle:
            message = handle.read()
    elif args.stdin:
        message = sys.stdin.read()
    else:
        message = args.message or ""

    message = message.strip()
    if args.prefix:
        message = f"{args.prefix}\n\n{message}"
    if not message:
        raise ValueError("Message body is empty")
    return message


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Reply to an Outlook mail message via Microsoft Graph."
    )
    parser.add_argument("message_id", help="The Outlook message ID to reply to")
    body_group = parser.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--message", "-m", help="Reply body (plain text)")
    body_group.add_argument("--message-file", help="Path to a UTF-8 text/HTML file")
    body_group.add_argument("--stdin", action="store_true", help="Read reply body from stdin")
    parser.add_argument("--prefix", default="", help="Optional prefix text")
    parser.add_argument("--html", action="store_true", help="Treat message body as HTML")
    parser.add_argument("--reply-all", action="store_true", help="Reply to all recipients (default: reply to sender only)")
    parser.add_argument("--dry-run", action="store_true", help="Print target and body without sending")
    parser.add_argument(
        "--flow",
        choices=["auth_code", "device", "client_credentials"],
        default="auth_code",
        help="Auth flow to use. Default: auth_code.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        load_dotenv()
        message = read_body(args)

        # 항상 html 로 보낸다. 평문은 이스케이프한 뒤 줄바꿈만 <br> 로 바꾼다.
        # contentType 을 text 로 두고 <br> 을 넣으면 받는 쪽에 태그가 그대로 보인다.
        content = message if args.html else html.escape(message).replace("\n", "<br>")

        endpoint = "replyAll" if args.reply_all else "reply"
        url = f"{GRAPH_BASE}/me/messages/{urllib.parse.quote(args.message_id, safe='')}/{endpoint}"

        payload = {"message": {"body": {"contentType": "html", "content": content}}}

        if args.dry_run:
            print(f"Target: {url}")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        tenant_id = get_secret(ENV_TENANT_ID, KEYCHAIN_TENANT_ID)
        client_id = get_secret(ENV_CLIENT_ID, KEYCHAIN_CLIENT_ID)
        client_secret = get_secret(ENV_CLIENT_SECRET, KEYCHAIN_CLIENT_SECRET)
        if args.flow == "client_credentials":
            token = get_client_credentials_token(tenant_id, client_id, client_secret)
        elif args.flow == "auth_code":
            token = get_auth_code_token(tenant_id, client_id, client_secret)
        else:
            token = get_device_code_token(tenant_id, client_id, client_secret)

        result = http_post_json(url, token, payload)
        print(f"회신 발송됨: {result.get('id', 'OK')}")
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
