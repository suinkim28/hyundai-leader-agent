# CONNECTIONS.md: 연결 설정과 대체 경로

## 0. 명령을 어떻게 부르는가

Graph 조회와 발송은 전부 `bin/graph` 하나로 부른다. **macOS 와 Windows 가
같다.**

    bin/graph mail --unread --top 30
    bin/graph check

`bin/graph` 는 셸 스크립트이며 `python3`, `py -3`, `python` 순으로 찾아
`bin/graph.py` 를 실행한다. Windows 의 python.org 설치본은 `python3` 를
만들지 않기 때문에, 문서에 `python3` 를 적어두면 본부장 PC 에서 아무것도
실행되지 않는다.

| 부르는 곳 | 명령 |
| --- | --- |
| 에이전트, Git Bash, 터미널 | `bin/graph mail --unread` |
| cmd, PowerShell | `bin\graph.cmd mail --unread` |

Python 자체가 없으면 무엇도 돌지 않는다. python.org 에서 3.11 이상을 설치하고
설치 화면의 **Add python.exe to PATH** 를 체크한다. `bin/graph check` 가
확인해 준다.


## 0. 무엇이 없어도 되는가

| 연결 | 없으면 잃는 것 | 그래도 되는 것 |
| --- | --- | --- |
| 없음 (완전 오프라인) | 자동 조회 전부 | 회의록, 회고, 의사결정 이력, 과제 추적, 문서 검토 |
| + 로컬 파일만 | 실시간성 | 위 + 내보낸 메일/일정 분석, 첨부 보고자료 검토 |
| + Confluence/Jira | | 위 + 사내 지식 검색, 과제 자동 추적 |
| + Microsoft Graph | | 위 + 아침 브리핑, 메일 트리아지, 회의 준비 자동화 |
| + STT | | 위 + 회의 녹음 → 회의록 자동 생성 |
| + 외부 웹 | | 위 + 시장 동향, 법규, 경쟁사 조사 |

**1회차 세션은 첫 줄(완전 오프라인)로도 성립하도록 준비한다.** 승인을
기다리다가 세션 당일에 아무것도 못 보여주는 것이 최악이다.

---

## 1. 실행 환경

| 항목 | 내용 |
| --- | --- |
| 위치 | 본부장 실제 사용 PC |
| 하네스 | **H Code Desktop**: Claude Code CLI 를 감싼 사내 데스크탑 앱 |
| 초기 세팅 | AX 챔피언 / DEP 가 대행. 본부장이 설치 화면을 볼 일이 없어야 한다 |
| 모델 | 에이전트에 기본 장착된 Claude 모델 |
| 저장 | 공유 가능 정보는 Confluence, 민감정보는 개인 PC `.md` |

**하네스는 교체 가능하도록 설계했다.** 이 워크스페이스의 규칙은 전부 마크다운
파일에 있고 도구 호출은 `scripts/` 의 파이썬으로 분리돼 있다. 사내에서 다른
실행 도구를 표준으로 정하면 파일을 그대로 옮기면 된다.

다만 래퍼 위에서는 훅과 권한 설정이 그대로 존중되는지 **밖에서 알 수 없다.**
무시되더라도 오류가 나지 않으므로, 배포 후 본부장이 쓰기 전에 `/selftest` 를
한 번 통과시킨다. 자세한 것은 `HARNESS.md`.

**세션 당일에 설치하지 않는다.** 2시간짜리 세션에서 환경 세팅을 시작하면
본부장이 볼 것은 진행 표시줄뿐이다.

---

## 2. Microsoft Graph (메일, 일정, Teams)

### 필요한 권한 (위임 / Delegated)

전체 명세와 근거는 `output/MS_Graph_권한요청_2026-09-01.md`.
여기에는 **1단계 최소 구성 9개**만 적는다. 이것만으로 1회차 세션이 성립한다.

