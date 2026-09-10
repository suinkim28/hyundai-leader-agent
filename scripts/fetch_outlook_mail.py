#!/usr/bin/env python3
"""Outlook 메일 조회 (읽기).

어디에 쓰는가
-------------
R2 아침 브리핑, R4 답변 초안, R5 결재 검토.

    bin/graph mail --unread --top 30 --json
    bin/graph mail --search "품질 리뷰"
    bin/graph mail --id <message_id>          # 본문 전문을 읽는다

목록은 미리보기(bodyPreview) 까지만 준다. 회신 초안을 쓰려면 `--id` 로
본문 전문을 먼저 읽는다. 미리보기만 보고 답장을 쓰지 않는다.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

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


def http_get_json(url: str, token: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HttpRequestError("GET", url, exc.code, body) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Outlook mail messages from Microsoft Graph."
    )
    parser.add_argument(
        "--folder",
        default="inbox",
        help='Mail folder id or well-known name. Default: "inbox".',
    )
    parser.add_argument(
        "--top",
        type=int,
        default=20,
        help="Maximum number of messages to fetch. Default: 20.",
    )
    parser.add_argument(
        "--unread",
        action="store_true",
        help="Fetch only unread messages.",
    )
    parser.add_argument(
        "--since",
        help="Filter to messages received on/after this ISO 8601 timestamp.",
    )
    parser.add_argument(
        "--search",
        help='Graph $search query, for example: "from:person@example.com". '
             "Graph 제약으로 --unread, --since 와 함께 쓸 수 없다.",
    )
    parser.add_argument(
        "--id",
        dest="message_id",
        help="이 메시지 하나의 본문 전문을 읽는다. 회신 초안을 쓰기 전에 쓴다.",
    )
    parser.add_argument(
        "--flow",
        choices=["auth_code", "device", "client_credentials"],
        default="auth_code",
        help="Auth flow to use. Default is delegated localhost auth-code flow.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full structured JSON output.",
    )
    return parser.parse_args()


def normalize_since(value: str) -> str:
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError(f"Timezone is required in datetime: {value}")
    return dt.astimezone().isoformat()


def fetch_messages(
    token: str,
    folder: str,
    top: int,
    unread_only: bool,
    since: str | None,
    search: str | None,
) -> list[dict]:
    base = f"{GRAPH_BASE}/me/mailFolders/{urllib.parse.quote(folder, safe='')}/messages"
    params = {
        "$top": str(top),
        "$select": ",".join(
            [
                "id",
                "subject",
                "from",
                "sender",
                "receivedDateTime",
                "isRead",
                "importance",
                "hasAttachments",
                "webLink",
                "bodyPreview",
            ]
        ),
    }

    filters: list[str] = []
    if unread_only:
        filters.append("isRead eq false")
    if since:
        filters.append(f"receivedDateTime ge {normalize_since(since)}")
    if filters:
        params["$filter"] = " and ".join(filters)

    headers_search = False
    if search:
        if filters:
            raise ValueError(
                "--search 는 --unread, --since 와 함께 쓸 수 없습니다 "
                "(Graph 가 $search 와 $filter 동시 사용을 거부합니다).\n"
                "  검색어로 먼저 찾은 뒤 결과에서 골라내십시오."
            )
        params["$search"] = f'"{search}"'
        headers_search = True
    else:
        params["$orderby"] = "receivedDateTime desc"

    url = f"{base}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    if headers_search:
        req.add_header("ConsistencyLevel", "eventual")

    try:
        with urllib.request.urlopen(req) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HttpRequestError("GET", url, exc.code, body) from exc

    return data.get("value", [])


def html_to_text(value: str) -> str:
    """본문 HTML 을 읽을 수 있는 평문으로 줄인다."""
    text = re.sub(r"(?is)<(script|style).*?</\1>", "", value)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</(p|div|tr|li|h[1-6])>", "\n", text)
    text = re.sub(r"(?s)<[^>]+>", "", text)
    text = html.unescape(text)
    text = re.sub(r"[ \t]+", " ", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def fetch_one(token: str, message_id: str) -> dict:
    fields = ("id,subject,from,sender,toRecipients,ccRecipients,receivedDateTime,"
              "isRead,importance,hasAttachments,webLink,body,conversationId")
    url = (f"{GRAPH_BASE}/me/messages/{urllib.parse.quote(message_id, safe='')}"
           f"?$select={fields}")
    return http_get_json(url, token)


def print_one(message: dict) -> None:
    def people(key):
        return ", ".join(
            f"{(r.get('emailAddress') or {}).get('name','')} "
            f"<{(r.get('emailAddress') or {}).get('address','')}>".strip()
            for r in (message.get(key) or [])
        )

    sender = (message.get("from") or {}).get("emailAddress") or {}
    print(f"제목: {message.get('subject') or '(제목 없음)'}")
    print(f"보낸이: {sender.get('name','')} <{sender.get('address','')}>")
    if people("toRecipients"):
        print(f"받는이: {people('toRecipients')}")
    if people("ccRecipients"):
        print(f"참조: {people('ccRecipients')}")
    print(f"수신: {message.get('receivedDateTime','')}")
    if message.get("hasAttachments"):
        print("첨부: 있음")
    print(f"id: {message.get('id')}")
    body = message.get("body") or {}
    content = body.get("content") or ""
    print("\n--- 본문 ---")
    print(html_to_text(content) if body.get("contentType") == "html" else content.strip())


def main() -> int:
    args = parse_args()

    try:
        load_dotenv()
        tenant_id = get_secret(ENV_TENANT_ID, KEYCHAIN_TENANT_ID)
        client_id = get_secret(ENV_CLIENT_ID, KEYCHAIN_CLIENT_ID)
        client_secret = get_secret(ENV_CLIENT_SECRET, KEYCHAIN_CLIENT_SECRET)

        if args.flow == "client_credentials":
            token = get_client_credentials_token(tenant_id, client_id, client_secret)
        elif args.flow == "auth_code":
            token = get_auth_code_token(tenant_id, client_id, client_secret)
        else:
            token = get_device_code_token(tenant_id, client_id, client_secret)

        if args.message_id:
            message = fetch_one(token, args.message_id)
            if args.json:
                print(json.dumps(message, ensure_ascii=False, indent=2))
            else:
                print_one(message)
            return 0

        messages = fetch_messages(
            token=token,
            folder=args.folder,
            top=args.top,
            unread_only=args.unread,
            since=args.since,
            search=args.search,
        )
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output = {
        "folder": args.folder,
        "count": len(messages),
        "messages": messages,
    }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    print(f"Folder: {output['folder']}")
    print(f"Messages: {output['count']}")

    for idx, message in enumerate(messages, start=1):
        from_name = (((message.get("from") or {}).get("emailAddress") or {}).get("name") or "")
        from_addr = (((message.get("from") or {}).get("emailAddress") or {}).get("address") or "")
        subject = message.get("subject") or "(no subject)"
        received = message.get("receivedDateTime") or ""
        flags = []
        if not message.get("isRead", True):
            flags.append("unread")
        if message.get("hasAttachments"):
            flags.append("attachment")
        if message.get("importance") and message.get("importance") != "normal":
            flags.append(str(message.get("importance")))
        flag_text = f" [{' | '.join(flags)}]" if flags else ""

        print()
        print(f"[{idx}] {subject}{flag_text}")
        if from_name or from_addr:
            print(f"From: {from_name} <{from_addr}>".strip())
        if received:
            print(f"Received: {received}")
        preview = (message.get("bodyPreview") or "").strip()
        if preview:
            print(f"Preview: {preview}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
