#!/usr/bin/env python3
"""Stop hook: 사내 자료를 읽고 답했는데 출처가 없으면 지적한다.

왜 이것이 있는가
----------------
본부장이 이 답변을 그대로 들고 회의에 들어간다. 출처가 없으면 그 자리에서
"어디서 나온 얘기냐"는 질문에 답할 수 없고, 한 번 그런 일이 생기면 에이전트
전체를 다시 쓰지 않게 된다. 답변 품질보다 **추적 가능성**이 먼저다.

기계적으로 확인할 수 있는 것만 본다 — 자료를 읽은 턴인가, 그 답변에 출처
표기가 하나라도 있는가. 표기가 정확한지는 판단할 수 없으므로 검사하지 않는다.

완전히 로컬에서 동작하고, 막지 않고 알려주기만 한다.
"""

import json
import re
import sys

MIN_SOURCE_CHARS = 800     # 이보다 적게 읽었으면 "자료 기반 답변"으로 보지 않는다
MIN_ANSWER_CHARS = 200     # 짧은 확인 답변("네, 처리했습니다")은 대상이 아니다

# 인정하는 출처 표기. SYSTEM.md 의 표기 규약과 같아야 한다.
CITATION_RE = re.compile(
    r"\[출처[:：]"          # [출처: Outlook 메일 ...]
    r"|\[판단\]"            # 근거가 아니라 해석임을 밝힌 것
    r"|\[미확보\]"          # 확인하지 못했음을 밝힌 것
    r"|\[추정\]"
    r"|https?://"           # 링크가 곧 출처
    r"|출처\s*[:：]"
    r"|근거\s*[:：]"
)

# 자료를 실제로 읽었다고 볼 수 있는 도구.
SOURCE_TOOLS = re.compile(
    r"fetch_outlook_mail|fetch_outlook_calendar|fetch_teams_message"
    r"|mcp__[A-Za-z0-9_-]*atlassian|WebFetch|WebSearch|transcribe_audio"
    r"|fetch_market_intel|sync_teams"
)


def load_entries(path):
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.read().splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def current_turn(entries):
    """마지막 실제 사용자 메시지 이후의 항목들."""
    start = 0
    for i in range(len(entries) - 1, -1, -1):
        e = entries[i]
        if e.get("type") != "user":
            continue
        content = e.get("message", {}).get("content")
        if isinstance(content, list) and all(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        ):
            continue  # 도구 결과 운반용 user 항목은 턴 경계가 아니다
        start = i
        break
    return entries[start:]


def text_of(content):
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    parts = []
    for block in content:
        if not isinstance(block, dict):
            continue
        if block.get("type") == "text" and isinstance(block.get("text"), str):
            parts.append(block["text"])
        elif block.get("type") == "tool_result":
            inner = block.get("content")
            if isinstance(inner, str):
                parts.append(inner)
            elif isinstance(inner, list):
                for ib in inner:
                    if isinstance(ib, dict) and isinstance(ib.get("text"), str):
                        parts.append(ib["text"])
    return "\n".join(parts)


def collect(turn):
    """(읽은 자료, 사용한 도구 이름들, 최종 답변) 을 돌려준다."""
    sources, tool_names, answers = [], [], []
    for e in turn:
        etype = e.get("type")
        content = e.get("message", {}).get("content")
        if etype == "user":
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                sources.append(text_of(content))
        elif etype == "assistant" and isinstance(content, list):
            for block in content:
                if not isinstance(block, dict):
                    continue
                if block.get("type") == "text":
                    answers.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_names.append(block.get("name", ""))
                    tool_names.append(
                        json.dumps(block.get("input", {}), ensure_ascii=False)[:2000]
                    )
    return "\n".join(sources), "\n".join(tool_names), (answers[-1] if answers else "")


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
    _beat("cite_sources")
    try:
        payload = json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        return 0

    if payload.get("stop_hook_active"):
        return 0

    path = payload.get("transcript_path")
    if not path:
        return 0

    entries = load_entries(path)
    if not entries:
        return 0

    source, tools, answer = collect(current_turn(entries))

    if len(source) < MIN_SOURCE_CHARS:
        return 0
    if len(answer.strip()) < MIN_ANSWER_CHARS:
        return 0
    if not SOURCE_TOOLS.search(tools):
        return 0
    if CITATION_RE.search(answer):
        return 0

    note = (
        "[출처 누락] 메일·일정·Confluence·Teams 등 사내 자료를 읽고 답했는데 "
        "답변에 출처 표기가 하나도 없습니다. 본부장님이 이 내용을 회의에서 "
        "그대로 인용하실 수 있으므로, 각 사실 옆에 "
        "`[출처: 채널 · 날짜 · 작성자]` 를 붙이고, 자료에 없는 해석은 `[판단]`, "
        "확인하지 못한 것은 `[미확보]` 로 표시해 주세요."
    )
    print(json.dumps({"systemMessage": note}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
