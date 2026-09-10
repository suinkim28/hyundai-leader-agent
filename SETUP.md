# SETUP.md: 설치와 사전 준비 (AX 챔피언, DEP 용)

이 문서는 **본부장이 아니라 챔피언, DEP 가 읽는다.**

원칙 하나: **세션 당일에는 설치하지 않는다.** 2시간 세션에서 환경 세팅을
시작하면 본부장이 볼 것은 진행 표시줄뿐이다. 환경, 데이터, 권한은 세션 전에
끝나 있어야 하고, 세션에서는 본부장의 지식과 선호를 넣는 일만 한다.

---

## 0. 설치 (30분)

### 0-1. 준비물

| 항목 | 확인 |
| --- | --- |
| **본부장 실제 사용 PC** (챔피언 PC 아님), Windows | 여기서 돌지 않으면 의미가 없다 |
| Python 3.11 이상 | **본부장 PC 에는 기본으로 설치돼 있지 않을 가능성이 높다.** `py --version` 으로 확인. 없으면 `winget install --id Python.Python.3.12 --scope user` 또는 python.org 설치본으로 설치하고, 설치 화면의 **Add python.exe to PATH** 를 체크한다. 설치 후 `bin/graph check` 로 재확인 |
| **VS Code** | 사내 표준 배포판 또는 code.visualstudio.com |
| **Claude Code 확장** (`anthropic.claude-code`, VS Code 마켓플레이스) | 확장이 내부적으로 Claude Code CLI 를 실행한다 |
| Node.js (무인 루틴용) | `node --version`. 없으면 `winget install OpenJS.NodeJS.LTS`. 무인 루틴을 안 쓰면 생략 |
| Claude Code CLI (무인 루틴용) | `npm install -g @anthropic-ai/claude-code` 후 `claude --version` |
| Playwright MCP | 웹 자료 조회용. **headed 모드**를 기본으로 등록. 등록 방법은 사내 절차 |
| Atlassian MCP | Confluence, Jira 조회용. 등록 방법은 사내 절차. `bin\graph.cmd check` 의 `Confluence / Jira MCP` 줄로 확인 |
| 본부장 사내 계정 로그인 상태 | Outlook, Teams 가 이 PC 에서 열리는지 |
| `pip install truststore` | **사내망(SSL 인스펙션 프록시)에서만 필요.** 안 하면 `bin/graph check` 에서 Outlook 메일, 캘린더, Teams 가 `CERTIFICATE_VERIFY_FAILED` 로 전부 실패한다 (`TODO.txt` 참고). Python 3.10 이상 필요. 프록시가 없는 망이면 안 해도 무방하다 |

### 0-2. 워크스페이스 배치

받은 스켈레톤 폴더(예: `hyundai-leader-agent-main-skeleton`)를 본부장 PC 의
작업 위치에 통째로 복사하고 이름을 바꾼다.

```powershell
Copy-Item -Recurse hyundai-leader-agent-main-skeleton "$HOME\비서"
Set-Location "$HOME\비서"
```

복사하기 전에 스켈레톤이 **비어 있는지** 확인한다: `PROFILE.md` 와 `ORG.md` 가
`templates/` 의 원본과 같고, `attachments/`, `meetings/`, `decisions/`,
`drafts/`, `briefings/`, `logs/` 에 `.gitkeep` 외의 파일이 없어야 한다.
앞선 본부장의 자료가 남아 있으면 새 본부장의 에이전트가 그 사람 기준으로
개인화를 시작한다.

**본부장 한 분당 한 폴더다.** 여러 본부장이 하나를 공유하지 않는다.
`PROFILE.md` 와 `ORG.md` 가 사람마다 다르고, 그 안에 대외비가 쌓인다.

### 0-3. 워크스페이스 신뢰 (빠뜨리기 쉬움)

복사한 폴더를 **VS Code 로 한 번 열고**(`code .` 또는 탐색기에서 폴더 열기)
신뢰 확인 대화상자(`Do you trust the authors of the files in this folder?`)에서
**Trust** 를 누른다. Claude Code 확장이 별도로 한 번 더 신뢰를 물으면 마찬가지로
동의한다.

이걸 건너뛰면 다음 경고와 함께 `.claude/settings.json` 의 허용 목록이 전부
무시되고, 조회할 때마다 확인 창이 뜬다.

