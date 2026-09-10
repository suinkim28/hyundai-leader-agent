#!/usr/bin/env python3
"""하네스 검증: 이 실행 환경에서 안전장치가 실제로 동작하는가.

왜 이것이 있는가
----------------
`check_connections.py` 가 "바깥세상과 연결됐는가"를 본다면, 이것은
**"내 안전장치가 살아 있는가"** 를 본다.

VS Code + Claude Code 확장은 `.claude/settings.json` 의 훅 등록을 표준으로
존중한다. 그래도 이 컴퓨터에 Python 이 없거나, 워크스페이스를 신뢰하지
않았거나, 프로젝트 루트를 다르게 잡으면 **아무 오류 없이 조용히 무시된다.**

그 상태에서 이 워크스페이스는 겉보기에 정상 동작한다. 메일 발송 확인 창만
안 뜰 뿐이다. 그리고 그 사실은 사고가 난 뒤에야 드러난다.

그래서 훅이 실행될 때마다 `logs/.harness/` 에 흔적을 남기고, 이 스크립트가
그 흔적을 읽어 판정한다. **정적 점검(파일이 있는가)과 동적 점검(실제로
돌았는가)을 나눠서** 본다. 파일이 있어도 안 돌 수 있기 때문이다.

사용
----
    python3 scripts/verify_harness.py            # 판정
    python3 scripts/verify_harness.py --canary   # 훅을 깨우는 방법 안내
    python3 scripts/verify_harness.py --json

`/selftest` 슬래시 명령이 이 스크립트를 카나리아와 함께 돌린다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BEAT_DIR = ROOT / "logs" / ".harness"
HOOK_DIR = ROOT / ".claude" / "hooks"
SETTINGS = ROOT / ".claude" / "settings.json"

OK, WARN, FAIL, UNKNOWN = "OK", "주의", "실패", "미확인"
SYMBOL = {OK: "OK  ", WARN: "주의 ", FAIL: "실패 ", UNKNOWN: "미확인"}

# 훅 이름 → (설명, 살아 있지 않으면 잃는 것, 깨우는 방법)
HOOKS = {
    "session_start": (
        "세션 시작 시 개인화 상태 확인",
        "첫 실행 시 부트스트랩으로 유도하지 못한다. 백지 상태로 일반론을 답하게 된다",
        "새 세션을 한 번 시작한다",
    ),
    "protect_secrets": (
        "자격증명 파일 보호",
        ".env 류 파일이 덮어써질 수 있다",
        "에이전트에게 아무 파일이나 쓰게 한다",
    ),
    "keep_memory_portable": (
        "기억이 하네스 전용 저장소로 새는 것 차단",
        "본부장 기억이 특정 도구에 갇힌다. 폴더를 옮기면 사라진다",
        "에이전트에게 아무 파일이나 쓰게 한다",
    ),
}

# 세션 시작, 응답마다 도는 훅. 한 세션만 돌아도 흔적이 남는다.
ALWAYS_FIRING = {"session_start"}

STALE_SECONDS = 24 * 3600  # 하루 지난 흔적은 "이번 세션 증거"로 보지 않는다


class Result:
    def __init__(self, name, status, detail, lost="", fix=""):
        self.name, self.status, self.detail = name, status, detail
        self.lost, self.fix = lost, fix

    def as_dict(self):
        return {"항목": self.name, "상태": self.status, "상세": self.detail,
                "잃는 것": self.lost, "조치": self.fix}


# --------------------------------------------------------------------------
# 정적 점검: 파일이 제자리에 있는가
# --------------------------------------------------------------------------

def check_files():
    out = []
    if not SETTINGS.exists():
        out.append(Result("settings.json", FAIL, "없음",
                          lost="훅 등록 전부",
                          fix="스켈레톤을 다시 복사"))
        return out
    try:
        cfg = json.loads(SETTINGS.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        out.append(Result("settings.json", FAIL, "JSON 파싱 실패",
                          lost="훅 등록 전부", fix="파일 문법 확인"))
        return out

    registered = json.dumps(cfg.get("hooks", {}), ensure_ascii=False)
    for name in HOOKS:
        path = HOOK_DIR / f"{name}.py"
        if not path.exists():
            out.append(Result(f"{name}.py", FAIL, "파일 없음",
                              lost=HOOKS[name][1], fix="스켈레톤 재복사"))
        elif f"{name}.py" not in registered:
            out.append(Result(f"{name}.py", FAIL, "settings.json 에 등록 안 됨",
                              lost=HOOKS[name][1], fix="settings.json 의 hooks 절 확인"))
    if not out:
        out.append(Result("훅 파일, 등록", OK,
                          f"{len(HOOKS)}개 전부 제자리"))
    return out


def check_python_runs_hooks():
    """훅을 직접 실행해 본다. 파이썬 경로 문제를 여기서 잡는다.

    카나리아는 keep_memory_portable 로 친다. 워크스페이스 밖 쓰기는 반드시
    deny 가 나와야 하므로, 훅이 아예 안 도는 것과 구분된다.
    """
    probe = HOOK_DIR / "keep_memory_portable.py"
    if not probe.exists():
        return Result("훅 단독 실행", FAIL, "keep_memory_portable.py 없음")
    payload = json.dumps({
        "tool_name": "Write",
        "tool_input": {"file_path": str(Path.home() / "selftest_canary.md")},
    })
    try:
        proc = subprocess.run([sys.executable, str(probe)], input=payload,
                              capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.SubprocessError) as exc:
        return Result("훅 단독 실행", FAIL, f"실행 실패: {type(exc).__name__}",
                      lost="안전장치 전부",
                      fix="python3 이 PATH 에 있는지 확인")
    if '"permissionDecision": "deny"' in proc.stdout:
        return Result("훅 단독 실행", OK, "워크스페이스 밖 쓰기 카나리아에 deny 반환")
    return Result("훅 단독 실행", FAIL,
                  f"deny 가 나오지 않음 (출력 {len(proc.stdout)}자)",
                  lost="파일 쓰기 안전장치",
                  fix="keep_memory_portable.py 를 직접 실행해 오류 확인")


def check_workspace_root():
    """훅이 계산하는 프로젝트 루트가 실제 워크스페이스와 같은가.

    다른 디렉터리(멀티루트 워크스페이스 등)에서 확장이 CLI 를 띄우면
    $CLAUDE_PROJECT_DIR 이 어긋나 훅 경로가 통째로 빗나간다.
    그러면 훅은 '없는 것'이 된다.
    """
    env_root = os.environ.get("CLAUDE_PROJECT_DIR")
    if not env_root:
        return Result("프로젝트 루트", UNKNOWN,
                      "CLAUDE_PROJECT_DIR 미설정 (셸에서 직접 실행 중이면 정상)",
                      fix="에이전트 안에서 /selftest 로 다시 확인")
    if Path(env_root).resolve() == ROOT:
        return Result("프로젝트 루트", OK, str(ROOT))
    return Result("프로젝트 루트", FAIL,
                  f"불일치, 훅이 보는 곳: {env_root}",
                  lost="훅 전부 (경로가 어긋나 실행되지 않는다)",
                  fix="워크스페이스 폴더를 직접 열어 에이전트를 시작할 것")


# --------------------------------------------------------------------------
# 동적 점검: 실제로 돌았는가
# --------------------------------------------------------------------------

def read_beats():
    beats = {}
    if not BEAT_DIR.exists():
        return beats
    for f in BEAT_DIR.glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            beats[data.get("hook", f.stem)] = data
        except (OSError, json.JSONDecodeError):
            continue
    return beats


def check_beats(beats):
    """실행 흔적으로 판정한다.

    주의: **"흔적이 없다"와 "훅이 죽었다"는 다르다.** 세션을 한 번도 열지
    않은 새 워크스페이스에는 당연히 흔적이 없다. 그것을 실패로 부르면 배포
    직후마다 오경보가 나고, 오경보가 반복되면 진짜 경보도 무시된다.

    기준점은 `session_start` 다. 세션이 한 번이라도 열렸다면 이 훅은 반드시
    돌았어야 한다. 그 흔적이 있는데 다른 훅의 흔적이 없다면 그때는 진짜
    문제다: 하네스가 일부 훅 종류만 무시하고 있다는 뜻이다.
    """
    out = []
    now = int(time.time())
    session_ran = "session_start" in beats

    if not session_ran:
        out.append(Result(
            "세션 실행 이력", UNKNOWN, "이 워크스페이스에서 아직 세션을 연 적이 없음",
            fix="에이전트를 한 번 시작한 뒤 /selftest 로 다시 확인",
        ))

    for name, (desc, lost, wake) in HOOKS.items():
        beat = beats.get(name)
        if not beat:
            # 세션이 돈 적 있는데 상시 훅의 흔적이 없다 → 진짜 실패
            if session_ran and name in ALWAYS_FIRING:
                status, detail = FAIL, "세션은 돌았는데 이 훅만 실행되지 않음"
            else:
                status, detail = UNKNOWN, "아직 깨울 조건이 없었음"
            out.append(Result(f"{name} 실행", status, detail,
                              lost=lost if status == FAIL else "",
                              fix=f"깨우는 방법: {wake}"))
            continue
        age = now - int(beat.get("epoch", 0))
        if age > STALE_SECONDS:
            days = age // 86400
            out.append(Result(f"{name} 실행", WARN,
                              f"마지막 실행 {days}일 전 ({beat.get('at','')})",
                              lost="", fix="새 세션에서 다시 확인"))
        else:
            mins = age // 60
            when = "방금" if mins < 2 else f"{mins}분 전"
            out.append(Result(f"{name} 실행", OK, f"{when} 실행됨"))
    return out


def check_harness_identity():
    """어떤 하네스 위에서 도는가. 판정이 아니라 기록이 목적이다."""
    hints = []
    for var in ("CLAUDECODE", "CLAUDE_CODE_ENTRYPOINT", "TERM_PROGRAM",
                "VSCODE_PID"):
        val = os.environ.get(var)
        if val:
            hints.append(f"{var}={val}")
    cli = shutil.which("claude")
    if cli:
        hints.append(f"claude={cli}")
    if not hints:
        return Result("하네스", UNKNOWN, "식별 정보 없음 (셸에서 직접 실행 중)")
    return Result("하네스", OK, ", ".join(hints[:4]))


def check_commands():
    d = ROOT / ".claude" / "commands"
    if not d.exists():
        return Result("슬래시 명령", FAIL, "commands 폴더 없음",
                      lost="/morning-brief 등 루틴 호출",
                      fix="스켈레톤 재복사")
    n = len(list(d.glob("*.md")))
    return Result("슬래시 명령", OK,
                  f"{n}개 정의됨. 본부장이 명령어를 몰라도 되게 "
                  f"평상어로도 호출 가능 (SYSTEM.md §6)")


# --------------------------------------------------------------------------

def run_all():
    results = [check_harness_identity(), check_workspace_root()]
    results += check_files()
    results.append(check_python_runs_hooks())
    results.append(check_commands())
    results += check_beats(read_beats())
    return results


def _w(text):
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in text)


def _pad(text, target):
    return text + " " * max(0, target - _w(text))


def render(results, quiet=False):
    lines = ["", "하네스 검증: 안전장치가 실제로 동작하는가", "=" * 72]
    shown = [r for r in results if not quiet or r.status != OK]
    width = max((_w(r.name) for r in shown), default=10)
    indent = " " * (6 + width + 2)
    for r in shown:
        lines.append(f"{SYMBOL[r.status]} {_pad(r.name, width)}  {r.detail}")
        if r.lost:
            lines.append(f"{indent}└ 잃는 것: {r.lost}")
        if r.fix and r.status != OK:
            lines.append(f"{indent}└ 조치: {r.fix}")
    lines.append("=" * 72)

    n_fail = sum(1 for r in results if r.status == FAIL)
    n_warn = sum(1 for r in results if r.status == WARN)
    n_unk = sum(1 for r in results if r.status == UNKNOWN)
    lines.append(f"정상 {sum(1 for r in results if r.status == OK)}, "
                 f"주의 {n_warn}, 미확인 {n_unk}, 실패 {n_fail}")

    if n_fail:
        lines += [
            "",
            "안전장치가 동작하지 않습니다. **본부장 PC 에서 실사용을 시작하지 마십시오.**",
            "훅 없이 도는 상태는 겉보기에 정상이라 사고가 난 뒤에야 드러납니다.",
            "HARNESS.md 의 대응표를 따르십시오.",
        ]
    elif n_unk:
        lines += [
            "",
            "미확인은 아직 그 훅을 깨울 조건이 없었다는 뜻이며, 고장이 아닙니다.",
            "**에이전트 안에서 `/selftest` 를 실행해야 판정이 끝납니다.**",
            "셸에서 이 스크립트만 돌리면 세션 훅은 영원히 미확인으로 남습니다.",
        ]
    lines.append("")
    return "\n".join(lines)


CANARY_GUIDE = """
카나리아: 훅을 일부러 깨워서 확인하는 방법

