#!/usr/bin/env python3
"""PreToolUse hook: 기억이 하네스 전용 저장소로 새는 것을 막는다.

왜 이것이 있는가
----------------
이 워크스페이스는 Claude Code, 헬피코드, 그 밖의 어떤 에이전트에서도 같은
결과를 내야 한다. 본부장의 기억이 특정 도구의 저장소에 들어가는 순간
그 기억은 그 도구에 갇힌다. 폴더를 옮기거나 회사가 도구를 교체하면 사라진다.

SYSTEM.md 8절에 규칙으로 적혀 있으나, 규칙은 읽히지 않을 수 있고 훅은
반드시 실행된다. 그래서 판정은 훅이 한다.

판정 기준은 하나다.
    이 폴더를 통째로 다른 PC 의 다른 에이전트로 옮겼을 때
    어제까지 쌓인 것이 전부 따라오는가.

막는 것
-------
  * 워크스페이스 밖 경로에 쓰기 (홈 디렉터리, ~/.claude, ~/.config 등)
  * .claude/ 아래에 기억을 남기는 것 (설정과 훅은 코드이지 기억이 아니다)
  * AGENTS.md / CLAUDE.md 수정 (SYSTEM.md 로 가는 포인터일 뿐이다)

통과시키는 것
-------------
  * PROFILE.md, ORG.md, decisions/, projects/, knowledge_base/ 등
    워크스페이스 안의 모든 마크다운 쓰기
  * 모든 읽기
  * logs/, briefings/, meetings/, drafts/ 같은 산출물 폴더
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path(__file__).resolve().parents[2])).resolve()

# .claude 아래에서 쓰기가 허용되는 것 (코드와 설정. 기억이 아니다)
CLAUDE_WRITE_OK = re.compile(r"^\.claude/(hooks|commands)/[^/]+$|^\.claude/(settings\.json|gate_policy\.json|graph_scopes\.txt)$")

# 포인터 파일. 내용은 SYSTEM.md 에 쓴다
POINTER_FILES = {"AGENTS.md", "CLAUDE.md"}

FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# 셸에서 파일을 만드는 흔한 형태
BASH_WRITE = [
    re.compile(r">>?\s*([^\s;|&]+)"),
    re.compile(r"\b(?:cp|mv|install|ln)\s+(?:-\S+\s+)*\S+\s+([^\s;|&]+)"),
    re.compile(r"\btee\s+(?:-\S+\s+)*([^\s;|&]+)"),
    re.compile(r"\bmkdir\s+(?:-\S+\s+)*([^\s;|&]+)"),
]


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))
    return 0


def verdict(raw_path: str):
    """막아야 하면 사유를 돌려준다. 괜찮으면 None."""
    if not raw_path:
        return None
    path = raw_path.strip().strip("'\"")
    if not path or path.startswith("-"):
        return None

    expanded = Path(os.path.expandvars(os.path.expanduser(path)))
    try:
        resolved = (ROOT / expanded).resolve() if not expanded.is_absolute() else expanded.resolve()
    except Exception:
        return None

    # 1. 워크스페이스 밖
    try:
        rel = resolved.relative_to(ROOT).as_posix()
    except ValueError:
        home = str(Path.home())
        if str(resolved).startswith(home) or "/.claude" in str(resolved):
            return (
                f"워크스페이스 밖에 쓰려고 합니다: {path}\n"
                f"기억은 이 폴더 안의 마크다운 파일에만 남깁니다 (SYSTEM.md 8절).\n"
                f"본부장 정보는 PROFILE.md, 조직은 ORG.md, 결정은 decisions/,\n"
                f"과제는 projects/, 참고자료는 knowledge_base/ 로 가야 합니다.\n"
                f"폴더를 다른 PC 의 다른 에이전트로 옮겼을 때 따라오지 않는 것은 기억이 아닙니다."
            )
        return None

    # 2. .claude 아래는 코드와 설정만
    if rel.startswith(".claude/") and not CLAUDE_WRITE_OK.match(rel):
        return (
            f".claude/ 아래에 기억을 남기려고 합니다: {rel}\n"
            f"이 폴더는 훅과 설정을 두는 곳이며 하네스 전용입니다.\n"
            f"본부장 정보는 PROFILE.md, 조직은 ORG.md 로 가야 합니다 (SYSTEM.md 8절)."
        )

    # 3. 포인터 파일
    if rel in POINTER_FILES:
        return (
            f"{rel} 은 SYSTEM.md 로 가는 포인터입니다. 내용을 여기 쌓지 않습니다.\n"
            f"운영 규칙을 고쳐야 한다면 SYSTEM.md 를 고칩니다 (SYSTEM.md 11절)."
        )

    return None


try:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _heartbeat import beat as _beat
except Exception:                                    # pragma: no cover
    def _beat(*_a, **_kw):
        return None


def main():
    _beat("keep_memory_portable")
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool = payload.get("tool_name", "")
    data = payload.get("tool_input", {}) or {}

    if tool in FILE_TOOLS:
        reason = verdict(data.get("file_path") or data.get("notebook_path") or "")
        if reason:
            return deny(reason)
        return 0

    if tool == "Bash":
        command = data.get("command", "") or ""
        if "ALLOW_OUTSIDE_WRITE=1" in command:
            return 0
        for pattern in BASH_WRITE:
            for match in pattern.finditer(command):
                reason = verdict(match.group(1))
                if reason:
                    return deny(reason)
    return 0


if __name__ == "__main__":
    sys.exit(main())