```
Ignoring N permissions.allow entries from .claude/settings.json:
this workspace has not been trusted.
```

훅은 신뢰 여부와 무관하게 동작하므로 안전장치는 유지되지만, 사용성이
크게 떨어진다. **본부장에게 이 창을 보여주지 않는다**: 
챔피언이 세팅 단계에서 끝내 둔다.

### 0-4. 하네스 자가진단: **가장 중요한 단계**

VS Code + Claude Code 확장은 공식 확장이므로 `.claude/settings.json` 의 훅
등록은 표준으로 지원된다. 그래도 이 단계를 건너뛰지 않는 이유는 따로 있다:
**이 컴퓨터에 Python 이 없거나, 워크스페이스를 신뢰하지 않았거나, 프로젝트
루트가 어긋나면 훅은 오류 없이 조용히 안 돈다.** 겉보기에는 완전히 정상
동작하면서 메일 발송 확인 창만 안 뜨는 상태가 될 수 있다.

에이전트를 열고 실행한다.

```
/selftest
```

- **통과** → 다음 단계로.
- **실패** → `HARNESS.md` §3 대응표를 따른다. **본부장에게 넘기지 않는다.**

> 안전장치가 없는 것보다 나쁜 상태는 **없는데 있다고 믿는 상태**다.
> 없는 줄 알면 조심하지만, 있다고 믿으면 맡긴다.

셸에서 아래를 돌려도 되지만, 이것만으로는 세션 훅이 `미확인` 으로 남는다.
판정을 끝내려면 에이전트 안에서 `/selftest` 를 해야 한다.

```powershell
bin\graph.cmd verify
```

### 0-5. 연결 진단

```powershell
bin\graph.cmd check
```

`실패` 항목이 나오는 것은 정상이다. 이 시점에는 아직 아무것도 연결되지
않았다. 무엇이 막혀 있는지 확인하는 것이 목적이다.

### 0-6. 훅 단독 실행 확인

```powershell
'{"tool_name":"Write","tool_input":{"file_path":"~/canary.md"}}' | py -3 .claude\hooks\keep_memory_portable.py
```

`permissionDecision: deny` 가 나오면 정상이다. 아무것도 안 나오면 훅이 동작하지
않는 것이므로 Python 경로를 확인한다.

### 0-7. Graph 자격증명과 로그인

두 단계다. **앞은 챔피언이, 뒤는 본부장이** 한다.

1. **자격증명 저장 (챔피언, D-3)**: 에이전트를 열고 "설정해줘" 라고 말한 뒤,
   에이전트가 여쭙는 세 값(Client ID, Tenant ID, Client Secret)을 붙여넣는다.
   앱 등록 값이라 모든 본부장 PC 에 같은 값이 들어간다.
2. **로그인 (본부장, 세션 첫 5분 또는 D-1)**: `bin\graph.cmd login` 이 브라우저를
   띄우면 **본부장 본인의 회사 계정**으로 로그인하고 동의를 누른다. MFA 때문에
   챔피언이 대신 할 수 없다. 한 번이면 되고, 이후에는 refresh token 으로 유지된다.

세션 시작 훅은 1번(세 값)만 검사한다. 2번이 안 된 채 세션이 시작되면
부트스트랩 도중 Quick Win 에서 첫 Graph 호출이 브라우저를 띄운다. 그래서
**로그인을 세션의 첫 순서로 계획해 둔다.** 끝나면 `bin\graph.cmd check` 에서
Outlook 메일, 캘린더, Teams 가 `조회 성공` 이어야 한다. 값을 대화창에 붙여넣으면 세션 로그에 남는다는 점은 `SECURITY.md` §4.

---

## 1. D-7: 권한

- [ ] Microsoft Graph 읽기 권한 승인 완료 (`CONNECTIONS.md` §4)
- [ ] Confluence / Jira MCP 연결 및 본부장 계정 로그인
- [ ] SharePoint, OneNote 접근 범위 확인
- [ ] 토큰, 비용 상한 정책 확인

**미완이면 지금 에스컬레이션한다.** D-7에 안 된 것이 D-1에 되는 일은 없다.

동시에 **승인 없이도 성립하는 최소 시나리오를 병행 준비한다.**
승인을 기다리다가 세션 당일에 아무것도 못 보여주는 것이 최악이다
(`CONNECTIONS.md` §2).

