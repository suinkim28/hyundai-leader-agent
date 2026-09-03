#!/usr/bin/env python3
"""Graph 스크립트 공통 부분 — 토큰 획득과 GET 호출.

새 스크립트를 쓸 때 인증 코드를 다시 짜지 않도록 한 곳에 모은다.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_teams_message import (            # noqa: E402
    ENV_CLIENT_ID, ENV_CLIENT_SECRET, ENV_TENANT_ID,
    GRAPH_BASE, HttpRequestError,
    KEYCHAIN_CLIENT_ID, KEYCHAIN_CLIENT_SECRET, KEYCHAIN_TENANT_ID,
    get_auth_code_token, get_client_credentials_token, get_device_code_token,
    get_secret, load_dotenv,
)

FLOWS = ("auth_code", "device", "client_credentials")


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
