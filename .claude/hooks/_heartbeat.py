#!/usr/bin/env python3
"""훅이 실제로 실행됐다는 흔적을 남긴다.

왜 이것이 있는가
----------------
안전장치가 없는 것보다 나쁜 상태는 **없는데 있다고 믿는 상태**다.

VS Code + Claude Code 확장은 `.claude/settings.json` 의 훅 등록을 표준으로
존중한다. 그래도 이 컴퓨터에 Python 이 없거나, 워크스페이스를 신뢰하지
않았거나, 프로젝트 루트를 다르게 잡으면 **아무 오류 없이 조용히 무시된다.**
그러면 메일 발송 확인 창이 뜨지 않고, 그 사실을 사고가 난 뒤에야 알게 된다.

그래서 훅이 돌 때마다 흔적을 남긴다. `scripts/verify_harness.py` 가 그 흔적을
읽어 "이 하네스에서 훅이 실제로 동작하는가"를 판정한다.

이 모듈은 **절대 예외를 던지지 않는다.** 심장박동 기록이 실패했다고 해서
안전장치가 멈추면 안 된다.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

BEAT_DIR = Path(__file__).resolve().parents[2] / "logs" / ".harness"


def beat(hook_name: str, detail: str = "") -> None:
    """훅 실행 흔적 한 건. 실패해도 조용히 넘어간다."""
    try:
        BEAT_DIR.mkdir(parents=True, exist_ok=True)
        payload = {
            "hook": hook_name,
            "at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "epoch": int(time.time()),
            "detail": detail[:200],
            "cwd": os.getcwd()[:300],
        }
        (BEAT_DIR / f"{hook_name}.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8"
        )
    except Exception:
        pass
