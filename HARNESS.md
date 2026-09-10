# HARNESS.md: 실행 환경 (VS Code + Claude Code 확장)

이 스켈레톤은 **VS Code 위에서 도는 공식 Claude Code 확장**(`anthropic.claude-code`,
Claude Code CLI 기반) 위에서 돈다. 본부장 PC 는 전부 Windows 다.

정체불명의 사내 래퍼가 아니라 Anthropic 공식 확장이므로 `.claude/settings.json` 의
훅, 권한 등록은 **표준으로 지원된다.** 그래도 배포 직후 한 번 `/selftest` 를 도는
이유는 래퍼 신뢰성 문제가 아니라 훨씬 평범한 것들이다.

- 이 컴퓨터에 **Python 이 없으면** 훅 스크립트 자체가 실행되지 않는다.
- **워크스페이스를 신뢰하지 않았으면** 권한 설정이 통째로 무시된다.
- **다른 폴더에서 확장을 열었으면**(멀티루트 워크스페이스 등) 훅이 보는 프로젝트
  루트가 어긋나 아무것도 안 읽힌다.

세 가지 모두 겉보기에는 정상 동작하면서 확인 창만 안 뜨는 상태를 만든다는 점은
같다. 그래서 검증 방식 자체는 바꾸지 않는다.

---

## 0. 가장 먼저 할 것

배포 후 **본부장이 쓰기 전에** 한 번 통과시킨다.

```
/selftest
```

훅이 하나라도 죽어 있으면 실사용을 시작하지 않는다.

---

## 1. 왜 검증이 필요한가

이 스켈레톤의 안전 설계는 전부 훅에 걸려 있다. 훅이 도는지는 대부분의 경우
VS Code + Claude Code 확장에서는 문제가 되지 않지만, 위에 적은 세 가지 로컬 조건
(Python 부재, 워크스페이스 미신뢰, 프로젝트 루트 불일치) 중 하나만 걸려도 훅은
**오류 없이** 안 돈다. 겉보기에는 완전히 정상 동작하고, 메일 발송 확인 창만 안
뜬다.

> 안전장치가 없는 것보다 나쁜 상태는 **없는데 있다고 믿는 상태**다.

없는 줄 알면 조심하지만, 있다고 믿으면 맡긴다. 그래서 훅이 실행될 때마다
`logs/.harness/` 에 흔적을 남기고, `verify_harness.py` 가 그 흔적을 읽어
판정한다. **"파일이 있는가"가 아니라 "실제로 돌았는가"를 본다.**

판정 기준점은 `session_start` 다. 세션이 한 번이라도 열렸다면 이 훅은 반드시
돌았어야 한다. 그 흔적이 있는데 다른 훅의 흔적이 없다면 그때가 진짜 문제다:
Python 경로나 프로젝트 루트 설정에 구체적인 문제가 있다는 뜻이다.

---

## 2. 확인할 것

`verify_harness.py` 로 직접 확인하거나 `/selftest` 로 확인한다.

| # | 확인 항목 | 왜 중요한가 | 확인 방법 |
| ---: | --- | --- | --- |
| 1 | **Python 3.11 이상**이 PATH 에 있는가 | 없으면 훅, `bin/graph` 전부 조용히 안 돈다 | `py --version` (Windows 에는 보통 `py` 만 있다) |
| 2 | **VS Code 가 이 폴더를 신뢰**했는가 | 미신뢰면 `permissions.allow` 가 통째로 무시된다 | 아래 §4 |
| 3 | 확장이 이 폴더를 **프로젝트 루트**로 잡는가 | 어긋나면 `CLAUDE.md`, 훅, 명령이 통째로 안 읽힌다 | `verify_harness.py` 의 `프로젝트 루트` 행 |
| 4 | `.claude/settings.json` 의 **훅 등록**이 실제로 실행되는가 | 안전장치 전부 | `/selftest` |
| 5 | `permissions.allow` 를 존중하는가 | 조회마다 확인 창이 떠서 못 쓰게 된다 | 조회를 몇 번 시켜 본다 |
| 6 | 통합 터미널이 **PowerShell 인가 Git Bash 인가** | 무인 실행, 스크립트 호출 표기가 다르다 | VS Code 하단 터미널 드롭다운 |
| 7 | **MCP 설정**을 어디서 읽는가 (`.mcp.json` 또는 `claude mcp add` 등록) | Confluence, Jira 연결 | `claude mcp list` |
| 8 | **헤드리스 실행**(`claude -p`)이 가능한가, CLI 바이너리 경로는 어디인가 | 06:00, 08:00, 17:00 무인 루틴 | 아래 §5 |
| 9 | 대화 기록 **저장 위치와 보존 기간** | 감사 로그 정책 (`SECURITY.md` §8) | VS Code / Claude Code 확장 설정 |

