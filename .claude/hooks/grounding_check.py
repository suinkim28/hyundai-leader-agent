#!/usr/bin/env python3
"""Stop hook: warn when the answer states figures the turn's sources do not contain.

Narrow trigger: only runs on turns that actually read source material
(tool results totalling more than MIN_SOURCE_CHARS characters).

Fully local. No LLM, no network, nothing leaves the machine.
Non-blocking: emits a systemMessage note, never forces a rewrite.

Checks numeric claims only (counts, amounts, percentages, dates, years),
because those are the claims that can be checked mechanically against a
source. Wording, attribution and reasoning are out of scope by design.
"""

import json
import re
import sys

MIN_SOURCE_CHARS = 1000
MAX_REPORTED = 8

# Digit runs with optional thousands separators and decimals.
NUM_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")

# Numbers small enough to be ordinary prose ("3단계", "2가지") are ignored
# unless they carry a unit that makes them a factual claim.
MIN_BARE_VALUE = 100

UNIT_SUFFIX_RE = re.compile(
    r"^\s*(%|퍼센트|원|주|명|건\b|개\b|장\b|억|만원|천원|MB|GB|KB|TB|배\b|년|월|일|시|분|초)"
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
    """Entries since the last real user message."""
    start = 0
    for i in range(len(entries) - 1, -1, -1):
        e = entries[i]
        if e.get("type") != "user":
            continue
        content = e.get("message", {}).get("content")
        # A tool_result carrier is not a real user turn boundary.
        if isinstance(content, list) and all(
            isinstance(b, dict) and b.get("type") == "tool_result" for b in content
        ):
            continue
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
    """Return (source_text, user_text, final_answer_text)."""
    sources, user_parts, answers = [], [], []
    for e in turn:
        etype = e.get("type")
        content = e.get("message", {}).get("content")
        if etype == "user":
            body = text_of(content)
            if isinstance(content, list) and any(
                isinstance(b, dict) and b.get("type") == "tool_result" for b in content
            ):
                sources.append(body)
            else:
                user_parts.append(body)
        elif etype == "assistant":
            if isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "text":
                        answers.append(block.get("text", ""))
                    elif block.get("type") == "tool_use":
                        sources.append(json.dumps(block.get("input", {}),
                                                  ensure_ascii=False))
    final = answers[-1] if answers else ""
    return "\n".join(sources), "\n".join(user_parts), final


def normalize(text):
    return re.sub(r"[,\s]", "", text)


def candidates(answer):
    found = []
    for m in NUM_RE.finditer(answer):
        raw = m.group(0)
        digits = raw.replace(",", "")
        if not digits or digits.startswith("."):
            continue
        try:
            value = float(digits)
        except ValueError:
            continue
        tail = answer[m.end():m.end() + 8]
        has_unit = bool(UNIT_SUFFIX_RE.match(tail))
        is_date_like = bool(re.match(r"^\s*[-/.]\d", tail)) or "-" in raw
        if value < MIN_BARE_VALUE and not has_unit and not is_date_like:
            continue
        found.append((raw, digits))
    # De-duplicate, preserve order.
    seen, out = set(), []
    for raw, digits in found:
        if digits in seen:
            continue
        seen.add(digits)
        out.append((raw, digits))
    return out


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
    _beat("grounding_check")
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

    turn = current_turn(entries)
    source, user_text, answer = collect(turn)

    if len(source) < MIN_SOURCE_CHARS or not answer.strip():
        return 0

    haystack = normalize(source) + normalize(user_text)
    unmatched = [raw for raw, digits in candidates(answer)
                 if digits not in haystack]

    if not unmatched:
        return 0

    shown = unmatched[:MAX_REPORTED]
    more = len(unmatched) - len(shown)
    listing = ", ".join(shown) + (f" 외 {more}건" if more > 0 else "")
    note = (
        f"[근거 대조] 이번 답변의 다음 수치가 이번 턴에서 읽은 자료에 그대로는 "
        f"보이지 않습니다: {listing}. "
        f"계산했거나 단위를 바꾼 값이면 정상입니다. 아니라면 원본을 다시 확인하세요."
    )
    print(json.dumps({"systemMessage": note}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
