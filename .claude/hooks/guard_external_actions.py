#!/usr/bin/env python3
"""PreToolUse hook: 되돌릴 수 없는 행동 직전에 사람에게 되묻는다.

왜 이것이 있는가
----------------
본부장 에이전트는 본부장 본인 계정으로 동작한다. 메일이 나가면 본부장이 보낸
것이고, Confluence 문서가 바뀌면 본부장이 바꾼 것이다. 모델이 잘못 판단해도
"에이전트가 그랬다"는 변명이 성립하지 않는다.

그래서 **조회는 전부 그냥 통과시키고, 바깥세상을 바꾸는 호출만** 잡아서
확인을 받는다. 모든 것을 확인받으면 아무도 쓰지 않고, 아무것도 확인받지
않으면 언젠가 사고가 난다.

게이트 등급
-----------
본부장마다 "무엇을 확인받고 싶은가"가 다르다. 사전설문 응답이 실제로 셋 다
달랐다. `.claude/gate_policy.json` 에서 등급을 고른다.

  standard  발송, 게시, 캘린더 변경, 원격 쓰기, 삭제만 확인   (기본값)
  strict    standard + 문서 수정/게시, 업무지시, 담당자 지정
  paranoid  모든 도구 호출을 확인 (조회, 검색 포함)

paranoid 는 사용성이 크게 떨어진다. 설문에서 "모든 실행 행위"를 고른 분에게는
1회차에서 "실행"이 발송, 수정을 뜻한 것인지 조회까지 포함한 것인지 반드시
되물은 뒤 등급을 정할 것.

읽기, 검색, `--dry-run` 은 어느 등급에서도(paranoid 제외) 건드리지 않는다.
"""

import json
import re
import sys
from pathlib import Path

PREVIEW_CHARS = 400
POLICY_PATH = Path(__file__).resolve().parents[1] / "gate_policy.json"

# --- Bash: 외부 발송 (--dry-run 이 없을 때만 실제 발송) --------------------
# 스크립트 이름과 bin/graph 하위 명령을 모두 잡는다. 어느 한쪽만 잡으면
# 다른 경로로 부를 때 게이트가 조용히 사라진다.
SEND_PATTERNS = [
    (re.compile(r"\breply_outlook_mail\b|\bgraph(?:\.py|\.cmd)?\s+reply-mail\b"),
     "Outlook 메일 발송"),
    (re.compile(r"\bsend_teams_reply\b|\bgraph(?:\.py|\.cmd)?\s+reply-teams\b"),
     "Teams 메시지 발송"),
    (re.compile(r"\bpost_teams_channel_message\b|\bgraph(?:\.py|\.cmd)?\s+post-teams\b"),
     "Teams 채널 새 글 게시"),
]

# --- Bash: 캘린더 변경 (dry-run 옵션이 없다) ------------------------------
CALENDAR_PATTERNS = [
    (re.compile(r"\bcreate_outlook_event\b|\bgraph(?:\.py|\.cmd)?\s+create-event\b"),
     "Outlook 일정 생성"),
    (re.compile(r"\bdelete_outlook_event\b"), "Outlook 일정 삭제"),
]

# --- Bash: 파괴적 파일 조작 ------------------------------------------------
DESTRUCTIVE_PATTERNS = [
    (re.compile(r"\brm\s+(-\w+\s+)*-[rRf]"), "파일/디렉터리 삭제"),
    (re.compile(r"\bgit\s+(push\s+.*--force|reset\s+--hard|clean\s+-\w*[fd])"), "Git 이력 파괴"),
    (re.compile(r"\b(shred|truncate)\b"), "파일 내용 파괴"),
]

DRY_RUN_RE = re.compile(r"--dry-run\b")

# --- MCP 쓰기 도구 ---------------------------------------------------------
MCP_WRITE_RE = re.compile(
    r"^mcp__[A-Za-z0-9_-]*?atlassian[A-Za-z0-9_-]*__(?:create|edit|transition|update|add|delete)",
)

MCP_LABELS = {
    "createJiraIssue": "Jira 이슈 생성",
    "editJiraIssue": "Jira 이슈 수정",
    "transitionJiraIssue": "Jira 상태 변경",
    "addCommentToJiraIssue": "Jira 코멘트 등록",
    "createConfluencePage": "Confluence 페이지 생성",
    "updateConfluencePage": "Confluence 페이지 수정",
    "createConfluenceFooterComment": "Confluence 코멘트 등록",
}

# strict 등급에서 추가로 잡는 것: "업무지시, 담당자 지정"에 해당한다.
ASSIGNMENT_KEYS = {"assignee", "assigneeAccountId", "assignee_id"}


