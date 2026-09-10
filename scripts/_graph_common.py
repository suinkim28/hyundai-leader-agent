#!/usr/bin/env python3
"""Graph 스크립트 공통 부분: 인증, 토큰, 시크릿, HTTP 호출.

새 스크립트를 쓸 때 인증 코드를 다시 짜지 않도록 한 곳에 모은다. **이 파일이
SSOT다.** 다른 스크립트는 여기서 import 하고, 이 파일은 다른 스크립트를
import 하지 않는다 (순환 참조 방지). `fetch_teams_message.py` 는 Teams 조회
로직만 가지며, 인증 관련 이름은 여기서 가져다 쓴다.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
import webbrowser

sys.path.insert(0, str(Path(__file__).resolve().parent))

# --------------------------------------------------------------------------
# 사내망 SSL 인스펙션 프록시(HMG Secure ROOT CA) 대응 (2026-09-09, TODO.txt 참고).
#
# Python 은 certifi 번들만 신뢰하므로, 프록시가 Graph HTTPS 를 가로채 자체 CA
# 인증서를 내밀면 CERTIFICATE_VERIFY_FAILED 로 거부한다. truststore 는 OS
# 인증서 저장소(Windows/macOS/Linux)를 그대로 쓰도록 ssl 모듈을 바꿔치기해
# 실제 CA(프록시든 공인 CA든)를 검증한다 — 검증을 끄는 것이 아니라 신뢰
# 소스만 바꾸는 것이라 프록시가 없는 환경에서도 그대로 동작한다.
#
# 모든 Graph 스크립트가 이 파일을 import 하므로 여기 한 곳에서만 걸면
# 전체에 적용된다. 미설치 PC 는 오늘과 동일하게 동작한다 (설치돼 있어야만
# 프록시 환경의 오류가 사라진다).
try:
    import truststore
    truststore.inject_into_ssl()
except Exception:
    pass

# --------------------------------------------------------------------------
# Graph 엔드포인트, 스코프
# --------------------------------------------------------------------------

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


DEVICE_SCOPES = _load_scopes()

ENV_CLIENT_ID = "MICROSOFT_GRAPH_CLIENT_ID"
ENV_CLIENT_SECRET = "MICROSOFT_GRAPH_CLIENT_SECRET"
ENV_TENANT_ID = "MICROSOFT_GRAPH_TENANT_ID"
ENV_REFRESH_TOKEN = "MICROSOFT_GRAPH_REFRESH_TOKEN"
KEYCHAIN_CLIENT_ID = "hmg-agent-graph-client-id"
KEYCHAIN_CLIENT_SECRET = "hmg-agent-graph-client-secret"
KEYCHAIN_TENANT_ID = "hmg-agent-graph-tenant-id"
KEYCHAIN_REFRESH_TOKEN = "hmg-agent-graph-refresh-token"

# 로그인 콜백 주소.
#
# **Entra 앱 등록의 리디렉션 URI 와 한 글자도 다르면 안 된다.**
# 다르면 로그인 화면에서 AADSTS50011 이 뜬다.
#
# 기본값은 현대자동차 ICT 가 등록한 값이다. 테넌트가 다른 앱을 쓸 때는
# 환경변수로 덮어쓴다.
#
#     export MICROSOFT_GRAPH_REDIRECT_URI="http://localhost:8765/callback"
#
# 지금 무엇이 쓰이는지 보려면:  python3 bin/graph login --check
LOCAL_REDIRECT_URI = os.environ.get(
    "MICROSOFT_GRAPH_REDIRECT_URI", "http://localhost:3000/auth/callback"
).strip()
LOCAL_REDIRECT_PORT = urllib.parse.urlparse(LOCAL_REDIRECT_URI).port or 3000
DOTENV_PATHS: list[str] = []

FLOWS = ("auth_code", "device", "client_credentials")


class HttpRequestError(RuntimeError):
    def __init__(self, method: str, url: str, status: int, body: str) -> None:
        self.method = method
        self.url = url
        self.status = status
        self.body = body
        super().__init__(f"{method} {url} failed: {status} {body}")


# --------------------------------------------------------------------------
# .env, 시크릿 저장소
# --------------------------------------------------------------------------

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

    실제 구현은 `secret_store` 에 있다. macOS 키체인과 Windows DPAPI 를
    한곳에서 관리하기 위해 위임한다.
    """
    try:
        from secret_store import keychain_get as _get
        value = _get(service)
        if value:
            return value
    except Exception:
        pass

    # `secret_store` 가 아는 곳에 없으면 없는 것으로 본다. 다른 경로를
    # 뒤지지 않는다: 같은 PC 의 다른 워크스페이스가 쓰던 토큰을 주워 오면
    # 어느 계정으로 도는지 알 수 없게 된다.
    return ""


