#!/usr/bin/env python3
"""PreToolUse hook: block writes that would destroy .env secrets.

Why this exists
---------------
2026-08-27: an agent overwrote `Secretary/.env` with `.env.example`,
wiping four live secrets. There was no git history (.env is gitignored),
no APFS snapshot, and no Time Machine. Three values were recovered from
Keychain and session transcripts; MICROSOFT_GRAPH_CLIENT_SECRET was lost
outright and had to be reissued in Azure.

The two files sit side by side with identical key names, so copying the
example over the real file is a one-character mistake. This hook makes
that mistake impossible.

Scope
-----
Denies (not "ask" -- there is no legitimate reason to do these):
  * Write / Edit / MultiEdit / NotebookEdit targeting a .env file
  * Bash redirections, cp, mv, tee, install, ln, truncate, rm, sed -i
    that would clobber a .env file

Allows:
  * every read (cat, grep, source, python-dotenv, ...)
  * .env.example and other templates -- only the live files are guarded
  * an explicit human override via ALLOW_ENV_WRITE=1 in the command

Exit code 0 with a `deny` decision; a bare 0 means "not my business".
"""

import json
import os
import re
import sys

# Live secret files. Templates (.env.example, .env.sample, .env.template,
# .env.dist) are deliberately NOT protected -- they carry no secrets.
PROTECTED_BASENAMES = re.compile(
    r"(?:^|/)\.env(?:\.(?!example$|sample$|template$|dist$)[A-Za-z0-9_-]+)?$"
)

OVERRIDE_RE = re.compile(r"\bALLOW_ENV_WRITE=1\b")

# Bash constructs that can clobber a file.
BASH_WRITE_PATTERNS = [
    # > .env   >> .env   1> .env      (redirection)
    (re.compile(r"(?<![0-9<>])>>?\s*(['\"]?)([^\s;|&'\"]*\.env[^\s;|&'\"]*)\1"), 2),
    # cp/mv/install/ln SRC ... DEST    (last path wins)
    (re.compile(r"\b(?:cp|mv|install|ln)\b[^;|&]*?(['\"]?)([^\s;|&'\"]*\.env[^\s;|&'\"]*)\1\s*(?:;|\||&|$)"), 2),
    # tee .env
    (re.compile(r"\btee\b(?:\s+-\w+)*\s+(['\"]?)([^\s;|&'\"]*\.env[^\s;|&'\"]*)\1"), 2),
    # rm .env / truncate .env
    (re.compile(r"\b(?:rm|truncate|shred)\b[^;|&]*?(['\"]?)([^\s;|&'\"]*\.env[^\s;|&'\"]*)\1"), 2),
    # sed -i ... .env   (in-place edit)
    (re.compile(r"\bsed\b[^;|&]*?-i[^;|&]*?(['\"]?)([^\s;|&'\"]*\.env[^\s;|&'\"]*)\1"), 2),
]

GUIDANCE = (
    "\n\n.env 는 git 에 없고 스냅샷도 없어 덮어쓰면 복구가 어렵습니다."
    "\n키를 바꿔야 한다면 다음 중 하나로 진행하세요."
    "\n  1) 사용자에게 직접 편집을 요청"
    "\n  2) 특정 키만 갱신:  security add-generic-password -U -a \"$USER\" -s <서비스명> -w"
    "\n  3) 정말 필요하면 명령 앞에 ALLOW_ENV_WRITE=1 을 붙여 명시적으로 우회"
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


def is_protected(path):
    if not path:
        return False
    return bool(PROTECTED_BASENAMES.search(str(path).strip().strip("'\"")))


def handle_file_tool(tool_name, tool_input):
    path = ""
    if isinstance(tool_input, dict):
        path = (tool_input.get("file_path")
                or tool_input.get("notebook_path")
                or tool_input.get("path")
                or "")
    if is_protected(path):
        return deny(
            f"[{tool_name}] {os.path.basename(str(path))} 쓰기를 차단했습니다."
            f"{GUIDANCE}"
        )
    return 0


def handle_bash(command):
    if OVERRIDE_RE.search(command):
        return 0  # explicit, deliberate override
    for pattern, group in BASH_WRITE_PATTERNS:
        m = pattern.search(command)
        if m:
            target = m.group(group)
            if is_protected(target):
                return deny(
                    f"[Bash] {target} 를 덮어쓰거나 지우는 명령을 차단했습니다."
                    f"\n명령: {command[:300]}"
                    f"{GUIDANCE}"
                )
    return 0


# --- 훅 실행 흔적 (하네스 검증용) ---------------------------------------
# 래퍼 위에서 훅이 조용히 무시되는 상황을 잡기 위한 것.
# 기록 실패가 안전장치를 멈추면 안 되므로 전부 감싼다.
try:
    import sys as _sys
    from pathlib import Path as _Path
    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from _heartbeat import beat as _beat
except Exception:                                    # pragma: no cover
    def _beat(*_a, **_kw):
        return None


def main():
    _beat("protect_secrets")
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    if tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        return handle_file_tool(tool_name, tool_input)

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        return handle_bash(command) if isinstance(command, str) else 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
