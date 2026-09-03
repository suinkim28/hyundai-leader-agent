#!/usr/bin/env python3
"""Fetch Microsoft Teams channel or chat content from a Teams deep link via Graph API.

Default auth flow is delegated auth, using localhost callback auth-code flow.
If application permissions are added later, `--flow client_credentials` can be
used with the same Entra app registration. Device-code is kept as a fallback.
"""

from __future__ import annotations

import argparse
import html
import json
import os
import re
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser
from http.server import BaseHTTPRequestHandler, HTTPServer


GRAPH_BASE = "https://graph.microsoft.com/v1.0"
TOKEN_SCOPE_CLIENT_CREDENTIALS = "https://graph.microsoft.com/.default"
# --- 요청 스코프 -----------------------------------------------------------
#
# **Entra 에 동의된 권한과 여기 적은 스코프는 별개다.**
# 동의만 되어 있고 여기 없으면 토큰에 담기지 않아 그 기능은 동작하지 않는다.
# 반대로 여기 있는데 동의가 없으면 로그인 자체가 실패한다.
# 승인이 단계적으로 나오므로, 코드를 고치지 않고 텍스트 파일로 관리한다.
#
#   .claude/graph_scopes.txt   한 줄에 하나씩. `#` 로 시작하면 주석.
#
# 파일이 없으면 아래 1단계 기본값을 쓴다. 승인이 추가될 때마다 파일에 줄을
# 더하고 `python3 scripts/fetch_outlook_mail.py --top 1` 로 재로그인한다.

_DEFAULT_SCOPES = (
    "offline_access openid profile User.Read "
    "User.Read.All "
    "Team.ReadBasic.All Channel.ReadBasic.All ChannelMessage.Read.All "
    "ChannelMessage.Send Chat.Read Chat.ReadBasic ChatMessage.Read "
    "ChatMessage.Send Calendars.Read Calendars.Read.Shared "
    "Calendars.ReadBasic Calendars.ReadWrite "
    "Mail.Read Mail.ReadWrite Mail.Send"
)


def _load_scopes() -> str:
    """`.claude/graph_scopes.txt` 가 있으면 그것을, 없으면 기본값을 쓴다."""
    try:
        from pathlib import Path
        path = Path(__file__).resolve().parents[1] / ".claude" / "graph_scopes.txt"
        if not path.exists():
            return _DEFAULT_SCOPES
        wanted = [
            line.strip()
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        return " ".join(wanted) if wanted else _DEFAULT_SCOPES
    except Exception:
        return _DEFAULT_SCOPES


DEVICE_SCOPES = (
    _load_scopes()
)
ENV_CLIENT_ID = "MICROSOFT_GRAPH_CLIENT_ID"
ENV_CLIENT_SECRET = "MICROSOFT_GRAPH_CLIENT_SECRET"
ENV_TENANT_ID = "MICROSOFT_GRAPH_TENANT_ID"
ENV_REFRESH_TOKEN = "MICROSOFT_GRAPH_REFRESH_TOKEN"
KEYCHAIN_CLIENT_ID = "hmg-agent-graph-client-id"
KEYCHAIN_CLIENT_SECRET = "hmg-agent-graph-client-secret"
KEYCHAIN_TENANT_ID = "hmg-agent-graph-tenant-id"
KEYCHAIN_REFRESH_TOKEN = "hmg-agent-graph-refresh-token"
LOCAL_REDIRECT_PORT = 8765
LOCAL_REDIRECT_URI = f"http://localhost:{LOCAL_REDIRECT_PORT}/callback"
DOTENV_PATHS: list[str] = []


class HttpRequestError(RuntimeError):
    def __init__(self, method: str, url: str, status: int, body: str) -> None:
        self.method = method
        self.url = url
        self.status = status
        self.body = body
        super().__init__(f"{method} {url} failed: {status} {body}")


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


def load_dotenv() -> None:
    script_dir = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(script_dir), ".env"),
    ]
    seen: set[str] = set()
    for path in candidates:
        if path in seen or not os.path.exists(path):
            continue
        seen.add(path)
        DOTENV_PATHS.append(path)
        with open(path, encoding="utf-8") as handle:
            for raw_line in handle:
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()
                if not key or key in os.environ:
                    continue
                if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                    value = value[1:-1]
                os.environ[key] = value


