#!/usr/bin/env python3
"""Microsoft Graph 단일 진입점.

왜 이것이 있는가
----------------
스크립트가 여러 개로 흩어져 있으면 에이전트가 무엇을 쓸 수 있는지 알기 어렵다.
`bin/graph --help` 하나로 전체 능력을 보여주고, 세부 옵션은 각 하위 명령의
`--help` 로 넘긴다. 실제 동작은 `scripts/` 의 기존 스크립트가 그대로 한다.

MCP 서버가 아니라 스크립트인 이유
---------------------------------
1. 루틴 8종은 고정이다. 매일 같은 호출을 한다. 도구 탐색이 필요 없다
2. 명령줄 전문이 그대로 화면에 남는다. 무엇이 나갔는지 나중에 확인할 수 있다.
   MCP 는 도구명과 JSON 만 본다
3. 본부장 PC 에서 움직이는 부품이 적을수록 좋다. MCP 서버가 안 뜨면 Graph 접근이
   통째로 조용히 사라지지만, 스크립트는 에러가 화면에 뜬다

나중에 이 진입점을 감싸는 로컬 MCP 를 얹을 수 있다. 그때도 SSOT 는 여기다.

읽기 / 쓰기
-----------
아래 `쓰기` 로 표시된 명령은 되돌릴 수 없다. 이를 막는 훅은 없다.
쓰기 명령은 모두 `--dry-run` 을 지원한다. 확인을 받기 전에 반드시 먼저
`--dry-run` 으로 무엇이 나갈지 그대로 보여줄 것.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

# 하위 명령 → (스크립트, 한 줄 설명, 쓰기 여부)
COMMANDS: dict[str, tuple[str, str, bool]] = {
    "mail":        ("fetch_outlook_mail.py",        "메일 조회, 검색  --unread --top --since --search --json", False),
    "calendar":    ("fetch_outlook_calendar.py",    "일정 조회  --days --start --end --json", False),
    "teams":       ("fetch_teams_message.py",       "Teams 메시지 조회  <url>", False),
    "teams-search":("search_teams_messages.py",     "Teams 채팅, 채널 메시지 키워드 검색  <검색어>", False),
    "files":       ("fetch_graph_files.py",         "OneDrive, SharePoint 파일 조회, 검색, 다운로드", False),
    "notes":       ("fetch_graph_notes.py",         "OneNote 노트북, 섹션, 페이지 조회", False),
    "market":      ("fetch_market_intel.py",        "시장 동향 수집 (Graph 아님. R1 에서 사용)", False),
    "transcribe":  ("transcribe_audio.py",           "회의 녹음 전사 (Graph 아님. R7. 외부 전송 주의)", False),

    # 쓰기는 동사를 앞에 둔다. 읽기 명령의 접두사가 되면 안 된다.
    # `mail` 을 허용하는 권한 규칙이 `mail-reply` 까지 통과시키기 때문이다.
    "reply-mail":  ("reply_outlook_mail.py",        "메일 회신  <message_id> --message  [쓰기]", True),
    "reply-teams": ("send_teams_reply.py",          "Teams 스레드 회신  <url> --message  [쓰기]", True),
    "post-teams":  ("post_teams_channel_message.py","Teams 채널 게시  <url> --message  [쓰기]", True),
    "create-event":("create_outlook_event.py",      "일정 등록  --subject --start --end  [쓰기]", True),
}

SETUP = {
    "setup":  ("setup_credentials.py", "자격증명 저장. JSON 을 표준입력으로 받는다"),
    "check":  ("check_connections.py", "연결 진단, 무엇이 되고 무엇이 안 되는지"),
    "verify": ("verify_harness.py",    "훅과 슬래시 명령이 살아 있는지 점검"),
}


def usage(code: int = 0) -> int:
    w = sys.stdout if code == 0 else sys.stderr
    print(__doc__.strip(), file=w)
    print("\n실행 방법:  bin/graph <명령> [옵션]", file=w)
    print("    macOS, Windows 모두 같다. cmd, PowerShell 에서만 bin\\graph.cmd\n", file=w)
    print("  읽기", file=w)
    for name, (_, desc, write) in COMMANDS.items():
        if not write:
            print(f"    {name:<12} {desc}", file=w)
    print("\n  쓰기 (되돌릴 수 없음. 먼저 --dry-run 으로 보여드릴 것)", file=w)
    for name, (_, desc, write) in COMMANDS.items():
        if write:
            print(f"    {name:<12} {desc}", file=w)
    print("\n  설정", file=w)
    for name, (_, desc) in SETUP.items():
        print(f"    {name:<12} {desc}", file=w)
    print("    login        로그인 상태 확인, 재로그인  [--check]", file=w)
    print("\n각 명령의 세부 옵션:  bin/graph <명령> --help", file=w)
    return code


def run(script: str, argv: list[str]) -> int:
    path = SCRIPTS / script
    if not path.exists():
        print(f"스크립트가 없습니다: {path}", file=sys.stderr)
        return 2
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SCRIPTS) + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run([sys.executable, str(path), *argv], env=env).returncode


def login(argv: list[str]) -> int:
    """토큰이 살아 있는지 확인한다. 없으면 브라우저 로그인이 뜬다."""
    check_only = "--check" in argv
    sys.path.insert(0, str(SCRIPTS))
    import secret_store as ss

    missing = [
        label for label, svc in (
            ("Client ID", ss.GRAPH_CLIENT_ID), ("Tenant ID", ss.GRAPH_TENANT_ID),
            ("Client Secret", ss.GRAPH_CLIENT_SECRET),
        ) if not ss.keychain_get(svc[1])
    ]
    if missing:
        print("자격증명이 없습니다: " + ", ".join(missing), file=sys.stderr)
        print("  에이전트에게 'Graph 설정해줘' 라고 말씀하십시오.", file=sys.stderr)
        return 1

    scopes = ROOT / ".claude" / "graph_scopes.txt"
    n = len([l for l in scopes.read_text(encoding="utf-8").splitlines()
             if l.strip() and not l.startswith("#")]) if scopes.exists() else 0
    import _graph_common as gc
    print(f"자격증명 확인됨. 요청 스코프 {n}종.")
    print(f"리디렉션 URI: {gc.LOCAL_REDIRECT_URI}")
    print("  Entra 앱 등록의 리디렉션 URI 와 정확히 같아야 합니다.")
    print("  다르면 AADSTS50011 이 뜹니다. 앱을 바꿀 수 없으면 환경변수로 맞춥니다:")
    print('    export MICROSOFT_GRAPH_REDIRECT_URI="<앱에 등록된 값>"')
    if check_only:
        return 0
    print("로그인을 확인합니다. 브라우저가 열리면 회사 계정으로 로그인하십시오.")
    return run("fetch_outlook_mail.py", ["--top", "1"])


def main() -> int:
    argv = sys.argv[1:]
    if not argv or argv[0] in ("-h", "--help", "help"):
        return usage(0)

    name, rest = argv[0], argv[1:]
    if name == "login":
        return login(rest)
    if name in SETUP:
        return run(SETUP[name][0], rest)
    if name in COMMANDS:
        return run(COMMANDS[name][0], rest)

    renamed = {"mail-reply": "reply-mail", "teams-reply": "reply-teams",
               "teams-post": "post-teams", "event": "create-event"}
    if name in renamed:
        print(f"'{name}' 은 '{renamed[name]}' 로 바뀌었습니다.", file=sys.stderr)
        print(f"  다시: bin/graph {renamed[name]} ...", file=sys.stderr)
        return 2

    print(f"모르는 명령: {name}\n", file=sys.stderr)
    return usage(2)


if __name__ == "__main__":
    sys.exit(main())
