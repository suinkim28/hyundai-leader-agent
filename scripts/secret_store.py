#!/usr/bin/env python3
"""자격증명을 OS 의 보안 저장소에서 읽고 쓴다.

값은 이 워크스페이스의 어느 파일에도 저장하지 않는다. 평문 파일은 실수로
커밋되거나 백업으로 새어 나가므로, OS 가 제공하는 저장소에만 둔다.

읽는 순서
--------
1. 환경변수 (실제 값이 들어 있을 때만)
2. OS 보안 저장소
     macOS   : 키체인
     Windows : DPAPI 로 암호화한 %LOCALAPPDATA%\\hmg-agent\\secrets

환경변수에 자리표시자가 들어 있으면 없는 것으로 본다.

**평문 파일에는 쓰지 않는다.** 위 둘이 아닌 환경에서는 저장하지 않고
실패한다. 그때는 값을 환경변수로 준다.

저장은 에이전트에게 "Graph 설정해줘" 라고 말하면 된다.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

# 템플릿에 남은 자리표시자는 값이 없는 것으로 본다.
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


def _env_name_for(service: str) -> str:
    """저장소 이름에 대응하는 환경변수 이름. 이 파일 아래의 대응표에서 찾는다.

    이름 규칙이 서로 달라(`hmg-agent-graph-client-id` ->
    `MICROSOFT_GRAPH_CLIENT_ID`) 문자열 변환으로 만들 수 없다.
    """
    for value in globals().values():
        if (isinstance(value, tuple) and len(value) == 2
                and value[1] == service and isinstance(value[0], str)):
            return value[0]
    return ""


def keychain_get(service: str) -> str:
    """저장소에서 값 하나를 읽는다. 없으면 "".

    macOS  : 로그인 키체인 (generic password)
    Windows: DPAPI 로 사용자 계정에 묶어 암호화한 파일
    그 외  : 없음. 환경변수로만 받는다 (`get_secret` 이 먼저 본다)
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

    # 여기까지 왔으면 macOS 도 Windows 도 아니다. 평문 파일에 쓰지 않는다.
    # 조용히 어딘가에 저장한 척하는 것이 가장 나쁘다: 본부장은 저장됐다고
    # 믿고, 값은 암호화 없이 디스크에 남는다.
    env_name = _env_name_for(service)
    hint = f"export {env_name}=..." if env_name else "해당 환경변수를 설정"
    raise RuntimeError(
        f"이 플랫폼({sys.platform})에는 쓸 수 있는 보안 저장소가 없습니다.\n"
        f"  평문 파일에는 저장하지 않습니다.\n"
        f"  값을 환경변수로 주십시오: {hint}"
    )


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
            f"자격증명이 없습니다: {keychain_service}\n"
            f"  에이전트에게 '설정해줘' 라고 말씀하시면 저장합니다.\n"
            f"  상태 확인: bin/graph setup --check"
        )
    return ""


# Service names used across this workspace.
OPENAI_API_KEY = ("OPENAI_API_KEY", "hmg-agent-openai-api-key")
ATLASSIAN_SITE = ("ATLASSIAN_SITE", "hmg-agent-atlassian-site")
ATLASSIAN_EMAIL = ("ATLASSIAN_EMAIL", "hmg-agent-atlassian-email")
ATLASSIAN_API_TOKEN = ("ATLASSIAN_API_TOKEN", "hmg-agent-atlassian-api-token")
MLAPI_KIMI_KEY = ("MLAPI_KIMI_KEY", "hmg-agent-mlapi-key")

# Microsoft Graph: 2026-09-03 ICT 승인 앱 HMG-LeaderAXSession-PILOT
GRAPH_CLIENT_ID = ("MICROSOFT_GRAPH_CLIENT_ID", "hmg-agent-graph-client-id")
GRAPH_TENANT_ID = ("MICROSOFT_GRAPH_TENANT_ID", "hmg-agent-graph-tenant-id")
GRAPH_CLIENT_SECRET = ("MICROSOFT_GRAPH_CLIENT_SECRET", "hmg-agent-graph-client-secret")
GRAPH_REFRESH_TOKEN = ("MICROSOFT_GRAPH_REFRESH_TOKEN", "hmg-agent-graph-refresh-token")
