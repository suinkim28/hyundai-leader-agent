#!/usr/bin/env python3
"""Send a Microsoft Teams reply/message from a Teams deep link via Graph API."""

from __future__ import annotations

import argparse
import html
import json
import sys
import urllib.error
import urllib.parse
import urllib.request

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
    parse_teams_message_url,
)


def http_post_json(url: str, token: str, data: dict) -> dict:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HttpRequestError("POST", url, exc.code, body) from exc


def text_to_html(value: str) -> str:
    escaped = html.escape(value)
    return escaped.replace("\n", "<br>")


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
        message = f"{args.prefix} {message}"
    if not message:
        raise ValueError("Message body is empty")
    return message


def body_payload(message: str, is_html: bool) -> dict:
    return {
        "body": {
            "contentType": "html",
            "content": message if is_html else text_to_html(message),
        }
    }


def target_url(source: dict[str, str]) -> tuple[str, str]:
    if source["source_type"] == "channel":
        channel_id = urllib.parse.quote(source["channel_id"], safe="")
        message_id = urllib.parse.quote(source["message_id"], safe="")
        url = (
            f"{GRAPH_BASE}/teams/{source['team_id']}/channels/{channel_id}/"
            f"messages/{message_id}/replies"
        )
        return url, "channel_reply"

    if source["source_type"] in {"chat", "chat_room"}:
        chat_id = urllib.parse.quote(source["chat_id"], safe="")
        return f"{GRAPH_BASE}/chats/{chat_id}/messages", "chat_message"

    raise ValueError(f"Unsupported source type: {source['source_type']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Send a Teams reply/message. Channel message links are posted as thread replies; "
            "chat links are posted as new chat messages."
        )
    )
    parser.add_argument("url", help="Teams channel message or chat deep link")
    body_group = parser.add_mutually_exclusive_group(required=True)
    body_group.add_argument("--message", "-m", help="Message body")
    body_group.add_argument("--message-file", help="Path to a UTF-8 text/HTML file")
    body_group.add_argument("--stdin", action="store_true", help="Read message body from stdin")
    parser.add_argument("--prefix", default="[🦝]", help="Optional prefix, e.g. '[🦝]'. Pass '' to send with no prefix.")
    parser.add_argument("--html", action="store_true", help="Treat message body as Teams HTML")
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
        source = parse_teams_message_url(args.url)
        message = read_body(args)
        url, mode = target_url(source)
        payload = body_payload(message, args.html)

        if args.dry_run:
            print(f"Mode: {mode}")
            print(f"Target: {url}")
            print(json.dumps(payload, ensure_ascii=False, indent=2))
            return 0

        tenant_id = get_secret(ENV_TENANT_ID, KEYCHAIN_TENANT_ID)
        client_id = get_secret(ENV_CLIENT_ID, KEYCHAIN_CLIENT_ID)
        if source.get("tenant_id") and source["tenant_id"] != tenant_id:
            raise RuntimeError("Teams URL tenantId does not match the configured tenant")

        client_secret = get_secret(ENV_CLIENT_SECRET, KEYCHAIN_CLIENT_SECRET)
        if args.flow == "client_credentials":
            token = get_client_credentials_token(tenant_id, client_id, client_secret)
        elif args.flow == "device":
            token = get_device_code_token(tenant_id, client_id, client_secret)
        else:
            token = get_auth_code_token(tenant_id, client_id, client_secret)

        result = http_post_json(url, token, payload)
        print(f"Sent Teams {mode}: {result.get('id')}")
        if result.get("webUrl"):
            print(f"WebUrl: {result['webUrl']}")
        return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
