#!/usr/bin/env python3
"""연결 진단: 무엇이 되고 무엇이 안 되는지 한 화면으로.

왜 이것이 있는가
----------------
세션 당일에 "메일이 안 읽힌다"를 발견하면 이미 늦다. 승인 하나가 막히면
워크플로 여러 개가 통째로 사라지는데, 그 사실을 세션 시작 후에 알게 되면
본부장 앞에서 복구할 방법이 없다.

그래서 이 스크립트는 **되는 것을 확인하는 도구가 아니라, 안 되는 것을
D-3에 찾아내는 도구**다. 각 항목에 "막히면 무엇을 잃는가"와 "대신 무엇을
할 수 있는가"를 함께 출력한다.

사용
----
    python3 scripts/check_connections.py            # 전체 진단
    python3 scripts/check_connections.py --quiet    # 실패한 것만
    python3 scripts/check_connections.py --json     # 기계 판독용

의존성 없음. 표준 라이브러리만 쓴다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import unicodedata
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

OK, WARN, FAIL = "OK", "주의", "실패"
SYMBOL = {OK: "OK  ", WARN: "주의 ", FAIL: "실패 "}

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class Check:
    def __init__(self, name, status, detail, lost="", fallback=""):
        self.name = name
        self.status = status
        self.detail = detail
        self.lost = lost          # 막히면 잃는 기능
        self.fallback = fallback  # 대체 경로

    def as_dict(self):
        return {
            "항목": self.name, "상태": self.status, "상세": self.detail,
            "잃는 기능": self.lost, "대체 경로": self.fallback,
        }


# --------------------------------------------------------------------------
# 개별 점검
# --------------------------------------------------------------------------

def check_python():
    v = sys.version_info
    if v >= (3, 9):
        return Check("Python", OK, f"{v.major}.{v.minor}.{v.micro}")
    return Check(
        "Python", FAIL, f"{v.major}.{v.minor} (3.9 이상이 필요합니다)",
        lost="모든 스크립트",
        fallback="python.org 에서 3.11 이상 설치",
    )


def check_claude_cli():
    path = shutil.which("claude")
    if not path:
        return Check(
            "Claude Code CLI", WARN, "PATH 에 없음",
            lost="무인 루틴 실행 (06:00 / 08:00 / 17:00)",
            fallback="에디터 안에서 수동 실행은 가능. 자동 실행만 불가",
        )
    try:
        out = subprocess.run([path, "--version"], capture_output=True,
                             text=True, timeout=20)
        return Check("Claude Code CLI", OK, out.stdout.strip() or path)
    except (OSError, subprocess.SubprocessError):
        return Check("Claude Code CLI", WARN, f"{path}, 버전 확인 실패")


def _secret(env_name, service):
    try:
        from secret_store import get_secret
    except ImportError:
        return ""
    try:
        return get_secret(env_name, service, required=False)
    except SystemExit:
        return ""


def check_graph_credentials():
    have = {
        "client id": _secret("MICROSOFT_GRAPH_CLIENT_ID", "hmg-agent-graph-client-id"),
        "tenant id": _secret("MICROSOFT_GRAPH_TENANT_ID", "hmg-agent-graph-tenant-id"),
    }
    missing = [k for k, v in have.items() if not v]
    if missing:
        return Check(
            "Graph 자격증명", FAIL, f"없음: {', '.join(missing)}",
            lost="메일, 일정, Teams 조회 전부",
            fallback="본부장님께 'Graph 설정해줘' 라고 말씀하시면 에이전트가 진행합니다 (.claude/commands/setup.md)",
        ), None
    token = _secret("MICROSOFT_GRAPH_REFRESH_TOKEN", "hmg-agent-graph-refresh-token")
    if not token:
        return Check(
            "Graph 자격증명", WARN, "앱 등록은 되어 있으나 로그인 이력 없음",
            lost="메일, 일정 조회 (첫 로그인 전까지)",
            fallback="python3 scripts/fetch_outlook_mail.py --top 1 을 한 번 실행해 로그인",
        ), None
    return Check("Graph 자격증명", OK, "client/tenant/refresh token 확인"), True


def _graph_token(client_id, tenant_id, client_secret):
    """저장된 refresh token 으로 access token 을 조용히 받아 본다.

    브라우저를 열지 않는다. `get_auth_code_token()` 을 인자 없이 부르면
    실패하고 (그 함수는 tenant_id, client_id 를 요구한다), 실패하면 여기서
    바로 대화형 로그인 화면을 띄워 버린다 — 진단 스크립트가 할 일이 아니다.
    그래서 refresh token 교환만 직접 재현한다.
    """
    try:
        sys.path.insert(0, str(ROOT / "scripts"))
        import _graph_common as gc
    except Exception:
        return None
    refresh_token = gc.get_cached_refresh_token()
    if not refresh_token:
        return None
    try:
        # 이 앱은 http://localhost 리디렉션을 쓰는 퍼블릭 클라이언트라
        # client_secret 을 보내면 AADSTS700025 로 거부된다
        # (scripts/_graph_common.py 의 같은 코멘트 참고).
        token = gc.http_post_form(
            gc.token_endpoint(tenant_id),
            {
                "client_id": client_id,
                "grant_type": "refresh_token",
                "refresh_token": refresh_token,
                "scope": gc.DEVICE_SCOPES,
            },
        )
        return token.get("access_token") or None
    except Exception:
        return None


def _graph_get(path, token, timeout=20):
    req = urllib.request.Request(f"{GRAPH_BASE}{path}", method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def check_graph_endpoints(token):
    targets = [
        ("Outlook 메일", "/me/messages?$top=1",
         "아침 브리핑, 메일 트리아지, 회신 추적",
         "본부장이 내보낸 .msg 파일을 attachments/raw/ 에 두면 읽습니다"),
        ("Outlook 캘린더", "/me/events?$top=1",
         "일정 브리핑, 회의 준비 자동 트리거",
         ".ics 내보내기 파일을 attachments/raw/ 에 두면 읽습니다"),
        ("Teams", "/me/chats?$top=1",
         "회의 전후 대화 맥락 파악",
         "본부장이 붙여넣은 대화 내용으로 대체"),
    ]
    results = []
    for name, path, lost, fallback in targets:
        if not token:
            results.append(Check(name, FAIL, "액세스 토큰 없음", lost, fallback))
            continue
        try:
            _graph_get(path, token)
            results.append(Check(name, OK, "조회 성공"))
        except urllib.error.HTTPError as exc:
            hint = "권한 미승인" if exc.code in (401, 403) else f"HTTP {exc.code}"
            results.append(Check(name, FAIL, hint, lost, fallback))
        except Exception as exc:
            if "CERTIFICATE_VERIFY_FAILED" in str(exc):
                results.append(Check(
                    name, FAIL, "SSL 인증서 검증 실패 (사내 프록시 가능성)",
                    lost,
                    "pip install truststore 실행 후 재시도 (TODO.txt 'CERTIFICATE_VERIFY_FAILED' 참고, Python 3.10+ 필요)",
                ))
            else:
                results.append(Check(name, FAIL, type(exc).__name__, lost, fallback))
    return results


def check_mcp():
    path = shutil.which("claude")
    if not path:
        return [Check(
            "Confluence / Jira MCP", WARN, "claude CLI 없음 (확인 불가)",
            lost="사내 지식 검색, 과제 추적",
            fallback="웹에서 복사한 내용을 knowledge_base/ 에 저장",
        )]
    try:
        out = subprocess.run([path, "mcp", "list"], capture_output=True,
                             text=True, timeout=60)
        text = (out.stdout or "") + (out.stderr or "")
    except (OSError, subprocess.SubprocessError):
        return [Check("Confluence / Jira MCP", WARN, "claude mcp list 실패")]

    lowered = text.lower()
    if "atlassian" not in lowered:
        return [Check(
            "Confluence / Jira MCP", FAIL, "atlassian 서버가 등록되지 않음",
            lost="사내 지식 검색, 과제 추적",
            fallback="CONNECTIONS.md §5 등록 절차",
        )]
    connected = "connected" in lowered or "✓" in text
    if connected:
        return [Check("Confluence / Jira MCP", OK, "atlassian 연결됨")]
    return [Check(
        "Confluence / Jira MCP", WARN, "등록됐으나 로그인 필요",
        lost="사내 지식 검색",
        fallback="claude mcp 로그인 후 재시도",
    )]


def check_stt():
    key = _secret("OPENAI_API_KEY", "hmg-agent-openai-api-key")
    if key:
        return Check("음성 전사 (STT)", OK, "API 키 확인")
    return Check(
        "음성 전사 (STT)", FAIL, "API 키 없음",
        lost="회의 녹음 → 전사 → 회의록 자동 생성",
        fallback="회의 중 구술 메모로 대체. 원문은 남지 않습니다",
    )


def check_web():
    try:
        req = urllib.request.Request(
            "https://www.google.com/generate_204",
            headers={"User-Agent": "Mozilla/5.0"},
        )
        urllib.request.urlopen(req, timeout=10)
        return Check("외부 웹", OK, "접근 가능")
    except Exception:
        return Check(
            "외부 웹", WARN, "접근 불가 또는 프록시 필요",
            lost="시장 동향 브리핑, 외부 법규, 경쟁사 조사",
            fallback="사내 뉴스 클리핑을 knowledge_base/ 에 축적",
        )


def check_workspace():
    required = ["PROFILE.md", "ORG.md", "SYSTEM.md", "ROUTINES.md",
                "briefings", "meetings/logs", "meetings/transcripts",
                "decisions", "drafts", "knowledge_base", "logs"]
    missing = [p for p in required if not (ROOT / p).exists()]
    if missing:
        return Check(
            "워크스페이스 구조", FAIL, f"없음: {', '.join(missing)}",
            lost="루틴 산출물 저장 위치",
            fallback="스켈레톤을 다시 복사하십시오",
        )
    return Check("워크스페이스 구조", OK, f"{len(required)}개 항목 확인")


def check_personalization():
    profile = ROOT / "PROFILE.md"
    if not profile.exists():
        return Check("개인화 상태", FAIL, "PROFILE.md 없음",
                     lost="모든 개인화", fallback="스켈레톤 재복사")
    text = profile.read_text(encoding="utf-8")
    state = "미완료"
    for line in text.splitlines():
        if line.strip().lstrip("- ").startswith(("상태:", "상태：")):
            state = line.split(":", 1)[-1].split("：")[-1].strip()
            break
    unknown = text.count("[미확보]")
    if state == "미완료":
        return Check(
            "개인화 상태", WARN, f"미완료, 미확보 항목 {unknown}개",
            lost="맞춤 답변 전부. 지금은 일반론만 가능합니다",
            fallback="세션에서 /bootstrap 실행 (필수 10문항, 20분)",
        )
    return Check("개인화 상태", OK, f"{state}, 미확보 항목 {unknown}개")


def check_send_gate():
    """발송 확인 게이트는 2026-09-10 에 제거됐다. 그 사실을 화면에 남긴다.

    없는 안전장치를 있다고 믿는 상태가 없는 것보다 나쁘다. 진단이
    조용하면 본부장은 여전히 확인 창이 뜬다고 생각한다.
    """
    return Check(
        "발송 확인 게이트", WARN, "없음 (2026-09-10 제거)",
        lost="메일, Teams 발송과 캘린더 변경이 확인 없이 실행됩니다",
        fallback="막아야 하면 HARNESS.md 6절 축소 운영, 또는 .claude/graph_scopes.txt 의 Send 권한 3줄을 주석 처리",
    )


def run_all():
    checks = [check_python(), check_claude_cli(), check_workspace()]

    cred, have_token = check_graph_credentials()
    checks.append(cred)
    if have_token:
        client_id = _secret("MICROSOFT_GRAPH_CLIENT_ID", "hmg-agent-graph-client-id")
        tenant_id = _secret("MICROSOFT_GRAPH_TENANT_ID", "hmg-agent-graph-tenant-id")
        client_secret = _secret("MICROSOFT_GRAPH_CLIENT_SECRET", "hmg-agent-graph-client-secret")
        token = _graph_token(client_id, tenant_id, client_secret)
    else:
        token = None
    checks.extend(check_graph_endpoints(token))

    checks.extend(check_mcp())
    checks.append(check_stt())
    checks.append(check_web())
    checks.append(check_personalization())
    checks.append(check_send_gate())
    return checks


def _width(text):
    """한글은 터미널에서 두 칸을 차지한다."""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1
               for ch in text)


def _pad(text, target):
    return text + " " * max(0, target - _width(text))


def render(checks, quiet=False):
    lines = ["", "연결 진단", "=" * 68]
    shown = [c for c in checks if not quiet or c.status != OK]
    width = max((_width(c.name) for c in shown), default=10)
    indent = " " * (6 + width + 2)
    for c in shown:
        lines.append(f"{SYMBOL[c.status]} {_pad(c.name, width)}  {c.detail}")
        if c.status != OK and c.lost:
            lines.append(f"{indent}└ 잃는 기능: {c.lost}")
        if c.status != OK and c.fallback:
            lines.append(f"{indent}└ 대체 경로: {c.fallback}")
    lines.append("=" * 68)

    n_fail = sum(1 for c in checks if c.status == FAIL)
    n_warn = sum(1 for c in checks if c.status == WARN)
    n_ok = sum(1 for c in checks if c.status == OK)
    lines.append(f"정상 {n_ok}, 주의 {n_warn}, 실패 {n_fail}")

    if n_fail:
        lines.append("")
        lines.append("실패 항목이 있습니다. 세션 당일이 아니라 지금 에스컬레이션하십시오.")
        lines.append("대체 경로만으로도 회의록, 회고, 의사결정 이력, 과제 추적은 동작합니다.")
    lines.append("")
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="본부장 에이전트 연결 진단")
    parser.add_argument("--quiet", action="store_true", help="실패, 주의만 출력")
    parser.add_argument("--json", action="store_true", help="JSON 으로 출력")
    args = parser.parse_args()

    checks = run_all()

    if args.json:
        print(json.dumps([c.as_dict() for c in checks],
                         ensure_ascii=False, indent=2))
    else:
        print(render(checks, quiet=args.quiet))

    return 1 if any(c.status == FAIL for c in checks) else 0


if __name__ == "__main__":
    sys.exit(main())
