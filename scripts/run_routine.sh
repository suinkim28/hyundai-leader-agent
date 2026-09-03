#!/usr/bin/env bash
# 무인 루틴 실행 (macOS / Linux)
#
# 사람이 화면 앞에 없는 상태로 돈다. 확인이 필요한 행동은 시도하지 않는다
# (SECURITY.md §7). 조회하고 파일로 남기는 것까지만 한다.
#
#   ./scripts/run_routine.sh morning-brief
#   ./scripts/run_routine.sh market-brief
#   ./scripts/run_routine.sh day-end
#
# CLI 경로
# --------
# 무인 실행은 래퍼 UI 가 아니라 CLI 를 직접 부른다. H Code Desktop 같은
# 래퍼가 CLI 를 번들로 갖고 있으면 PATH 에 없을 수 있으므로 다음 순서로
# 찾는다: $HMG_CLAUDE_BIN → PATH → 흔한 설치 위치.
#
#   export HMG_CLAUDE_BIN="/Applications/H Code Desktop.app/Contents/Resources/claude"
#
# launchd 등록 예 (평일 08:00):
#   ~/Library/LaunchAgents/com.hmg.agent.morning.plist 에
#   ProgramArguments = [<워크스페이스>/scripts/run_routine.sh, morning-brief]
#   StartCalendarInterval = { Hour = 8, Minute = 0 }
#   EnvironmentVariables 에 HMG_CLAUDE_BIN 을 함께 넣을 것.
#   launchd 는 로그인 셸 PATH 를 물려받지 않는다.

set -uo pipefail

ROUTINE="${1:-}"
if [ -z "$ROUTINE" ]; then
  echo "사용법: $0 <morning-brief|market-brief|day-end|...>" >&2
  exit 2
fi

WORKSPACE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$WORKSPACE" || exit 1

TODAY="$(date +%F)"
LOGDIR="$WORKSPACE/logs/$TODAY"
mkdir -p "$LOGDIR"
LOGFILE="$LOGDIR/${ROUTINE}.log"

# --- CLI 찾기 -------------------------------------------------------------
CANDIDATES=(
  "${HMG_CLAUDE_BIN:-}"
  "$(command -v claude 2>/dev/null || true)"
  "$HOME/.local/bin/claude"
  "/usr/local/bin/claude"
  "/opt/homebrew/bin/claude"
  "/Applications/H Code Desktop.app/Contents/Resources/claude"
  "/Applications/H Code Desktop.app/Contents/MacOS/claude"
)

CLAUDE_BIN=""
TRIED=""
for c in "${CANDIDATES[@]}"; do
  [ -z "$c" ] && continue
  TRIED="$TRIED
  - $c"
  if [ -x "$c" ]; then CLAUDE_BIN="$c"; break; fi
done

if [ -z "$CLAUDE_BIN" ]; then
  {
    echo "[$(date '+%F %T')] Claude Code CLI 를 찾지 못했습니다."
    echo "다음 위치를 확인했습니다:$TRIED"
    echo ""
    echo "래퍼가 CLI 를 번들로 갖고 있다면 경로를 지정하십시오:"
    echo '  export HMG_CLAUDE_BIN="/경로/claude"'
    echo "자세한 내용은 HARNESS.md §5 참조."
  } | tee -a "$LOGFILE" >&2
  exit 1
fi

{
  echo "===================================================="
  echo "[$(date '+%F %T %Z')] 루틴 시작: /$ROUTINE"
  echo "CLI: $CLAUDE_BIN"
  echo "===================================================="
} >> "$LOGFILE"

# --permission-mode acceptEdits: 파일 저장은 통과시키되, 발송·변경은
# guard_external_actions.py 훅이 여전히 잡는다. 무인 실행에서 훅이 확인을
# 요구하면 그 도구 호출은 거부되고 루틴은 나머지를 계속한다.
"$CLAUDE_BIN" -p "/$ROUTINE" \
  --permission-mode acceptEdits \
  < /dev/null >> "$LOGFILE" 2>&1
STATUS=$?

{
  echo ""
  echo "[$(date '+%F %T')] 종료 코드 $STATUS"
} >> "$LOGFILE"

if [ $STATUS -ne 0 ]; then
  echo "루틴 /$ROUTINE 실패 (코드 $STATUS). 로그: $LOGFILE" >&2
fi

exit $STATUS
