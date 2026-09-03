#!/usr/bin/env python3
"""Fetch Outlook mail messages from Microsoft Graph."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime

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
        help='Graph $search query, for example: "from:person@example.com".',
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
