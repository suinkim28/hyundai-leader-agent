#!/usr/bin/env python3
"""SessionStart hook: 개인화 상태를 확인하고, 비어 있으면 부트스트랩으로 보낸다.

왜 이것이 있는가
----------------
이 스켈레톤의 첫 사용자는 자기 정보가 하나도 들어 있지 않은 상태에서
"비서 역할을 해달라"고 말한다. 그때 에이전트가 일반론으로 답하기 시작하면
개인화는 영원히 시작되지 않는다. 첫 턴에 반드시 **질문하는 쪽**이 되어야 한다.

SYSTEM.md 에도 같은 규칙이 적혀 있지만, 규칙은 읽히지 않을 수 있고 훅은
반드시 실행된다. 그래서 상태 판정은 훅이 하고, 무엇을 물을지는 문서가 정한다.

판정 기준은 하나다: PROFILE.md 의 `상태:` 줄.
"""

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PROFILE = ROOT / "PROFILE.md"
ORG = ROOT / "ORG.md"
SCRIPTS = ROOT / "scripts"

STATE_RE = re.compile(r"^\s*-?\s*상태\s*[:：]\s*(\S+)", re.MULTILINE)


def state_of(path):
    """'미완료' / '진행중' / '완료' / '없음' 중 하나."""
    if not path.exists():
        return "없음"
    m = STATE_RE.search(path.read_text(encoding="utf-8"))
    return m.group(1) if m else "미완료"


def graph_credentials_missing():
    """저장소에 Graph 자격증명이 없으면 빠진 항목 이름을 돌려준다.

    설정은 개인화보다 먼저다. 연결이 없으면 Quick Win 을 실제 데이터로
    시연할 수 없고, 부트스트랩 10문항의 마지막 단계가 빈손이 된다.
    """
    try:
        sys.path.insert(0, str(SCRIPTS))
        import secret_store as ss
        pairs = (("Client ID", ss.GRAPH_CLIENT_ID),
                 ("Tenant ID", ss.GRAPH_TENANT_ID),
                 ("Client Secret", ss.GRAPH_CLIENT_SECRET))
        return [label for label, svc in pairs if not ss.keychain_get(svc[1])]
    except Exception:
        return []


def emit(context):
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": context,
        }
    }, ensure_ascii=False))


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
    _beat("session_start")
    try:
        json.load(sys.stdin)
    except (json.JSONDecodeError, ValueError):
        pass

    profile_state = state_of(PROFILE)
    org_state = state_of(ORG)

    missing = graph_credentials_missing()
    if missing:
        emit(
            "[설정 미완료] Microsoft Graph 자격증명이 이 컴퓨터에 없습니다: "
            + ", ".join(missing) + "\n"
            "사용자가 무엇을 요청하든, 먼저 `.claude/commands/setup.md` 절차를 "
            "따라 설정을 마치십시오. 사용자는 터미널을 쓰지 않습니다. "
            "명령어를 알려주지 말고 필요한 값만 여쭌 뒤 에이전트가 직접 실행하십시오.\n"
            "설정이 끝나면 멈추지 말고 그대로 부트스트랩(BOOTSTRAP.md)으로 이어가십시오."
        )
        return 0

    if profile_state in ("미완료", "없음"):
        emit(
            "[개인화 미완료] PROFILE.md 가 아직 채워지지 않았습니다.\n"
            "이 세션에서 사용자가 무엇을 요청하든, 먼저 BOOTSTRAP.md 를 읽고 "
            "**1단계 필수 질문**부터 진행하십시오. 일반적인 조언으로 답하지 마십시오.\n"
            "질문은 한 번에 하나씩, 답을 들을 때마다 PROFILE.md 의 해당 항목을 "
            "즉시 갱신하고, 10개 항목이 차면 상태를 `진행중` 으로 바꾸고 "
            "Quick Win 한 건을 실제로 실행해 보여 주십시오."
        )
        return 0

    if profile_state == "진행중" or org_state in ("미완료", "없음"):
        emit(
            "[개인화 진행중] PROFILE.md 의 기본 항목은 채워졌으나 "
            "아직 `완료` 상태가 아닙니다. 오늘 일과에서 새로 확인된 선호, 규칙, "
            "이해관계자는 BOOTSTRAP.md 의 `2단계 누적 학습` 절차에 따라 "
            "PROFILE.md / ORG.md 에 반영하십시오. "
            f"(ORG.md 상태: {org_state})"
        )
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