def load_policy():
    default = {"등급": "standard", "본부장": "미설정"}
    try:
        data = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ValueError):
        return default
    if not isinstance(data, dict):
        return default
    level = data.get("등급")
    if level not in ("standard", "strict", "paranoid"):
        level = "standard"
    return {"등급": level, "본부장": data.get("본부장", "미설정")}


def ask(reason):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "ask",
            "permissionDecisionReason": reason,
        }
    }, ensure_ascii=False))
    return 0


def extract_body(command):
    m = re.search(r"(?:--message|-m)\s+(['\"])(.*?)\1", command, re.S)
    if m:
        return m.group(2)
    m = re.search(r"--message-file\s+(\S+)", command)
    if m:
        return f"(파일: {m.group(1)})"
    if "--stdin" in command:
        return "(stdin으로 전달)"
    return ""


def extract_target(command):
    m = re.search(r"https://teams\.microsoft\.com/\S+", command)
    if m:
        url = m.group(0).strip("'\"")
        chan = re.search(r"channelName=([^&'\"]+)", url)
        return f"Teams 채널 {chan.group(1)}" if chan else "Teams 대화"
    m = re.search(r"--to\s+(['\"]?)([^\s'\"]+@[^\s'\"]+)\1", command)
    if m:
        return f"수신자 {m.group(2)}"
    m = re.search(r"(?:reply_outlook_mail\S*|graph(?:\.py|\.cmd)?\s+reply-mail)"
                  r"\s+(?:\S+\s+)*?([A-Za-z0-9=_-]{40,})", command)
    if m:
        return f"메일 ID {m.group(1)[:24]}..."
    return ""


def handle_bash(command, level):
    for pattern, label in SEND_PATTERNS:
        if pattern.search(command):
            if DRY_RUN_RE.search(command):
                return 0  # 미리보기는 그냥 통과
            target = extract_target(command) or "(대상 확인 필요)"
            body = extract_body(command)
            preview = body[:PREVIEW_CHARS] + ("..." if len(body) > PREVIEW_CHARS else "")
            return ask(
                f"[{label}] 본부장님 계정으로 실제 발송합니다. 되돌릴 수 없습니다.\n"
                f"대상: {target}\n"
                f"본문: {preview or '(추출 실패, 명령을 직접 확인해 주세요)'}"
            )

    for pattern, label in CALENDAR_PATTERNS:
        if pattern.search(command):
            return ask(f"[{label}] 캘린더를 변경합니다.\n명령: {command[:PREVIEW_CHARS]}")

    for pattern, label in DESTRUCTIVE_PATTERNS:
        if pattern.search(command):
            return ask(
                f"[{label}] 되돌릴 수 없는 삭제를 시도합니다.\n"
                f"명령: {command[:PREVIEW_CHARS]}"
            )

    return 0


def handle_mcp(tool_name, tool_input, level):
    if not MCP_WRITE_RE.match(tool_name):
        return 0
    short = tool_name.split("__")[-1]
    label = MCP_LABELS.get(short, short)

    detail = ""
    if isinstance(tool_input, dict):
        for key in ("issueIdOrKey", "projectKey", "pageId", "title", "summary", "commentBody"):
            if tool_input.get(key):
                detail += f"\n{key}: {str(tool_input[key])[:200]}"
        if level == "strict" and ASSIGNMENT_KEYS & set(tool_input):
            detail += "\n⚠ 담당자 지정이 포함되어 있습니다 (업무지시에 해당)."

    return ask(f"[{label}] 사내 시스템에 기록합니다.{detail}")


# --- 훅 실행 흔적 (하네스 검증용) ---------------------------------------
# Python 부재, 워크스페이스 미신뢰 등으로 훅이 조용히 무시되는 상황을 잡기 위한 것.
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
    _beat("guard_external_actions")
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    policy = load_policy()
    level = policy["등급"]
    tool_name = payload.get("tool_name", "")
    tool_input = payload.get("tool_input", {}) or {}

    if level == "paranoid":
        preview = json.dumps(tool_input, ensure_ascii=False)[:PREVIEW_CHARS]
        return ask(
            f"[전체 확인 모드] {tool_name} 을(를) 실행합니다.\n"
            f"입력: {preview}\n"
            f"※ 조회까지 매번 확인하는 설정입니다. 불편하시면 "
            f".claude/gate_policy.json 의 등급을 standard 로 바꾸십시오."
        )

    if tool_name == "Bash":
        command = tool_input.get("command", "")
        return handle_bash(command, level) if isinstance(command, str) else 0

    if tool_name.startswith("mcp__"):
        return handle_mcp(tool_name, tool_input, level)

    return 0


if __name__ == "__main__":
    sys.exit(main())