---

## 2. D-5: 남은 결정

- [ ] STT 사용 승인 회신: 막히면 회의 관련 워크플로 2종이 사라진다
- [ ] 녹음 가능한 회의 범위 확정 → `ORG.md` §5 에 목록화

**미결이면 해당 워크플로를 세션 범위에서 빼고 본부장께 사전 고지한다.**
세션에서 "그건 안 됩니다"를 처음 말하는 것이 가장 나쁘다.

---

## 3. D-3: 데이터와 초안

### 3-1. 연결 진단 기록

```powershell
New-Item -ItemType Directory -Force -Path "logs\<오늘>" | Out-Null
bin\graph.cmd check > "logs\<오늘>\connections.txt" 2>&1
```

결과 요약을 `PROFILE.md` §3 연결 표에 옮긴다.

### 3-2. `ORG.md` 초안 작성

챔피언이 아는 것으로 채운다. **본부장의 세션 시간을 조직도 받아쓰기에 쓰지
않는다.**

- [ ] §1 본부 개요, 올해 최우선 목표
- [ ] §2 보고 라인: **경영진 계정 목록** (메일 트리아지 우선순위의 기준)
- [ ] §3 팀장급 구성원, AX 지원 인력
- [ ] §4 진행 중 과제와 마일스톤
- [ ] §5 정기 회의 + 녹음 가능 여부
- [ ] §6 실제로 쓰는 시스템만
- [ ] §7 본부 약어, 용어 → `knowledge_base/transcription_glossary.txt` 에도 한 줄에 하나씩
- [ ] 다 채웠으면 맨 위 `상태:` 를 `진행중` 으로, `최종 갱신:` 을 오늘 날짜로 바꾼다.
      **`PROFILE.md` 는 건드리지 않는다.** `상태: 미완료` 그대로여야 세션 첫 턴에
      부트스트랩이 시작된다

### 3-3. 데이터 샘플 확보

부트스트랩 1단계는 **사전자료를 먼저 읽고** 자료로 확인되지 않는 것만 여쭙는다.
자료가 없으면 에이전트가 본부장께 처음부터 묻게 된다. 반드시 미리 넣어 둔다.

- [ ] **사전설문 응답과 사전인터뷰 전사본** → `attachments/raw/`
      (파일명에 날짜와 본부명: `2026-08-28_<본부>_사전인터뷰_TRANSCRIPT.md`)
- [ ] 프로파일 카드, 정리 노트가 있으면 → `knowledge_base/`

1회차에서 Quick Win 을 **실제 데이터로** 시연하려면 아래도 있어야 한다.

- [ ] 최근 2주 메일 (미읽음 포함): 실제 상태 그대로
- [ ] 회사 캘린더 2주치
- [ ] 최근 회의 자료 1건 (첨부 문서 포함)
- [ ] 진행 중 과제 1건의 흩어진 이력 (메일, Confluence, 구두 지시)

연결이 막혔으면 본부장 동의를 받아 내보내기 파일로 대체하고
`attachments/raw/` 에 둔다.

### 3-4. 구동 확인

- [ ] **본부장 PC에서** 에이전트가 실제로 뜬다
- [ ] `/morning-brief` 를 한 번 돌려 본다. 결과가 비어도 상관없다.
      **오류 없이 끝나는지**를 본다.
- [ ] `/selftest` 재확인: 세션이 몇 번 돈 뒤이므로 이제 `미확인` 이 없어야 한다

---

## 4. D-1: 리허설

- [ ] Quick Win 1건이 **실제 본부장 데이터로** 동작한다
- [ ] 무인 루틴 등록 (선택)
      ```powershell
      .\scripts\run_routine.ps1 morning-brief
      ```
      정상 동작을 확인한 뒤 작업 스케줄러에 등록한다.
      등록 예시는 스크립트 상단 주석과 `HARNESS.md` §5 에 있다.
- [ ] 세션에서 보여줄 화면 순서를 정한다. 즉석에서 찾지 않는다.

---

## 5. 세션 당일

**하지 않는 것**

- 설치, 로그인, 연결 설정
- 조직도, 인물 정보 받아쓰기
- 기능 설명 슬라이드

**하는 것**