def is_placeholder_secret(value: str) -> bool:
    normalized = value.strip()
    return (
        not normalized
        or normalized.startswith("your-")
        or normalized in {"placeholder", "changeme", "change-me"}
    )


def update_dotenv_value(key: str, value: str) -> None:
    if not DOTENV_PATHS:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        DOTENV_PATHS.append(os.path.join(os.path.dirname(script_dir), ".env"))

    path = DOTENV_PATHS[-1]
    lines: list[str] = []
    found = False
    if os.path.exists(path):
        with open(path, encoding="utf-8") as handle:
            lines = handle.readlines()

    for index, raw_line in enumerate(lines):
        stripped = raw_line.lstrip()
        if stripped.startswith("#") or "=" not in stripped:
            continue
        current_key = stripped.split("=", 1)[0].strip()
        if current_key == key:
            lines[index] = f"{key}={value}\n"
            found = True
            break

    if not found:
        if lines and not lines[-1].endswith("\n"):
            lines[-1] += "\n"
        lines.append(f"{key}={value}\n")

    with open(path, "w", encoding="utf-8") as handle:
        handle.writelines(lines)


def keychain_get(service: str) -> str:
    """자격증명 저장소에서 값 하나를 읽는다.

    실제 구현은 `secret_store` 에 있다. macOS 키체인, Windows DPAPI,
    그 외 플랫폼의 파일 폴백을 한곳에서 관리하기 위해 위임한다.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        from secret_store import keychain_get as _get
        value = _get(service)
        if value:
            return value
    except Exception:
        pass

    # 공유 경로(~/.config/microsoft-graph)는 읽지 않는다. 같은 Mac 에서 다른
    # 워크스페이스가 쓰던 토큰을 이 에이전트가 주워 오면 안 된다.
    return ""

def keychain_set(service: str, value: str) -> None:
    # macOS Keychain support
    if sys.platform == "darwin":
        cmd = [
            "security",
            "add-generic-password",
            "-a",
            os.environ.get("USER", ""),
            "-s",
            service,
            "-w",
            value,
            "-U",
        ]
        result = subprocess.run(cmd, check=False, capture_output=True, text=True)
        if result.returncode == 0:
            return
            
    # Linux or macOS fallback: save to environment and local file
    env_key = service.upper().replace("-", "_")
    os.environ[env_key] = value
    
    config_dir = os.path.expanduser("~/.config/microsoft-graph")
    os.makedirs(config_dir, exist_ok=True)
    config_path = os.path.join(config_dir, "secrets.json")
    
    data = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except json.JSONDecodeError:
            pass
            
    data[service] = value
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_secret(env_name: str, keychain_service: str) -> str:
    value = os.environ.get(env_name, "").strip()
    if value and not is_placeholder_secret(value):
        return value
    return keychain_get(keychain_service)


def set_refresh_token(value: str) -> None:
    os.environ[ENV_REFRESH_TOKEN] = value
    # Keychain is the single source of truth; .env was retired 2026-08-27
    # after an agent clobbered it and four live secrets had to be recovered.
    try:
        keychain_set(KEYCHAIN_REFRESH_TOKEN, value)
    except RuntimeError as exc:
        print(f"WARNING: refresh token cached in env only ({exc})", file=sys.stderr)


def get_cached_refresh_token() -> str:
    refresh_token = os.environ.get(ENV_REFRESH_TOKEN, "").strip()
    if refresh_token and not is_placeholder_secret(refresh_token):
        return refresh_token
    try:
        return keychain_get(KEYCHAIN_REFRESH_TOKEN)
    except RuntimeError:
        return ""


def http_post_form(url: str, data: dict[str, str]) -> dict:
    payload = urllib.parse.urlencode(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HttpRequestError("POST", url, exc.code, body) from exc


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


def token_endpoint(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


def device_code_endpoint(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/devicecode"


def get_device_code_token(tenant_id: str, client_id: str, client_secret: str | None = None) -> str:
    refresh_token = get_cached_refresh_token()

    if refresh_token:
        try:
            token = http_post_form(
                token_endpoint(tenant_id),
                {
                    "client_id": client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "scope": DEVICE_SCOPES,
                    **({"client_secret": client_secret} if client_secret else {}),
                },
            )
            if "refresh_token" in token:
                set_refresh_token(token["refresh_token"])
            return token["access_token"]
        except HttpRequestError as exc:
            print(
                f"WARNING: cached Microsoft Graph refresh token was rejected: {exc.status}",
                file=sys.stderr,
            )
            pass

    device_code = http_post_form(
        device_code_endpoint(tenant_id),
        {
            "client_id": client_id,
            "scope": DEVICE_SCOPES,
        },
    )

    print(device_code["message"], file=sys.stderr)

    expires_at = time.time() + int(device_code.get("expires_in", 900))
    interval = int(device_code.get("interval", 5))

    while time.time() < expires_at:
        time.sleep(interval)
        try:
            token = http_post_form(
                token_endpoint(tenant_id),
                {
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                    "client_id": client_id,
                    "device_code": device_code["device_code"],
                    **({"client_secret": client_secret} if client_secret else {}),
                },
            )
            if "refresh_token" in token:
                set_refresh_token(token["refresh_token"])
            return token["access_token"]
        except HttpRequestError as exc:
            body = exc.body
            try:
                error = json.loads(body).get("error")
            except json.JSONDecodeError:
                raise RuntimeError(body) from exc

            if error in {"authorization_pending", "slow_down"}:
                if error == "slow_down":
                    interval += 5
                continue
            raise RuntimeError(body) from exc

    raise RuntimeError("Device code authentication timed out")


class AuthCallbackHandler(BaseHTTPRequestHandler):
    server_version = "GraphAuth/1.0"
    auth_code: str | None = None
    auth_error: str | None = None

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        error = params.get("error", [None])[0]

        self.__class__.auth_code = code
        self.__class__.auth_error = error

        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        if code:
            self.wfile.write(
                b"<html><body><h2>Authentication complete.</h2><p>You can close this tab.</p></body></html>"
            )
        else:
            self.wfile.write(
                b"<html><body><h2>Authentication failed.</h2><p>You can close this tab and return to Codex.</p></body></html>"
            )

    def log_message(self, format: str, *args: object) -> None:
        return


def get_auth_code_token(tenant_id: str, client_id: str, client_secret: str | None = None) -> str:
    refresh_token = get_cached_refresh_token()

    if refresh_token:
        try:
            token = http_post_form(
                token_endpoint(tenant_id),
                {
                    "client_id": client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "scope": DEVICE_SCOPES,
                    **({"client_secret": client_secret} if client_secret else {}),
                },
            )
            if "refresh_token" in token:
                set_refresh_token(token["refresh_token"])
            return token["access_token"]
        except HttpRequestError as exc:
            print(
                f"WARNING: cached Microsoft Graph refresh token was rejected: {exc.status}",
                file=sys.stderr,
            )
            pass

    state = secrets.token_urlsafe(24)
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": LOCAL_REDIRECT_URI,
            "response_mode": "query",
            "scope": DEVICE_SCOPES,
            "state": state,
        }
    )
    auth_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize?{query}"

    AuthCallbackHandler.auth_code = None
    AuthCallbackHandler.auth_error = None

    httpd = HTTPServer(("127.0.0.1", LOCAL_REDIRECT_PORT), AuthCallbackHandler)
    httpd.timeout = 1

    print("Open this URL in a browser and complete sign-in:", file=sys.stderr)
    print(auth_url, file=sys.stderr)
    try:
        subprocess.run(["open", auth_url], check=False, capture_output=True, text=True)
    except Exception:
        pass

    deadline = time.time() + 300
    while time.time() < deadline:
        httpd.handle_request()
        if AuthCallbackHandler.auth_error:
            raise RuntimeError(f"Authorization failed: {AuthCallbackHandler.auth_error}")
        if AuthCallbackHandler.auth_code:
            break

    httpd.server_close()

    if not AuthCallbackHandler.auth_code:
        raise RuntimeError("Authorization timed out waiting for localhost callback")

    token = http_post_form(
        token_endpoint(tenant_id),
        {
            "client_id": client_id,
            "grant_type": "authorization_code",
            "code": AuthCallbackHandler.auth_code,
            "redirect_uri": LOCAL_REDIRECT_URI,
            "scope": DEVICE_SCOPES,
            **({"client_secret": client_secret} if client_secret else {}),
        },
    )

    if "refresh_token" in token:
        set_refresh_token(token["refresh_token"])
    return token["access_token"]


def get_client_credentials_token(tenant_id: str, client_id: str, client_secret: str) -> str:
    token = http_post_form(
        token_endpoint(tenant_id),
        {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": TOKEN_SCOPE_CLIENT_CREDENTIALS,
        },
    )
    return token["access_token"]


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