| 권한 | 쓰는 곳 |
| --- | --- |
| `User.Read` | 로그인, 본인 프로필 |
| `offline_access` | 토큰 갱신. **없으면 무인 루틴이 아예 안 돈다** |
| `User.Read.All` | 발신자 **직급, 부서**: 메일 트리아지의 전제 |
| `Mail.ReadWrite` | 메일 조회, 검색, **초안 저장**, 이동, 삭제 |
| `Calendars.ReadWrite` | 일정 조회, 등록, 수정, 삭제 |
| `Chat.Read` | DM, 그룹챗 읽기 및 검색 |
| `ChannelMessage.Read.All` | 채널 메시지 읽기 및 검색 |
| `Files.ReadWrite` | 내 OneDrive |
| `Sites.Read.All` | 본부 SharePoint 보고자료 |

2단계(발송, 타인 캘린더, Teams 링크 해석)와 3단계는 요청서 §7 참조.

**`Mail.ReadWrite` 는 발송 권한이 아니다.** 초안을 본부장 초안함에 저장하는
것까지이며, 발송에는 `Mail.Send` 가 따로 필요하다. 초안까지만으로도 회신
초안 작성(R4)은 완전히 동작한다.

발송 권한을 받더라도 **자동 발송은 하지 않는다.** 훅이 발송 API 호출 직전에
멈춰 대상과 본문 전문을 보여주고, 본부장이 승인해야 나간다.

**응용프로그램(Application) 권한은 요청하지 않는다.** 테넌트 전체 사서함
접근은 이 과정의 범위가 아니다.

### 등록 절차

1. 사내 ICT 승인 후 Entra 앱 등록 정보(클라이언트 ID / 테넌트 ID /
   클라이언트 시크릿)를 받는다.
2. **파일에 적지 말고** OS 자격증명 저장소에 넣는다.

   macOS:
   ```bash
   security add-generic-password -U -a "$USER" -s hmg-agent-graph-client-id -w
   security add-generic-password -U -a "$USER" -s hmg-agent-graph-tenant-id -w
   security add-generic-password -U -a "$USER" -s hmg-agent-graph-client-secret -w
   ```

   Windows / Linux: `~/.config/hmg-agent/secrets.json` 에 넣고 파일 권한을
   본인만 읽도록 제한한다.
   ```json
   {
     "hmg-agent-graph-client-id": "...",
     "hmg-agent-graph-tenant-id": "...",
     "hmg-agent-graph-client-secret": "..."
   }
   ```

3. 첫 로그인을 한 번 수행한다. 이후 refresh token 이 자동 갱신된다.
   ```bash
   bin/graph mail --top 1
   ```

### 확인

```bash
bin/graph calendar --date <오늘> --days 1
bin/graph mail --search "키워드" --top 10
```

### 승인 전 대체 경로

| 대신 | 방법 |
| --- | --- |
| 메일 | Outlook에서 해당 메일을 `.msg` 로 저장 → `attachments/raw/` |
| 일정 | Outlook 캘린더를 `.ics` 로 내보내기 → `attachments/raw/` |
| Teams | 대화를 복사해 붙여넣기 |

내보낸 파일로도 트리아지, 스레드 병합, 일정 브리핑은 그대로 동작한다.
잃는 것은 **자동 갱신**이지 기능이 아니다.

---

## 3. Confluence / Jira (Atlassian MCP)

```bash
claude mcp add --transport sse atlassian https://mcp.atlassian.com/v1/sse
claude mcp list          # 연결 상태 확인
```

첫 사용 시 브라우저 로그인이 뜬다. 본부장 계정으로 로그인한다.

**조회는 확인 없이 통과하고, 페이지 생성, 수정과 이슈 변경은 훅이 되묻는다.**
본부 지식베이스 자동 갱신은 위험도가 높으므로 2회차 전까지는 초안 제안까지만
한다.

승인 전 대체: 필요한 문서를 웹에서 복사해 `knowledge_base/` 에 저장한다.

---

## 4. 문서 DRM

**이것이 가장 자주 막히고, 막히면 가장 아프다.** 본부장 보고는 대부분 PPT
첨부이고, DRM이 걸린 문서는 에이전트가 아예 열 수 없다.