1~4 는 **막히면 대안이 없다.** 5~9 는 대안이 있다.

---

## 3. 깨졌을 때 대응표

`verify_harness.py` 가 실패로 잡은 항목마다 여기서 행을 찾는다.

| 증상 | 원인 | 조치 |
| --- | --- | --- |
| 훅 파일은 있는데 **실행 흔적 없음**, 오류 메시지도 없음 | Python 이 PATH 에 없다 | `py --version` 확인. 없으면 python.org 설치본 또는 `winget install Python.Python.3.12` 로 설치 후 VS Code 재시작 |
| `프로젝트 루트` 불일치 | 이 폴더가 아니라 상위/다른 폴더를 열었다 (멀티루트 워크스페이스 포함) | VS Code 에서 `파일 → 폴더 열기` 로 이 폴더 자체를 단일 루트로 다시 연다 |
| 조회마다 확인 창 | 워크스페이스 미신뢰 | §4 |
| `session_start` 만 안 됨 | 세션이 아직 한 번도 열리지 않았다 | 새 대화창을 한 번 시작한 뒤 재확인 |
| `keep_memory_portable` 안 됨 | Python 미설치, 또는 `.claude/hooks/run` 실행 권한 문제 | `.claude/hooks/run keep_memory_portable.py` 를 직접 호출해 오류 메시지 확인 |
| `protect_secrets` 안 됨 | 위와 동일 | 위와 동일. **가장 심각하므로** 원인을 못 찾으면 §6 축소 운영으로 전환 |
| `/morning-brief` 가 안 먹힘 | 명령 파일 인식 지연 (드물게 발생) | 평상어로 호출한다 (§7). VS Code 재시작으로도 대개 해결된다 |
| 무인 루틴이 안 돎 | `claude` 가 작업 스케줄러의 PATH 에 없음 | §5 |

---

## 4. 워크스페이스 신뢰

VS Code 는 처음 보는 폴더를 열면 **"Do you trust the authors of the files in this
folder?"** 대화상자를 띄운다. **Trust** 를 눌러야 `.claude/settings.json` 의
권한, 훅 설정이 적용된다. Claude Code 확장도 별도로 한 번 더 신뢰를 물을 수 있다.

신뢰하지 않으면 CLI 쪽에서도 다음과 같은 경고가 남는다.

```
Ignoring 25 permissions.allow entries from .claude/settings.json:
this workspace has not been trusted.
```

**훅은 워크스페이스 신뢰와 무관하게 동작하므로 안전장치는 유지된다.** 잃는 것은
사용성이다. 조회할 때마다 확인 창이 떠서 `paranoid` 등급처럼 느껴진다.

해소 방법:

1. VS Code 로 이 폴더를 열 때 뜨는 신뢰 대화상자에서 **Trust** 를 선택한다.
2. 이미 미신뢰로 넘어갔다면, 명령 팔레트(`Ctrl+Shift+P`) → `Workspaces: Manage
   Workspace Trust` 에서 다시 신뢰를 부여한다.
3. Claude Code CLI 자체의 신뢰 상태는 `~/.claude.json` 의 해당 경로에
   `hasTrustDialogAccepted: true` 로도 확인할 수 있다.

**본부장에게 신뢰 확인 창을 보여주지 않는다**: 챔피언이 세팅 단계에서 끝내 둔다.

---

## 5. 무인 루틴 (06:00, 08:00, 17:00)

무인 실행은 VS Code 가 아니라 **Claude Code CLI 를 직접 호출**한다. CLI 는 보통
npm 전역 설치(`%APPDATA%\npm\claude.cmd`)라 사용자 PATH 에 있지만, **작업
스케줄러는 사용자 PATH 를 물려받지 않을 수 있다.** 그럴 때는 경로를 지정한다.

Windows (1순위):

```powershell
$env:HMG_CLAUDE_BIN = "$env:APPDATA\npm\claude.cmd"
.\scripts\run_routine.ps1 morning-brief
```

