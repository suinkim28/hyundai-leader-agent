#!/usr/bin/env python3
"""Fetch Microsoft Teams channel or chat content from a Teams deep link via Graph API.

Default auth flow is delegated auth, using localhost callback auth-code flow.
If application permissions are added later, `--flow client_credentials` can be
used with the same Entra app registration. Device-code is kept as a fallback.

인증, 토큰, 시크릿, 저수준 HTTP 는 `_graph_common.py` 에 있다 (SSOT). 이
파일은 Teams 딥링크를 해석하고 채널, 채팅 메시지를 가져오는 로직만 담는다.
"""

from __future__ import annotations

import argparse
import html
import json
import re
import sys
import urllib.parse
from html.parser import HTMLParser
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from _graph_common import (            # noqa: E402
    ENV_CLIENT_ID, ENV_CLIENT_SECRET, ENV_TENANT_ID,
    GRAPH_BASE, HttpRequestError,
    KEYCHAIN_CLIENT_ID, KEYCHAIN_CLIENT_SECRET, KEYCHAIN_TENANT_ID,
    get_auth_code_token, get_client_credentials_token, get_device_code_token,
    get_secret, http_get_json, load_dotenv,
)


class HtmlToText(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in {"p", "div", "br", "li"}:
            self.parts.append("\n")

    def get_text(self) -> str:
        text = html.unescape("".join(self.parts))
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def parse_teams_message_url(url: str) -> dict[str, str]:
    parsed = urllib.parse.urlparse(url)
    path_match = re.search(r"/l/message/([^/]+)/([^/?]+)", parsed.path)
    chat_match = re.search(r"/l/chat/([^/]+)/conversations", parsed.path)
    query = urllib.parse.parse_qs(parsed.query)

    if chat_match:
        chat_id = urllib.parse.unquote(chat_match.group(1))
        return {
            "tenant_id": query.get("tenantId", [""])[0],
            "source_type": "chat_room",
            "chat_id": chat_id,
            "chat_name": query.get("chatName", [""])[0],
        }

    if not path_match:
        raise ValueError("Unsupported Teams URL format")

    channel_id = urllib.parse.unquote(path_match.group(1))
    message_id = urllib.parse.unquote(path_match.group(2))
    team_id = query.get("groupId", [""])[0]
    tenant_id = query.get("tenantId", [""])[0]
    team_name = query.get("teamName", [""])[0]
    channel_name = query.get("channelName", [""])[0]

    context_raw = query.get("context", [""])[0]
    context_type = ""
    if context_raw:
        try:
            context_type = (json.loads(context_raw).get("contextType") or "").lower()
        except json.JSONDecodeError:
            context_type = ""

    is_chat_link = context_type == "chat" or channel_id.endswith("@thread.v2")
    if is_chat_link:
        if not channel_id or not message_id:
            raise ValueError("Missing chat/message identifiers in URL")
        return {
            "tenant_id": tenant_id,
            "source_type": "chat",
            "chat_id": channel_id,
            "message_id": message_id,
            "chat_name": query.get("chatName", [""])[0],
        }

    if not team_id or not message_id or not channel_id:
        raise ValueError("Missing team/channel/message identifiers in URL")

    return {
        "tenant_id": tenant_id,
        "source_type": "channel",
        "team_id": team_id,
        "channel_id": channel_id,
        "message_id": message_id,
        "team_name": team_name,
        "channel_name": channel_name,
    }


def fetch_channel_message(token: str, team_id: str, channel_id: str, message_id: str) -> dict:
    encoded_channel_id = urllib.parse.quote(channel_id, safe="")
    encoded_message_id = urllib.parse.quote(message_id, safe="")
    url = (
        f"{GRAPH_BASE}/teams/{team_id}/channels/{encoded_channel_id}/messages/{encoded_message_id}"
    )
    return http_get_json(url, token)


def fetch_channel_replies(token: str, team_id: str, channel_id: str, message_id: str) -> list[dict]:
    encoded_channel_id = urllib.parse.quote(channel_id, safe="")
    encoded_message_id = urllib.parse.quote(message_id, safe="")
    url = (
        f"{GRAPH_BASE}/teams/{team_id}/channels/{encoded_channel_id}/messages/"
        f"{encoded_message_id}/replies"
    )
    replies: list[dict] = []
    while url:
        data = http_get_json(url, token)
        replies.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
    return replies


def fetch_chat_message(token: str, chat_id: str, message_id: str) -> dict:
    encoded_chat_id = urllib.parse.quote(chat_id, safe="")
    encoded_message_id = urllib.parse.quote(message_id, safe="")
    url = f"{GRAPH_BASE}/chats/{encoded_chat_id}/messages/{encoded_message_id}"
    return http_get_json(url, token)


def fetch_chat_messages(token: str, chat_id: str, top: int = 50, page_limit: int = 20) -> list[dict]:
    top = max(1, min(top, 50))
    encoded_chat_id = urllib.parse.quote(chat_id, safe="")
    url = f"{GRAPH_BASE}/chats/{encoded_chat_id}/messages?$top={top}"
    messages: list[dict] = []
    pages = 0
    while url and pages < page_limit:
        data = http_get_json(url, token)
        messages.extend(data.get("value", []))
        url = data.get("@odata.nextLink")
        pages += 1
    return messages


def body_text(message: dict) -> str:
    body = message.get("body", {})
    content = body.get("content", "")
    if body.get("contentType") == "html":
        parser = HtmlToText()
        parser.feed(content)
        return parser.get_text()
    return str(content).strip()


def normalize_message(source: dict[str, str], message: dict) -> dict:
    from_user = (((message.get("from") or {}).get("user") or {}))
    return {
        "source_type": source["source_type"],
        "message_id": message.get("id", source.get("message_id")),
        "reply_to_id": message.get("replyToId"),
        "created_at": message.get("createdDateTime"),
        "last_modified_at": message.get("lastModifiedDateTime"),
        "subject": message.get("subject"),
        "from": {
            "display_name": from_user.get("displayName"),
            "id": from_user.get("id"),
            "user_identity_type": from_user.get("userIdentityType"),
        },
        "importance": message.get("importance"),
        "summary": body_text(message),
        "raw_body": message.get("body", {}),
        "web_url": message.get("webUrl"),
    }


def build_output(source: dict[str, str], message: dict, replies: list[dict] | None = None) -> dict:
    output = normalize_message(source, message)
    if source["source_type"] == "channel":
        output.update(
            {
                "team_name": source["team_name"],
                "channel_name": source["channel_name"],
                "team_id": source["team_id"],
                "channel_id": source["channel_id"],
            }
        )
    else:
        output.update(
            {
                "chat_name": source.get("chat_name", ""),
                "chat_id": source["chat_id"],
            }
        )
    output["replies"] = [normalize_message(source, reply) for reply in (replies or [])]
    return output


def build_chat_room_output(source: dict[str, str], messages: list[dict]) -> dict:
    normalized = [normalize_message({"source_type": "chat"}, message) for message in messages]
    return {
        "source_type": "chat_room",
        "chat_name": source.get("chat_name", ""),
        "chat_id": source["chat_id"],
        "messages": normalized,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch a Teams channel message from a Teams deep link via Microsoft Graph."
    )
    parser.add_argument("url", help="Teams deep link to a channel message")
    parser.add_argument(
        "--flow",
        choices=["auth_code", "device", "client_credentials"],
        default="auth_code",
        help="Auth flow to use. Default is delegated localhost auth-code flow.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full structured JSON output",
    )
    parser.add_argument(
        "--top",
        type=int,
        default=50,
        help="For chat room links, number of messages to request per page. Default: 50.",
    )
    parser.add_argument(
        "--page-limit",
        type=int,
        default=20,
        help="For chat room links, maximum number of Graph pages to follow. Default: 20.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        load_dotenv()
        source = parse_teams_message_url(args.url)
        tenant_id = get_secret(ENV_TENANT_ID, KEYCHAIN_TENANT_ID)
        client_id = get_secret(ENV_CLIENT_ID, KEYCHAIN_CLIENT_ID)

        if source["tenant_id"] and source["tenant_id"] != tenant_id:
            raise RuntimeError("Teams URL tenantId does not match the configured tenant")

        client_secret = get_secret(ENV_CLIENT_SECRET, KEYCHAIN_CLIENT_SECRET)
        if args.flow == "client_credentials":
            token = get_client_credentials_token(tenant_id, client_id, client_secret)
        elif args.flow == "auth_code":
            token = get_auth_code_token(tenant_id, client_id, client_secret)
        else:
            token = get_device_code_token(tenant_id, client_id, client_secret)

        replies: list[dict] = []
        if source["source_type"] == "channel":
            message = fetch_channel_message(
                token=token,
                team_id=source["team_id"],
                channel_id=source["channel_id"],
                message_id=source["message_id"],
            )
            replies = fetch_channel_replies(
                token=token,
                team_id=source["team_id"],
                channel_id=source["channel_id"],
                message_id=source["message_id"],
            )
            output = build_output(source, message, replies)
        elif source["source_type"] == "chat":
            message = fetch_chat_message(
                token=token,
                chat_id=source["chat_id"],
                message_id=source["message_id"],
            )
            output = build_output(source, message, replies)
        else:
            messages = fetch_chat_messages(
                token=token,
                chat_id=source["chat_id"],
                top=args.top,
                page_limit=args.page_limit,
            )
            output = build_chat_room_output(source, messages)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    if output["source_type"] == "channel":
        print(f"Team: {output['team_name'] or output['team_id']}")
        print(f"Channel: {output['channel_name'] or output['channel_id']}")
    elif output["source_type"] == "chat":
        print(f"Chat: {output.get('chat_name') or output['chat_id']}")
    else:
        print(f"Chat Room: {output.get('chat_name') or output['chat_id']}")
        print(f"Messages: {len(output.get('messages', []))}")
        print()
        for idx, message in enumerate(sorted(output.get("messages", []), key=lambda item: item.get("created_at") or ""), start=1):
            author = message["from"].get("display_name") or "Unknown"
            created = message.get("created_at") or ""
            header = f"[{idx}] {author}"
            if created:
                header += f" | {created}"
            print(header)
            if message.get("summary"):
                print(message["summary"])
            else:
                print("(no text)")
            print()
        return 0

    print(f"Message ID: {output['message_id']}")
    if output["from"]["display_name"]:
        print(f"From: {output['from']['display_name']}")
    if output["created_at"]:
        print(f"Created: {output['created_at']}")
    if output["summary"]:
        print("\nMessage:\n")
        print(output["summary"])
    if output.get("replies"):
        print("\nReplies:\n")
        for idx, reply in enumerate(output["replies"], start=1):
            author = reply["from"].get("display_name") or "Unknown"
            created = reply.get("created_at") or ""
            header = f"[{idx}] {author}"
            if created:
                header += f" | {created}"
            print(header)
            if reply.get("summary"):
                print(reply["summary"])
            else:
                print("(no text)")
            print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