def keychain_set(service: str, value: str) -> None:
    """저장소에 값 하나를 쓴다.

    실제 구현은 `secret_store` 에 위임한다: macOS 키체인, Windows DPAPI.
    읽기(`keychain_get`)와 쓰기가 같은 곳을 보도록 한곳에서 관리한다.
    **평문 파일에 쓰지 않는다.** 암호화 없이 남은 refresh token 은 그 PC 를
    쓰는 누구나 본부장 계정으로 Graph 를 호출하게 만든다.
    """
    from secret_store import keychain_set as _set
    _set(service, value)


def get_secret(env_name: str, keychain_service: str, *, required: bool = True) -> str:
    """환경변수 먼저, 그다음 자격증명 저장소.

    없을 때 빈 문자열을 돌려주지 않는다. 빈 값으로 진행하면 인자가 빠진
    로그인 URL 이 열리고 원인을 알기 어려운 오류가 난다. 조용히 넘어가는
    대신 무엇이 없는지 말하고 멈춘다.
    """
    value = os.environ.get(env_name, "").strip()
    if value and not is_placeholder_secret(value):
        return value

    value = keychain_get(keychain_service)
    if value and not is_placeholder_secret(value):
        return value

    if required:
        raise SystemExit(
            f"자격증명이 없습니다: {keychain_service}\n"
            f"  에이전트에게 'Graph 설정해줘' 라고 말씀하십시오.\n"
            f"  상태 확인: python3 bin/graph setup --check"
        )
    return ""


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


# --------------------------------------------------------------------------
# 저수준 HTTP
# --------------------------------------------------------------------------

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


# --------------------------------------------------------------------------
# 토큰 발급: auth_code (PKCE), device code, client_credentials
# --------------------------------------------------------------------------

