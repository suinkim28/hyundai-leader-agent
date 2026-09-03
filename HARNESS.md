# HARNESS.md: 실행 환경 (H Code Desktop)

이 스켈레톤은 **Claude Code CLI 를 감싼 H Code Desktop** 위에서 돈다.

래퍼는 좋은 선택이다. ICT 검토에서 1안(HChat 데스크탑 앱)은 임원 친화적이지만
Agent 실행 기반이 미확인이었고, 3안(VS Code + Claude Code)은 검증됐지만 임원
UI 가 낯설다는 것이 문제였다. CLI 래퍼는 **실행 기반은 3안, 화면은 1안**이다.

대신 **래퍼가 CLI 의 무엇을 그대로 넘겨주는지 밖에서 알 수 없다**는 문제가
새로 생긴다. 이 문서는 그 문제를 다룬다.

---

## 0. 가장 먼저 할 것

배포 후 **본부장이 쓰기 전에** 한 번 통과시킨다.

```
/selftest
```

훅이 하나라도 죽어 있으면 실사용을 시작하지 않는다.

---

## 1. 왜 검증이 필요한가

이 스켈레톤의 안전 설계는 전부 훅에 걸려 있다. 그런데 훅이 무시될 때
**오류가 나지 않는다.** 겉보기에는 완전히 정상 동작하고, 메일 발송 확인 창만
안 뜬다.

> 안전장치가 없는 것보다 나쁜 상태는 **없는데 있다고 믿는 상태**다.

없는 줄 알면 조심하지만, 있다고 믿으면 맡긴다. 그래서 훅이 실행될 때마다
`logs/.harness/` 에 흔적을 남기고, `verify_harness.py` 가 그 흔적을 읽어
판정한다. **"파일이 있는가"가 아니라 "실제로 돌았는가"를 본다.**

판정 기준점은 `session_start` 다. 세션이 한 번이라도 열렸다면 이 훅은 반드시
돌았어야 한다. 그 흔적이 있는데 다른 훅의 흔적이 없다면 그때가 진짜 문제다: 
하네스가 특정 훅 종류만 무시하고 있다는 뜻이다.

---

## 2. 래퍼에서 확인할 것

H Code Desktop 담당자에게 확인하거나, `/selftest` 로 직접 확인한다.

| # | 확인 항목 | 왜 중요한가 | 확인 방법 |
| ---: | --- | --- | --- |
| 1 | **프로젝트 루트** 를 워크스페이스 폴더로 잡는가 | 어긋나면 `CLAUDE.md`, 훅, 명령이 통째로 안 읽힌다 | `verify_harness.py` 의 `프로젝트 루트` 행 |
| 2 | `.claude/settings.json` 의 **훅 등록**을 존중하는가 | 안전장치 전부 | `/selftest` |
| 3 | `permissions.allow` 를 존중하는가 | 조회마다 확인 창이 떠서 못 쓰게 된다 | 조회를 몇 번 시켜 본다 |
| 4 | **워크스페이스 신뢰** 를 어떻게 처리하는가 | 미신뢰면 allow 25개가 통째로 무시된다 | 아래 §4 |
| 5 | **Bash 도구**를 쓸 수 있는가 | `scripts/` 전부가 여기 의존한다 | 조회 스크립트를 한 번 돌려 본다 |
| 6 | **슬래시 명령**(`/`)을 CLI 로 넘기는가, 자체 UI 가 가로채는가 | 루틴 호출 경로 | `/morning-brief` 입력 |
| 7 | **MCP 설정**을 어디서 읽는가 (`.mcp.json` / 래퍼 자체 레지스트리) | Confluence, Jira 연결 | `claude mcp list` 또는 래퍼 설정 화면 |
| 8 | **헤드리스 실행**(`claude -p`)이 가능한가, CLI 바이너리 경로는 어디인가 | 06:00, 08:00, 17:00 무인 루틴 | 아래 §5 |
| 9 | 대화 기록 **저장 위치와 보존 기간** | 감사 로그 정책 (`SECURITY.md` §8) | 래퍼 문서 |

1~5 는 **막히면 대안이 없다.** 6~9 는 대안이 있다.

---

## 3. 깨졌을 때 대응표

`verify_harness.py` 가 실패로 잡은 항목마다 여기서 행을 찾는다.

