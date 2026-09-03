#!/usr/bin/env python3
"""Resolve secrets from the environment, then fall back to the macOS Keychain.

Why this exists
---------------
2026-08-27: an agent overwrote `Secretary/.env` with `.env.example`, wiping
four live secrets. `.env` is gitignored and there was no snapshot, so the
only reason recovery was possible is that some values also lived in the
Keychain.

`fetch_teams_message.py` already had this pattern for the Microsoft Graph
credentials. This module generalises it so any script can use it without
importing the Graph module (and its heavy dependencies).

Precedence
----------
1. the environment variable, when it holds a real value
2. the macOS Keychain entry
3. `~/.config/secretary/secrets.json`, keyed by service name (Linux/CI)

A placeholder in the environment is treated as absent, so a clobbered
`.env` degrades to the Keychain instead of failing.

Register a secret with:
    security add-generic-password -U -a "$USER" -s <service> -w
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

FALLBACK_FILE = Path.home() / ".config" / "hmg-agent" / "secrets.json"

# `.env.example` uses `your_openai_api_key`; older code only caught `your-`.
_PLACEHOLDER_PREFIXES = ("your", "<", "$", "changeme", "change-me",
                         "placeholder", "dummy", "xxx", "todo")


def is_placeholder(value: str | None) -> bool:
    """True when a value is empty or an obvious template stand-in."""
    if not value:
        return True
    normalized = value.strip().strip("'\"").lower()
    if not normalized:
        return True
    return normalized.startswith(_PLACEHOLDER_PREFIXES)


def _win_store_path(service: str) -> Path:
    """Windows 저장 위치. DPAPI 로 암호화된 값을 파일 하나에 담는다."""
    root = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "hmg-agent" / "secrets"
    return root / f"{service}.dpapi"


def _powershell(script: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        check=False, capture_output=True, text=True,
    )


def keychain_get(service: str) -> str:
    """저장소에서 값 하나를 읽는다. 없으면 "".

    macOS  : 로그인 키체인 (generic password)
    Windows: DPAPI 로 사용자 계정에 묶어 암호화한 파일
    그 외  : ~/.config/hmg-agent/secrets.json
    """
    if sys.platform == "darwin":
        result = subprocess.run(
            ["security", "find-generic-password",
             "-a", os.environ.get("USER", ""), "-s", service, "-w"],
            check=False, capture_output=True, text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()

    elif os.name == "nt":
        path = _win_store_path(service)
        if path.exists():
            proc = _powershell(
                f"$e = Get-Content -Raw -LiteralPath '{path}'; "
                "$s = ConvertTo-SecureString -String $e; "
                "[Runtime.InteropServices.Marshal]::PtrToStringAuto("
                "[Runtime.InteropServices.Marshal]::SecureStringToBSTR($s))"
            )
            if proc.returncode == 0:
                return proc.stdout.strip()

    if FALLBACK_FILE.exists():
        try:
            data = json.loads(FALLBACK_FILE.read_text(encoding="utf-8"))
            value = data.get(service, "")
            if isinstance(value, str):
                return value.strip()
        except (json.JSONDecodeError, OSError):
            pass

    return ""


def keychain_set(service: str, value: str) -> str:
    """값 하나를 저장한다. 저장된 위치 설명을 돌려준다.

    값은 인자로만 오간다. 이 함수는 값을 로그에 남기지 않는다.
    """
    if not value or not value.strip():
        raise ValueError("빈 값은 저장하지 않는다")
    value = value.strip()

    if sys.platform == "darwin":
        result = subprocess.run(
            ["security", "add-generic-password", "-U",
             "-a", os.environ.get("USER", ""), "-s", service, "-w", value],
            check=False, capture_output=True, text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"macOS 키체인 저장 실패: {result.stderr.strip()}")
        return "macOS 로그인 키체인"

    if os.name == "nt":
        path = _win_store_path(service)
        path.parent.mkdir(parents=True, exist_ok=True)
        escaped = value.replace("'", "''")
        proc = _powershell(
            f"$v = '{escaped}'; "
            "$s = ConvertTo-SecureString -String $v -AsPlainText -Force; "
            f"ConvertFrom-SecureString -SecureString $s | "
            f"Set-Content -NoNewline -LiteralPath '{path}'"
        )
        if proc.returncode != 0:
            raise RuntimeError(f"Windows DPAPI 저장 실패: {proc.stderr.strip()}")
        return f"Windows 자격 저장소 (DPAPI, {path.parent})"

    FALLBACK_FILE.parent.mkdir(parents=True, exist_ok=True)
    data = {}
    if FALLBACK_FILE.exists():
        try:
            data = json.loads(FALLBACK_FILE.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            data = {}
    data[service] = value
    FALLBACK_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    os.chmod(FALLBACK_FILE, 0o600)
    return f"파일 ({FALLBACK_FILE})"


def mask(value: str) -> str:
    """로그와 화면에 쓸 마스킹 형태. 앞 4자 + 뒤 4자만."""
    v = (value or "").strip()
    if len(v) <= 10:
        return "*" * len(v)
    return f"{v[:4]}{'*' * 6}{v[-4:]}"


def get_secret(env_name: str, keychain_service: str, *, required: bool = True) -> str:
    """Environment first, Keychain second.

    Raises SystemExit with a fix-it message when required and unresolved.
    """
    value = os.environ.get(env_name, "")
    if not is_placeholder(value):
        return value.strip()

    value = keychain_get(keychain_service)
    if not is_placeholder(value):
        return value.strip()

    if required:
        raise SystemExit(
            f"{env_name} is not configured.\n"
            f"  .env 에 넣거나, Keychain 에 등록하세요:\n"
            f'  security add-generic-password -U -a "$USER" '
            f'-s {keychain_service} -w'
        )
    return ""


# Service names used across this workspace.
OPENAI_API_KEY = ("OPENAI_API_KEY", "hmg-agent-openai-api-key")
ATLASSIAN_SITE = ("ATLASSIAN_SITE", "hmg-agent-atlassian-site")
ATLASSIAN_EMAIL = ("ATLASSIAN_EMAIL", "hmg-agent-atlassian-email")
ATLASSIAN_API_TOKEN = ("ATLASSIAN_API_TOKEN", "hmg-agent-atlassian-api-token")
MLAPI_KIMI_KEY = ("MLAPI_KIMI_KEY", "hmg-agent-mlapi-key")

# Microsoft Graph — 2026-09-03 ICT 승인 앱 HMG-LeaderAXSession-PILOT
GRAPH_CLIENT_ID = ("MICROSOFT_GRAPH_CLIENT_ID", "hmg-agent-graph-client-id")
GRAPH_TENANT_ID = ("MICROSOFT_GRAPH_TENANT_ID", "hmg-agent-graph-tenant-id")
GRAPH_CLIENT_SECRET = ("MICROSOFT_GRAPH_CLIENT_SECRET", "hmg-agent-graph-client-secret")
GRAPH_REFRESH_TOKEN = ("MICROSOFT_GRAPH_REFRESH_TOKEN", "hmg-agent-graph-refresh-token")