요청할 것은 **읽기 전용 목적의 일시적, 제한적 해제**다. 문서를 반출하는 것이
아니라 본부장 PC 안에서 요약, 검증하기 위한 것임을 명확히 한다.

막혔을 때:

1. `[미확보: DRM]` 으로 표시한다. **추측해서 채우지 않는다.**
2. 본부장이 화면에 띄운 내용을 구술하시면 그것으로 검토한다.
3. 해제본이 있으면 `attachments/raw/` 에 두면 읽는다.

---

## 5. 음성 전사 (STT)

```bash
security add-generic-password -U -a "$USER" -s hmg-agent-openai-api-key -w
bin/graph transcribe <오디오> --output meetings/transcripts/...
```

사내 정책상 음성이 외부로 나갈 수 없으면 **폐쇄망 STT 또는 로컬 모델**을
쓴다. 그 경우 `scripts/transcribe_audio.py` 의 호출 대상만 바꾸면 되고,
저장 경로와 후속 절차(`ROUTINES.md` R7)는 그대로다.

**녹음 자체가 금지된 회의가 있다.** 상위자 주재 회의는 녹음, 녹화를 금지하는
경우가 있으므로 `PROFILE.md` §7 과 `ORG.md` §5 에 가능한 회의를 목록으로
관리하고, 목록에 없으면 녹음하지 않는다.

막혔을 때: 회의 중 구술 메모 → 직후 요약. 원문은 남지 않으므로 요약의
정확도를 본부장이 그 자리에서 확인해야 한다.

---

## 6. 외부 웹

시장 동향(R1)과 법규, 경쟁사 조사에 쓴다. 사내 방화벽, 프록시 정책에 따라
허용 도메인 화이트리스트가 필요할 수 있다.

**검색어에 사내 정보를 넣지 않는다.** 과제명, 코드명, 내부 인물명을 검색창에
넣는 순간 외부로 나간다. 공개된 사실만 검색한다.

막혔을 때: 사내에서 받는 뉴스 클리핑을 `knowledge_base/` 에 축적해 R1의
입력으로 쓴다.

---

## 7. SharePoint, OneNote

Graph 권한 범위에 포함되는지 확인이 필요하다. 문서 보관처로 쓰이는 경우
보고자료 검토(R5)와 과제 이력 통합의 입력이 된다.

대체 경로: 해당 문서를 로컬로 내려받아 `attachments/raw/` 에 둔다.

---

## 8. 하지 않는 연결

| 대상 | 사유 |
| --- | --- |
| 사내 전자결재 시스템 | 미연동. 결재 요약, 쟁점 정리까지가 범위이며 승인, 반려는 하지 않는다 |
| 오토웨어(M채널) | 미지원 |
| 사내 기간계 DB 직접 연계 | AI 거버넌스 협의 사항 |
| 외부 사이트 예약, 구매 실행 | 위험 대비 효용이 낮다. 후보 정리까지만 |
| 개인 계정 (개인 메일, 캘린더, 사외 메신저) | 본부별 정책 확인 후 결정. 기본값은 연동하지 않음 |

---

## 9. 비용, 토큰 상한

사용량 상한 정책이 정해지면 본부장께 **사전에** 안내한다. 상한에 도달했을 때
어떻게 되는지(중단되는지, 느려지는지)를 함께 알린다. 쓰다가 갑자기 멈추면
그 다음부터 쓰지 않는다.

무거운 작업은 미리 알린다: 긴 회의 전사, 대량 메일 분석, 장문 문서 전체 검토.

---

## 10. 진단 결과 기록

`check_connections.py` 결과를 `logs/YYYY-MM-DD/connections.txt` 에 남기고,
요약을 `PROFILE.md` §3 의 연결 표에 옮긴다. 무엇이 언제부터 막혀 있었는지가
남아야 에스컬레이션이 된다.

```bash
mkdir -p logs/<오늘>
bin/graph check > logs/<오늘>/connections.txt 2>&1
```