| 증상 | 원인 | 조치 |
| --- | --- | --- |
| `프로젝트 루트` 불일치 | 래퍼가 다른 디렉터리에서 CLI 를 띄움 | 워크스페이스 폴더를 직접 열어 시작. 안 되면 래퍼 담당자에게 작업 폴더 지정 방법 확인 |
| 훅 파일은 있는데 **실행 흔적 없음** | 래퍼가 훅을 지원하지 않거나 자체 설정으로 덮어씀 | **실사용 중단.** §6 축소 운영으로 전환하고 래퍼 담당자에게 에스컬레이션 |
| `session_start` 만 안 됨 | 래퍼가 SessionStart 이벤트를 안 넘김 | 부트스트랩을 `/bootstrap` 수동 호출로 대체. `SETUP.md` §5 에 챔피언이 직접 챙기도록 명시 |
| `guard_external_actions` 안 됨 | PreToolUse 미지원 | **가장 심각.** 발송, 변경 스크립트를 `scripts/` 밖으로 빼서 물리적으로 못 부르게 한다. 초안까지만 운영 |
| `protect_secrets` 안 됨 | PreToolUse 미지원 | 자격증명을 워크스페이스 밖(OS 저장소)에만 두면 노출면이 줄어든다. 이미 그렇게 설계돼 있다 |
| 조회마다 확인 창 | 워크스페이스 미신뢰 또는 `permissions.allow` 미지원 | §4 |
| `/morning-brief` 가 안 먹힘 | 래퍼가 `/` 를 가로챔 | 평상어로 호출한다 (§7) |
| 무인 루틴이 안 돎 | `claude` 가 PATH 에 없음 | §5 |

---

## 4. 워크스페이스 신뢰

CLI 는 처음 보는 폴더의 `settings.json` 을 신뢰 확인 전까지 무시한다.

```
Ignoring 25 permissions.allow entries from .claude/settings.json:
this workspace has not been trusted.
```

**훅은 신뢰와 무관하게 동작하므로 안전장치는 유지된다.** 잃는 것은 사용성이다.
조회할 때마다 확인 창이 떠서 `paranoid` 등급처럼 느껴진다.

해소 방법 두 가지.

1. 그 폴더에서 CLI 를 한 번 대화형으로 실행하고 신뢰에 동의한다.
2. `~/.claude.json` 의 해당 경로에 `hasTrustDialogAccepted: true` 를 넣는다.

래퍼가 자체 신뢰 흐름을 갖고 있으면 그것을 따른다. **본부장에게 신뢰 확인
창을 보여주지 않는다**: 챔피언이 세팅 단계에서 끝내 둔다.

---

## 5. 무인 루틴 (06:00, 08:00, 17:00)

무인 실행은 래퍼 UI 가 아니라 **CLI 를 직접 호출**한다. 래퍼가 CLI 를 번들로
갖고 있으면 PATH 에 없을 수 있으므로 경로를 지정한다.

```bash
export HMG_CLAUDE_BIN="/Applications/H Code Desktop.app/Contents/Resources/claude"
./scripts/run_routine.sh morning-brief
```

Windows:

```powershell
$env:HMG_CLAUDE_BIN = "C:\Program Files\H Code Desktop\resources\claude.exe"
.\scripts\run_routine.ps1 morning-brief
```

`run_routine` 은 `HMG_CLAUDE_BIN` → PATH → 흔한 설치 위치 순으로 찾는다.
찾지 못하면 어디를 뒤졌는지 로그에 남기고 멈춘다.

**헤드리스 실행이 아예 불가능하면** 무인 루틴을 포기하고, 본부장이 아침에
`/morning-brief` 를 한 번 누르는 방식으로 바꾼다. 루틴 자체는 그대로 동작한다.
잃는 것은 자동 실행이지 기능이 아니다.

---

## 6. 훅이 죽었을 때의 축소 운영

`guard_external_actions` 가 동작하지 않는 것이 확인되면, 안전장치를 **문서가
아니라 파일 배치로** 만든다.

```bash
mkdir -p _disabled
mv scripts/reply_outlook_mail.py scripts/send_teams_reply.py \
   scripts/post_teams_channel_message.py scripts/create_outlook_event.py \
   scripts/delete_outlook_event.py _disabled/ 2>/dev/null
```

에이전트가 부를 수 있는 발송 수단이 물리적으로 사라진다. 초안은 `drafts/` 에
그대로 쌓이고, 본부장이 직접 복사해 보내신다.

**규칙으로 막는 것과 도구를 없애는 것은 다르다.** 훅이 없는 상태에서 규칙만
믿는 것은 안전장치가 아니다.

---

## 7. 슬래시 명령이 안 먹힐 때

래퍼가 `/` 입력을 자체 UI 로 가로채면 `.claude/commands/` 가 안 쓰인다.
그 경우 **평상어로 호출한다.** `SYSTEM.md` §6 에 대응표가 있고, 에이전트는
그 표를 보고 `ROUTINES.md` 의 해당 절을 실행한다.

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

이 스켈레톤은 하네스 종속과 비종속을 처음부터 나눠 두었다.

| 그대로 옮겨지는 것 | 하네스 종속 |
| --- | --- |
| `SYSTEM.md` `PROFILE.md` `ORG.md` `ROUTINES.md` `BOOTSTRAP.md` `CONNECTIONS.md` `SECURITY.md` | `.claude/settings.json` (훅, 권한 등록 형식) |
| `scripts/` 전부 (표준 라이브러리만 씀) | `.claude/commands/` (슬래시 명령 형식) |
| `templates/` `knowledge_base/` 및 모든 산출물 | `.claude/hooks/` 의 **입출력 규약** (스크립트 로직은 유지) |

하네스를 바꾸면 오른쪽 열만 다시 쓴다. 왼쪽은 손대지 않는다.
그리고 새 하네스에서 다시 `/selftest` 를 통과시킨다.
