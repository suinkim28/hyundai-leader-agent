#!/usr/bin/env python3
"""PreToolUse hook: 기억이 하네스 전용 저장소로 새는 것을 막고, 갈 곳을 알려준다.

왜 이것이 있는가
----------------
이 워크스페이스는 Claude Code, 헬피코드, 그 밖의 어떤 에이전트에서도 같은
결과를 내야 한다. 본부장의 기억이 특정 도구의 저장소에 들어가는 순간
그 기억은 그 도구에 갇힌다. 폴더를 옮기거나 회사가 도구를 교체하면 사라진다.

판정 기준은 하나다.
    이 폴더를 통째로 다른 PC 의 다른 에이전트로 옮겼을 때
    어제까지 쌓인 것이 전부 따라오는가.

Claude Code 의 auto memory
--------------------------
Claude Code 는 스스로 배운 것을 `~/.claude/projects/<프로젝트>/memory/` 에
쌓는다 (공식 문서 "How Claude remembers your project"). 이 경로는 홈
디렉터리이며 git 에도 없고 폴더를 옮겨도 따라오지 않는다. 그래서

  1. `.claude/settings.json` 의 `autoMemoryEnabled: false` 로 기능을 끄고,
  2. 그래도 저 경로로 쓰려는 시도가 오면 이 훅이 막으면서
     **어느 파일에 대신 쓰면 되는지** 알려준다.

막는 것으로 끝내지 않는다. 기억할 내용 자체는 남겨야 하므로, 종류에 따라
PROFILE.md / ORG.md / decisions/ / projects/ 중 어디로 가야 하는지 답한다.

무엇을 막는가
-------------
  * 워크스페이스 밖 쓰기 (홈 디렉터리, Claude 설정 폴더 등)
  * 워크스페이스 안이라도 `.claude/` 아래의 **로컬 상태**:
    settings.local.json, 세션 전사(.jsonl), auto memory, `*-local/`
  * AGENTS.md / CLAUDE.md / CLAUDE.local.md (SYSTEM.md 로 가는 포인터)

무엇을 통과시키는가
-------------------
  * 모든 읽기
  * 워크스페이스 안의 모든 산출물 (PROFILE.md, ORG.md, decisions/,
    projects/, meetings/, drafts/, logs/, knowledge_base/ ...)
  * `.claude/` 아래의 **설정과 코드**: settings.json, hooks/, commands/,
    agents/, skills/, rules/, workflows/ 등. 여기는 git 에 커밋되어
    폴더와 함께 이동하므로 기억이 갇히지 않는다.

`.claude/` 를 통째로 막지 않는 이유: 새 설정 폴더가 생길 때마다 훅을 고쳐야
하고, 정작 막고 싶은 auto memory 는 애초에 홈 디렉터리에 있어서 저 규칙에
걸리지도 않았다. 그래서 허용 목록이 아니라 **로컬 상태 차단 목록**으로 뒤집었다.

Windows 주의
------------
본부장 PC 는 Windows 다. 경로 비교를 문자열로 하면(`"/.claude" in path`)
`C:\\Users\\...\\.claude\\...` 에서 조용히 빗나간다. 그래서

  * 폴더 포함 관계는 `Path.relative_to` 로 보고, 실패하면
    `os.path.normcase` 로 한 번 더 본다 (Windows 의 대소문자, 역슬래시)
  * 파일 이름 비교는 `.lower()` 로 한다. `normcase` 는 Windows 에서만
    소문자로 바꾸므로, 이것으로 이름을 비교하면 macOS 에서 조용히 빠진다
  * 설정 폴더는 `CLAUDE_CONFIG_DIR` 을 먼저 본다: 홈 밖(다른 드라이브)에
    있을 수 있다
"""

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(os.environ.get("CLAUDE_PROJECT_DIR", Path(__file__).resolve().parents[2])).resolve()

# 포인터 파일. 내용은 SYSTEM.md 에 쓴다
POINTER_FILES = {"AGENTS.md", "CLAUDE.md", "CLAUDE.local.md"}

FILE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}

# 셸에서 파일을 만드는 흔한 형태
BASH_WRITE = [
    re.compile(r">>?\s*([^\s;|&]+)"),
    re.compile(r"\b(?:cp|mv|install|ln)\s+(?:-\S+\s+)*\S+\s+([^\s;|&]+)"),
    re.compile(r"\btee\s+(?:-\S+\s+)*([^\s;|&]+)"),
    re.compile(r"\bmkdir\s+(?:-\S+\s+)*([^\s;|&]+)"),
]

# 기억을 어디로 보내야 하는지. 막기만 하면 그 내용은 그냥 사라진다.
WHERE_TO_WRITE = (
    "기억은 이 폴더 안의 마크다운에만 남깁니다 (SYSTEM.md 8절). 종류별로:\n"
    "  본부장 개인, 선호, 답변 규칙  -> PROFILE.md\n"
    "  인물, 조직, 과제, 약어        -> ORG.md\n"
    "  회의에서 내려진 결정과 근거   -> decisions/\n"
    "  과제 상태와 리스크 변화       -> projects/\n"
    "  외부 참고자료                 -> knowledge_base/"
)