def token_endpoint(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"


def device_code_endpoint(tenant_id: str) -> str:
    return f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/devicecode"


def get_device_code_token(tenant_id: str, client_id: str, client_secret: str | None = None) -> str:
    refresh_token = get_cached_refresh_token()

    if refresh_token:
        try:
            # 이 앱은 http://localhost 리디렉션을 쓰는 퍼블릭 클라이언트로
            # 등록돼 있다 (Entra 는 localhost 를 "모바일 및 데스크톱 앱"
            # 플랫폼에서만 허용한다). 퍼블릭 클라이언트에 client_secret 을
            # 보내면 AADSTS700025 로 거부된다.
            token = http_post_form(
                token_endpoint(tenant_id),
                {
                    "client_id": client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "scope": DEVICE_SCOPES,
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
    # 빈 값으로 URL 을 만들면 login.microsoftonline.com//oauth2/...&client_id=
    # 같은 주소가 열리고, 사용자는 무엇이 잘못됐는지 알 수 없다.
    for label, value in (("Tenant ID", tenant_id), ("Client ID", client_id)):
        if not (value or "").strip():
            raise SystemExit(
                f"{label} 가 비어 있어 로그인 URL 을 만들 수 없습니다.\n"
                f"  상태 확인: python3 bin/graph setup --check"
            )

    refresh_token = get_cached_refresh_token()

    if refresh_token:
        try:
            # 퍼블릭 클라이언트(아래 참고)에는 client_secret 을 보내지 않는다.
            token = http_post_form(
                token_endpoint(tenant_id),
                {
                    "client_id": client_id,
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "scope": DEVICE_SCOPES,
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

    # PKCE (RFC 7636). Entra 는 http://localhost 리디렉션을 "모바일 및
    # 데스크톱 앱" 플랫폼(퍼블릭 클라이언트)에서만 허용하므로, 이 앱은
    # client_secret 이 아니라 code_verifier 로 인증 코드를 증명해야 한다.
    # client_secret 을 함께 보내면 AADSTS700025 로 거부된다.
    code_verifier = secrets.token_urlsafe(64)
    code_challenge = base64.urlsafe_b64encode(
        hashlib.sha256(code_verifier.encode("ascii")).digest()
    ).rstrip(b"=").decode("ascii")

    state = secrets.token_urlsafe(24)
    query = urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "redirect_uri": LOCAL_REDIRECT_URI,
            "response_mode": "query",
            "scope": DEVICE_SCOPES,
            "state": state,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
    )
    auth_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/authorize?{query}"

    AuthCallbackHandler.auth_code = None
    AuthCallbackHandler.auth_error = None

    httpd = HTTPServer(("127.0.0.1", LOCAL_REDIRECT_PORT), AuthCallbackHandler)
    httpd.timeout = 1

    print("Open this URL in a browser and complete sign-in:", file=sys.stderr)
    print(auth_url, file=sys.stderr)
    opened = False
    try:
        opened = webbrowser.open(auth_url)
    except Exception:
        opened = False
    if not opened:
        # macOS 참고 경로. webbrowser.open() 이 이미 대부분의 플랫폼(Windows
        # 포함)을 처리하므로 이건 실패했을 때의 보강일 뿐이다.
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
            "code_verifier": code_verifier,
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


# --------------------------------------------------------------------------
# 상위 레벨 헬퍼: 대부분의 스크립트가 실제로 쓰는 진입점
# --------------------------------------------------------------------------

def token_for(flow: str = "auth_code") -> str:
    load_dotenv()
    tenant_id = get_secret(ENV_TENANT_ID, KEYCHAIN_TENANT_ID)
    client_id = get_secret(ENV_CLIENT_ID, KEYCHAIN_CLIENT_ID)
    client_secret = get_secret(ENV_CLIENT_SECRET, KEYCHAIN_CLIENT_SECRET)
    if flow == "client_credentials":
        return get_client_credentials_token(tenant_id, client_id, client_secret)
    if flow == "device":
        return get_device_code_token(tenant_id, client_id, client_secret)
    return get_auth_code_token(tenant_id, client_id, client_secret)


def graph_get(token: str, path: str, params: dict | None = None) -> dict:
    """`path` 는 /me/drive/root 처럼 GRAPH_BASE 이후 부분."""
    url = f"{GRAPH_BASE}{path}"
    if params:
        url += "?" + urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
    })
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HttpRequestError("GET", url, exc.code, body) from exc


def graph_post(token: str, path: str, body: dict) -> dict:
    """`path` 는 /search/query 처럼 GRAPH_BASE 이후 부분."""
    url = f"{GRAPH_BASE}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body_text = exc.read().decode("utf-8", errors="ignore")
        raise HttpRequestError("POST", url, exc.code, body_text) from exc


def graph_download(token: str, path: str, dest: Path) -> int:
    url = f"{GRAPH_BASE}{path}"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    try:
        with urllib.request.urlopen(req) as resp:
            data = resp.read()
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HttpRequestError("GET", url, exc.code, body) from exc
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    return len(data)