---

## 6. Atlassian (Confluence, Jira): 2026-09-03 추가

회의 준비(R3)와 과제 추적(R6)이 사내 지식과 이슈를 읽는 통로다.
**MCP 등록은 에이전트가 실행하고, 브라우저 로그인만 본부장님이 하신다.**

### 에이전트가 실행하는 것

```
claude mcp add --transport http atlassian https://mcp.atlassian.com/v1/sse
```

헬피코드에서는 설정 파일에 다음을 넣는다 (`~/.config/helpycode/helpycode.jsonc`).

```jsonc
{
  "mcp": {
    "atlassian": {
      "type": "remote",
      "url": "https://mcp.atlassian.com/v1/sse",
      "enabled": true
    }
  }
}
```

### 본부장님이 하시는 것

브라우저가 열리면 **회사 Atlassian 계정으로 로그인**하고 접근 허용을 누른다.
한 번만 하면 토큰이 갱신된다.

### 확인

```
bin/graph check
```

`Confluence / Jira MCP  연결됨` 이 나오면 끝이다.

### 안 되면 무엇을 잃는가

| 잃는 것 | 대체 경로 |
| --- | --- |
| 회의 전 자동 쟁점 정리 | 본부장님이 문서 링크를 붙여넣으면 읽는다 |
| 과제 지연, 리스크 자동 추적 | 회의 중 구술로 받아 `projects/` 에 기록 |
| 과거 유사 건 검색 | `decisions/` 의 자체 이력만 검색 |

---

## 7. Microsoft Graph 자격증명: 2026-09-03 승인 반영

현대차 ICT 가 `HMG-LeaderAXSession-PILOT` 앱으로 **위임 권한 19종**을 승인했다.
승인 목록과 사용자 12명은 `source/ict/2026-09-03_Graph권한_승인결과.md` 에 있다.

### 저장 위치

| OS | 저장소 |
| --- | --- |
| macOS | 로그인 키체인 |
| Windows | DPAPI: 사용자 계정에 묶인 암호화 파일 (`%LOCALAPPDATA%\hmg-agent\secrets`) |

워크스페이스 파일에는 쓰지 않는다. `.env` 도 만들지 않는다.

### 설정

본부장님은 에이전트에게 말만 하면 된다.

> "Graph 설정해줘"

에이전트가 `.claude/commands/setup.md` 절차대로 값을 여쭙고 저장한 뒤
로그인까지 진행한다. 자격증명이 없으면 세션 시작 훅이 자동으로 이 절차를 띄운다.


### 리디렉션 URI

로그인 콜백 주소입니다. **Entra 앱 등록의 값과 한 글자도 다르면 안 됩니다.**
다르면 로그인 화면에서 `AADSTS50011` 이 뜹니다.

| 항목 | 값 |
| --- | --- |
| 기본값 | `http://localhost:3000/auth/callback` |
| 근거 | 현대자동차 ICT 가 `HMG-LeaderAXSession-PILOT` 앱에 등록한 값 |
| 코드 위치 | `scripts/fetch_teams_message.py` 의 `LOCAL_REDIRECT_URI` |

현재 무엇이 쓰이는지는 다음으로 확인합니다.

```
bin/graph login --check
```

다른 앱을 쓰거나 앱에 이미 다른 값이 등록되어 있으면 **코드를 고치지 말고
환경변수로 맞춥니다.**

```
export MICROSOFT_GRAPH_REDIRECT_URI="http://localhost:8765/callback"
```

포트는 URI 에서 자동으로 읽어 콜백 서버가 그 포트에서 듣습니다.
`127.0.0.1` 이 아니라 `localhost` 로 적어야 합니다. Entra 는 `localhost` 만
http 예외로 허용합니다.

### 스코프

요청 스코프는 `.claude/graph_scopes.txt` 에 있고, Entra 승인 목록과 정확히 일치한다.
**승인 목록에 없는 줄이 하나라도 있으면 로그인 자체가 실패한다.** 고친 뒤에는 재로그인한다.