작업 스케줄러 등록 예 (평일 08:00, 관리자 PowerShell):

```powershell
$a = New-ScheduledTaskAction -Execute "powershell.exe" `
       -Argument "-NoProfile -ExecutionPolicy Bypass -File C:\<워크스페이스>\scripts\run_routine.ps1 morning-brief"
$t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Mon,Tue,Wed,Thu,Fri -At 08:00
Register-ScheduledTask -TaskName "HMG-Agent-MorningBrief" -Action $a -Trigger $t
```

`run_routine.ps1` 은 `HMG_CLAUDE_BIN` → PATH → 흔한 설치 위치(npm 전역, VS Code
확장 번들 경로) 순으로 찾는다. 찾지 못하면 어디를 뒤졌는지 로그에 남기고 멈춘다.

macOS/Linux (참고):

```bash
export HMG_CLAUDE_BIN="$(npm config get prefix)/bin/claude"
./scripts/run_routine.sh morning-brief
```

**헤드리스 실행이 아예 불가능하면** 무인 루틴을 포기하고, 본부장이 아침에
`/morning-brief` 를 한 번 누르는 방식으로 바꾼다. 루틴 자체는 그대로 동작한다.
잃는 것은 자동 실행이지 기능이 아니다.

---

## 6. 훅이 죽었을 때의 축소 운영

발송 확인 게이트는 2026-09-10 에 제거했다. 되돌릴 수 없는 발송을 막아야
하는 본부장이라면, 안전장치를 **문서가 아니라 파일 배치로** 만든다.

```powershell
New-Item -ItemType Directory -Force -Path _disabled | Out-Null
Move-Item scripts\reply_outlook_mail.py, scripts\send_teams_reply.py, `
  scripts\post_teams_channel_message.py, scripts\create_outlook_event.py, `
  scripts\delete_outlook_event.py -Destination _disabled -ErrorAction SilentlyContinue