def deny(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))
    return 0


def _inside(child: Path, parent: Path) -> bool:
    """child 가 parent 안인가. Windows 의 대소문자와 역슬래시를 견딘다."""
    try:
        child.relative_to(parent)
        return True
    except ValueError:
        pass
    c, p = os.path.normcase(str(child)), os.path.normcase(str(parent))
    return c == p or c.startswith(p.rstrip(os.sep) + os.sep)


def _config_dirs():
    """Claude Code 가 설정과 상태를 두는 폴더. 홈 밖일 수 있다."""
    candidates = []
    env = os.environ.get("CLAUDE_CONFIG_DIR")
    if env:
        candidates.append(Path(os.path.expanduser(env)))
    candidates.append(Path.home() / ".claude")
    out = []
    for c in candidates:
        try:
            out.append(c.resolve())
        except Exception:
            continue
    return out


def _looks_like_auto_memory(resolved: Path) -> bool:
    """Claude auto memory 저장소인가.

    기본값은 <설정폴더>/projects/<프로젝트>/memory/ 이지만
    autoMemoryDirectory 로 옮길 수 있으므로 경로 모양으로도 본다.
    """
    parts = [p.lower() for p in resolved.parts]
    if "memory" in parts[:-1]:
        return True
    return resolved.name.lower() == "memory.md"


def _claude_dir_verdict(tail):
    """워크스페이스 안 `.claude/` 아래 경로(tail)가 로컬 상태인가.

    통과시키는 것이 기본이다. 설정과 코드는 커밋되어 폴더와 함께 이동한다.
    """
    if not tail:
        return None
    name = tail[-1]
    parents = tail[:-1]

    if name.lower() == "settings.local.json":
        return (
            "settings.local.json 은 이 PC 에만 남는 개인 설정입니다.\n"
            "폴더를 옮기면 따라오지 않으므로 여기에 규칙이나 기억을 두지 않습니다.\n"
            "팀이 공유해야 하는 설정은 .claude/settings.json 에 씁니다."
        )
    if name.lower().endswith(".jsonl"):
        return (
            f".claude/ 아래에 세션 기록을 남기려고 합니다: {'/'.join(tail)}\n"
            "전사와 세션 상태는 하네스가 알아서 보관합니다. 워크스페이스에 두지 않습니다.\n"
            + WHERE_TO_WRITE
        )
    if name.lower() == "claude.md":
        return (
            ".claude/CLAUDE.md 는 Claude Code 만 읽는 지시문입니다.\n"
            "이 워크스페이스의 운영 규칙은 어느 에이전트에서나 같아야 하므로\n"
            "SYSTEM.md 에 씁니다 (SYSTEM.md 11절)."
        )
    if any(p.lower() == "memory" for p in parents) or name.lower() == "memory.md":
        return (
            f".claude/ 아래에 기억을 쌓으려고 합니다: {'/'.join(tail)}\n" + WHERE_TO_WRITE
        )
    if any(p.lower().endswith("-local") for p in parents):
        return (
            f"{'/'.join(tail)} 은 이 PC 에만 남는 로컬 저장소입니다.\n"
            "폴더를 옮기면 따라오지 않습니다.\n" + WHERE_TO_WRITE
        )
    return None


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
    if not _inside(resolved, ROOT):
        in_claude = any(_inside(resolved, c) for c in _config_dirs())
        in_home = _inside(resolved, Path.home())

        if in_claude and _looks_like_auto_memory(resolved):
            return (
                f"Claude 전용 메모리 저장소에 쓰려고 합니다: {path}\n"
                "이 경로는 이 PC 의 홈 디렉터리에 있어 폴더를 옮기면 따라오지 않고,\n"
                "다른 에이전트도 읽지 못합니다. 기억할 내용이라면 아래로 옮겨 주십시오.\n"
                + WHERE_TO_WRITE
            )
        if in_claude or in_home:
            return (
                f"워크스페이스 밖에 쓰려고 합니다: {path}\n"
                "폴더를 다른 PC 의 다른 에이전트로 옮겼을 때 따라오지 않는 것은 기억이 아닙니다.\n"
                + WHERE_TO_WRITE
            )
        return None

    try:
        rel = resolved.relative_to(ROOT).as_posix()
    except ValueError:
        # _inside 는 normcase 로도 판정한다. Windows 에서 대소문자만 다른
        # 경로는 relative_to 가 거부하므로 여기서 직접 잘라 낸다.
        cut = len(os.path.normcase(str(ROOT)).rstrip(os.sep)) + 1
        rel = str(resolved)[cut:].replace("\\", "/")

    # 2. `.claude/` 아래는 설정과 코드만. 로컬 상태는 막는다
    parts = rel.split("/")
    if parts and parts[0].lower() == ".claude":
        reason = _claude_dir_verdict(parts[1:])
        if reason:
            return reason
        return None

    # 3. 포인터 파일
    if rel in POINTER_FILES:
        return (
            f"{rel} 은 SYSTEM.md 로 가는 포인터입니다. 내용을 여기 쌓지 않습니다.\n"
            "운영 규칙을 고쳐야 한다면 SYSTEM.md 를 고칩니다 (SYSTEM.md 11절)."
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