에이전트에게 아래를 그대로 실행하게 하십시오. 실제 발송은 일어나지 않습니다.
존재하지 않는 주소로 보내는 명령이며, 훅이 살아 있으면 **실행 전에 확인 창이
뜨고 거기서 거절하면 됩니다.**

    python3 scripts/reply_outlook_mail.py --to selftest@example.invalid \\
        --message "하네스 카나리아: 거절해 주십시오"

판정

  확인 창이 떴다        → 훅 정상. 거절하십시오
  아무 창 없이 실행됐다  → **훅이 죽어 있습니다.** 즉시 중단하고 HARNESS.md 참조

확인 창의 등장 여부와 무관하게, 훅이 호출되기만 하면 흔적이 남습니다.
카나리아 뒤에 다시 이 스크립트를 돌리십시오.

    python3 scripts/verify_harness.py
"""



def main():
    ap = argparse.ArgumentParser(description="하네스 안전장치 검증")
    ap.add_argument("--quiet", action="store_true", help="실패, 주의, 미확인만 출력")
    ap.add_argument("--canary", action="store_true", help="훅을 깨우는 방법 안내")
    ap.add_argument("--json", action="store_true", help="JSON 출력")
    args = ap.parse_args()

    if args.canary:
        print(CANARY_GUIDE)
        return 0

    results = run_all()
    if args.json:
        print(json.dumps([r.as_dict() for r in results],
                         ensure_ascii=False, indent=2))
    else:
        print(render(results, quiet=args.quiet))
    return 1 if any(r.status == FAIL for r in results) else 0


if __name__ == "__main__":
    sys.exit(main())