```

에이전트가 부를 수 있는 발송 수단이 물리적으로 사라진다. 초안은 `drafts/` 에
그대로 쌓이고, 본부장이 직접 복사해 보내신다.

**규칙으로 막는 것과 도구를 없애는 것은 다르다.** 훅이 없는 상태에서 규칙만
믿는 것은 안전장치가 아니다. 근본 원인(대개 Python 미설치)을 고치는 것이
우선이며, 이 조치는 그 전까지의 임시 조치다.

---

## 7. 슬래시 명령과 평상어 호출

VS Code + Claude Code 확장은 `/` 로 시작하는 슬래시 명령을 표준으로 지원한다.
정체불명 래퍼가 `/` 입력을 가로채 다른 UI 로 보내는 위험은 이 하네스에는
없다. 그럼에도 평상어 호출표(`SYSTEM.md` §6, `ROUTINES.md`)를 그대로 두는
이유는 다르다: **본부장이 명령어 이름을 외울 필요가 없어야 한다.**

| 평상어 | 루틴 |
| --- | --- |
| "오늘 뭐 있지?" / "아침 브리핑" | R2 아침 브리핑 |
| "오늘 시장 어때?" | R1 시장 브리핑 |
| "10시 회의 준비해줘" | R3 회의 준비 |
| "이거 답장 좀 써줘" | R4 초안 작성 |
| "이 보고서 검토해줘" | R5 결재 검토 |
| "그 과제 어디까지 됐지?" | R6 과제 추적 |
| "회의 정리해줘" | R7 회의 정리 |
| "오늘 정리해줘" | R8 회고 |
| "비서 역할 해줘" (최초) | 부트스트랩 |

**본부장에게는 이쪽이 원래 더 자연스럽다.** 슬래시 명령은 챔피언용 지름길로
보는 편이 낫다.

---

## 8. 하네스를 또 바꿀 때

지금의 기본 하네스는 **VS Code + Claude Code 확장**이다. 사내에서 다른 실행
도구를 표준으로 정하는 상황에 대비해, 이 스켈레톤은 하네스 종속과 비종속을
처음부터 나눠 두었다.

| 그대로 옮겨지는 것 | 하네스 종속 |
| --- | --- |
| `SYSTEM.md` `PROFILE.md` `ORG.md` `ROUTINES.md` `BOOTSTRAP.md` `CONNECTIONS.md` `SECURITY.md` | `.claude/settings.json` (훅, 권한 등록 형식) |
| `scripts/` 전부 (표준 라이브러리만 씀) | `.claude/commands/` (슬래시 명령 형식) |
| `templates/` `knowledge_base/` 및 모든 산출물 | `.claude/hooks/` 의 **입출력 규약** (스크립트 로직은 유지) |

하네스를 바꾸면 오른쪽 열만 다시 쓴다. 왼쪽은 손대지 않는다.
그리고 새 하네스에서 다시 `/selftest` 를 통과시킨다.

이 워크스페이스는 **git 을 쓰지 않는다.** 배포는 폴더 통째 복사(§0-2)로 하고,
버전 관리나 커밋 이력에 기억을 의존하지 않는다. 장기기억은 오직 이 폴더 안의
마크다운 파일에만 있다는 원칙(`SYSTEM.md` §8)과 같은 이유다: git 이력도
이 폴더를 다른 PC 로 옮기면 통째로 사라지거나 꼬일 수 있는 하네스 종속물이다.

---

## 9. PATH 가 깨진 셸: `ls`, `cp` 조차 안 먹힐 때

일부 사내 PC(특히 DLP/보안 에이전트가 깔린 잠금 PC)에서는 에이전트의 Bash 도구가
**Windows 형식 PATH(세미콜론 구분, `C:\...`)를 변환 없이 그대로** 물려받는다.
Git Bash 는 원래 로그인 셸을 통해 PATH 를 POSIX 형식(콜론 구분, `/usr/bin` 포함)
으로 바꿔 주는데, 이 변환이 빠지면 bash 의 명령 탐색기가 세미콜론을 경로
구분자로 인식하지 못해 **사실상 아무 명령도 못 찾는다.** `ls`, `cp`, `mkdir`,
`grep`, `find` 는 물론 `node`, `npm`, `claude` 같은 실제로 설치된 명령까지
전부 `command not found` 가 뜬다.

**확인 방법**

```bash
echo $PATH
```

세미콜론(`;`)과 `C:\` 형식이 보이면 이 증상이다. 정상이라면 콜론(`:`)과
`/c/...` 형식이어야 한다.

**대응**

1. **가능하면 셸 명령 대신 에이전트 전용 도구를 쓴다.** 파일 읽기/쓰기/검색은
   Bash 의 `cat`/`cp`/`grep`/`find` 가 아니라 에이전트의 Read/Write/Edit/Glob/Grep
   도구로 한다. 이 도구들은 PATH 에 의존하지 않으므로 이 증상의 영향을 받지 않는다.
2. **Bash 가 꼭 필요하면 전체 경로(POSIX 스타일)로 부른다.** 흔한 위치:

   | 명령 | 흔한 전체 경로 |
   | --- | --- |
   | `ls`, `cp`, `mkdir`, `grep`, `find`, `cat` | `/usr/bin/<명령>` (Git Bash 내장 coreutils) |
   | `node` | `/c/Program Files/nodejs/node.exe` |
   | `npm` | `/c/Program Files/nodejs/npm.cmd` |
   | `claude` (전역 설치 시) | `/c/Users/<계정>/AppData/Roaming/npm/claude.cmd` |
   | `python`/`py` (설치 위치에 따라 다름) | `py --version` 이 안 되면 `/c/Users/<계정>/AppData/Local/Programs/Python/Python3xx/python.exe` 확인 |
   | `powershell` | `/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe` |

3. **PowerShell 이 꼭 필요하면 전체 경로로 부르고 `-NoProfile` 을 붙인다.**

   ```bash
   /c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe -NoProfile -Command "Get-ChildItem"
   ```

4. `bin/graph`, `.claude/hooks/run` 은 이미 `python3`/`py`/`python` 을 순서대로
   찾도록 설계돼 있지만(§2 참고), 그 탐색 자체도 이 PATH 증상이 있으면 실패
   한다. 이 증상이 의심되면 **먼저 `echo $PATH` 로 확인**하고, 세미콜론이
   보이면 위 표의 전체 경로 방식으로 직접 호출해 진단한다.

이 항목은 이 스켈레톤이 만든 문제가 아니라 **PC 환경이 Bash 도구에 넘기는
PATH 형식의 문제**다. 문서나 훅을 고쳐서 해결할 수 없고, 매 명령을 전체
경로로 부르거나 전용 도구를 쓰는 것으로 우회한다.
