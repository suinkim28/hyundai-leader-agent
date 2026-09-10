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

CC 추가, 첨부가 필요하면 (`--cc`, `--attach`) 단순 reply/replyAll 대신
초안(draft)을 만들어 기존 수신자를 확인한 뒤 CC 를 더하고, 첨부를 올리고,
마지막에 전송하는 3단계로 간다. 단순 텍스트 회신은 기존 경로 그대로다.
"""

from __future__ import annotations

import argparse
import base64
import html
import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _graph_common import (
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


def http_patch_json(url: str, token: str, data: dict) -> dict:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="PATCH")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body) if body else {}
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HttpRequestError("PATCH", url, exc.code, body) from exc


def recipient(address: str) -> dict:
    return {"emailAddress": {"address": address}}


def build_attachment(path: str) -> dict:
    p = Path(path).expanduser()
    data = p.read_bytes()
    return {
        "@odata.type": "#microsoft.graph.fileAttachment",
        "name": p.name,
        "contentBytes": base64.b64encode(data).decode("ascii"),
    }


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
    parser.add_argument("--cc", action="append", default=[], metavar="EMAIL",
                         help="Add a recipient to Cc on top of the existing recipients. Repeatable.")
    parser.add_argument("--attach", action="append", default=[], metavar="PATH",
                         help="Local file to attach. Repeatable.")
    parser.add_argument("--dry-run", action="store_true", help="Print target and body without sending")
    parser.add_argument(
        "--flow",
        choices=["auth_code", "device", "client_credentials"],
        default="auth_code",
        help="Auth flow to use. Default: auth_code.",
    )
    return parser.parse_args()


def _get_token(args: argparse.Namespace) -> str:
    tenant_id = get_secret(ENV_TENANT_ID, KEYCHAIN_TENANT_ID)
    client_id = get_secret(ENV_CLIENT_ID, KEYCHAIN_CLIENT_ID)
    client_secret = get_secret(ENV_CLIENT_SECRET, KEYCHAIN_CLIENT_SECRET)
    if args.flow == "client_credentials":
        return get_client_credentials_token(tenant_id, client_id, client_secret)
    if args.flow == "auth_code":
        return get_auth_code_token(tenant_id, client_id, client_secret)
    return get_device_code_token(tenant_id, client_id, client_secret)


def main() -> int:
    args = parse_args()

    try:
        load_dotenv()
        message = read_body(args)

        # 항상 html 로 보낸다. 평문은 이스케이프한 뒤 줄바꿈만 <br> 로 바꾼다.
        # contentType 을 text 로 두고 <br> 을 넣으면 받는 쪽에 태그가 그대로 보인다.
        content = message if args.html else html.escape(message).replace("\n", "<br>")

        msg_id = urllib.parse.quote(args.message_id, safe="")
        want_draft = bool(args.cc or args.attach)
        action = "replyAll" if args.reply_all else "reply"

        if not want_draft:
            url = f"{GRAPH_BASE}/me/messages/{msg_id}/{action}"
            payload = {"message": {"body": {"contentType": "html", "content": content}}}

            if args.dry_run:
                print(f"Target: {url}")
                print(json.dumps(payload, ensure_ascii=False, indent=2))
                return 0

            token = _get_token(args)
            result = http_post_json(url, token, payload)
            print(f"회신 발송됨: {result.get('id', 'OK')}")
            return 0

        # CC 추가 또는 첨부가 있으면 초안을 만들어 기존 수신자를 보존한 채
        # CC 를 더하고, 첨부를 올린 뒤 보낸다. reply/replyAll 을 message
        # 오버라이드로 바로 부르면 Graph 가 수신자를 통째로 갈아치우기
        # 때문에, 기본 계산된 수신자를 먼저 받아와야 안전하다.
        attachments = [{"path": p, "size": Path(p).expanduser().stat().st_size} for p in args.attach]

        if args.dry_run:
            create_url = f"{GRAPH_BASE}/me/messages/{msg_id}/create{action[0].upper()}{action[1:]}"
            print(f"1) 초안 생성: POST {create_url}")
            print(f"2) 초안 수정: PATCH .../messages/<draft id>")
            print(f"   본문 길이: {len(content)}자")
            print(f"   추가 Cc: {', '.join(args.cc) if args.cc else '(없음)'}")
            for att in attachments:
                print(f"   첨부: {att['path']} ({att['size']:,} bytes)")
            print(f"3) 전송: POST .../messages/<draft id>/send")
            print("(기존 수신자는 로그인 후 초안 생성 시점에 Graph 가 계산합니다. "
                  "여기서는 로그인 없이 미리보기만 합니다.)")
            return 0

        token = _get_token(args)

        create_url = f"{GRAPH_BASE}/me/messages/{msg_id}/create{action[0].upper()}{action[1:]}"
        draft = http_post_json(create_url, token, {})
        draft_id = draft["id"]
        draft_url = f"{GRAPH_BASE}/me/messages/{urllib.parse.quote(draft_id, safe='')}"

        existing_cc = draft.get("ccRecipients", [])
        existing_addrs = {r["emailAddress"]["address"].lower() for r in existing_cc}
        merged_cc = list(existing_cc)
        for addr in args.cc:
            if addr.lower() not in existing_addrs:
                merged_cc.append(recipient(addr))
                existing_addrs.add(addr.lower())

        http_patch_json(draft_url, token, {
            "body": {"contentType": "html", "content": content},
            "ccRecipients": merged_cc,
        })

        for att in attachments:
            http_post_json(f"{draft_url}/attachments", token, build_attachment(att["path"]))

        http_post_json(f"{draft_url}/send", token, {})
        print(f"회신 발송됨: {draft_id}")
        print(f"To: {', '.join(r['emailAddress']['address'] for r in draft.get('toRecipients', []))}")
        print(f"Cc: {', '.join(r['emailAddress']['address'] for r in merged_cc)}")
        if attachments:
            print(f"첨부: {', '.join(Path(a['path']).name for a in attachments)}")
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