1. `/bootstrap`: 사전자료를 먼저 읽고, 자료로 확인되지 않는 것만 여쭙는다 (5분).
   본부장이 타이핑하지 않는다. 말씀하시면 에이전트가 적는다.
2. "없어졌으면 하는 반복 작업" 으로 답하신 것을 **그 자리에서 실행**해 보여준다.
   설명하지 말고 돌린다.
3. 결과를 보고 본부장이 "이건 이렇게 해달라"고 하시는 것을 `PROFILE.md` 에
   즉시 적는다. **이 왕복이 진짜 개인화다.** 2~3회 반복하면 목적 달성이다.
4. 마지막 5분: 자율 활용 기간에 무엇을 쓰실지 한 가지만 약속받는다.
   여러 개를 약속받으면 하나도 안 쓰신다.

**본부장이 "보고받아 판단"하는 분이면** (`BOOTSTRAP.md` Q3) 프롬프트를 직접
치게 하지 않는다. 챔피언이 실행하고 본부장은 결과를 보고 고치는 구조로
진행한다. 평소 업무 방식과 같게 만드는 것이 핵심이다.

---

## 6. 자율 활용 기간 (챔피언 역할)

에이전트는 매일 자란다. 챔피언은 **자라고 있는지**를 본다.

주 1회 확인:

```powershell
Get-ChildItem briefings\ | Sort-Object LastWriteTime -Descending | Select-Object -First 10   # 루틴이 실제로 돌고 있는가
Get-Content PROFILE.md -Tail 30                                                              # §9 누적 학습 로그가 늘고 있는가
bin\graph.cmd check --quiet
```

- 브리핑이 사흘 이상 비어 있다 → 루틴이 안 돌거나 안 읽히고 있다. 물어본다.
- `PROFILE.md` §9 가 사흘 연속 "변화 없음" → 에이전트가 안 쓰이거나 학습
  포착이 고장 났다.
- 본부장이 같은 불만을 두 번 말씀하셨다 → 규칙 문제다. `PROFILE.md` §4 에
  적어서 해결한다. 사람 힘으로 매번 고치지 않는다.

---

## 7. 2회차 준비

- [ ] `PROFILE.md` / `ORG.md` 를 인쇄해 간다. **2주 만에 얼마나 자랐는지
      보여주는 것 자체가 성과다.**
- [ ] 자율 활용 중 막힌 지점을 유형별로 정리한다: 연결 / 규칙 / 기대 불일치.
      세 가지는 해법이 완전히 다르다.
- [ ] 틀리게 학습된 항목 목록. 2회차에서 함께 지운다.
- [ ] 추가할 루틴 후보 **하나**. 여러 개를 늘리면 셋 다 안 쓰인다.

---

## 8. 자주 나오는 문제

| 증상 | 원인 | 조치 |
| --- | --- | --- |
| 세션 시작하자마자 질문만 한다 | 정상. `PROFILE.md` 가 `미완료` 상태 | `/bootstrap` 진행 |
| 조회할 때마다 확인 창이 뜬다 | 워크스페이스 미신뢰 | VS Code 신뢰 대화상자에서 Trust 선택 (§0-3) |
| 메일, 일정이 비어 있다 | Graph 미승인 또는 첫 로그인 전 | `bin\graph.cmd check`. 승인 전이면 내보내기 파일 |
| 답변에 출처가 없다 | 훅이 지적했는데 넘어갔다 | `SYSTEM.md` §3 을 다시 읽히고, 반복되면 `PROFILE.md` §4 에 규칙 추가 |
| 무인 루틴이 안 돈다 | 작업 스케줄러가 사용자 PATH 를 안 물려받아 `claude` 를 못 찾는다 | `HMG_CLAUDE_BIN` 에 경로 지정 (`HARNESS.md` §5). 로그는 `logs/YYYY-MM-DD/` |
| 훅이 하나도 안 돈다 | **Python 이 이 컴퓨터에 없다** | `py --version` 확인, 없으면 `winget install --id Python.Python.3.12 --scope user` |
| `/명령` 이 안 먹힌다 | 명령 파일 인식 지연 (드묾) | 평상어로 호출 (`SYSTEM.md` §6 대응표), VS Code 재시작 |
| 회의록에 이름이 틀린다 | 용어집 미반영 | `knowledge_base/transcription_glossary.txt` 에 고유명사 추가 |

