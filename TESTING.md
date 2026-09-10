# TESTING.md: 엘리스 테넌트에서 끝까지 돌려보기

현대차 앱(`HMG-LeaderAXSession-PILOT`)은 할당 사용자 12명이 전부 `@hyundai.com`
계정이라 사내에서 로그인할 수 없다. **동일 권한의 앱을 엘리스 테넌트에 하나 만들어**
루틴 8종이 실제로 도는지 확인한 뒤 현대차 PC 로 넘어간다.

작성 2026-09-03

---

## 1. Entra 앱 등록 (엘리스 테넌트)

Azure Portal → Microsoft Entra ID → 앱 등록 → 새 등록

| 항목 | 값 |
| --- | --- |
| 이름 | `ELICE-LeaderAXSession-TEST` (이름은 자유) |
| 지원되는 계정 유형 | **이 조직 디렉터리의 계정만** (단일 테넌트) |
| 리디렉션 URI | 아래 참고 |

### 리디렉션 URI: 틀리면 로그인이 실패한다

플랫폼은 **모바일 및 데스크톱 앱**(퍼블릭 클라이언트)을 고른다.
**"웹(Web)"을 고르지 않는다.** Entra 는 `http://localhost` 리디렉션을
"모바일 및 데스크톱 앱" 플랫폼에서만 허용하고, 그 플랫폼으로 등록된
앱은 자동으로 퍼블릭 클라이언트가 된다. 로그인은 PKCE(코드 검증자)로
증명하므로 **클라이언트 시크릿이 로그인 자체에는 쓰이지 않는다.**

> 2026-09-09: 처음에 "웹" 플랫폼 + 시크릿 조합으로 안내했다가 실제
> 로그인에서 `AADSTS700025: Client is public, client_secret 을 보내면
> 안 됨` 으로 실패하는 것을 확인했다. Entra 가 이미 이 앱을 퍼블릭
> 클라이언트로 처리하고 있었기 때문이다. `get_auth_code_token()`
> (지금은 `scripts/_graph_common.py` 에 있음) 을 PKCE 로 바꿔 해결했다.
> **새로 앱을 등록할 때는 처음부터 "모바일 및 데스크톱 앱" 플랫폼을 고른다.**

```
http://localhost:3000/auth/callback
```

포트와 경로까지 정확히 같아야 합니다. 현재 값은 다음으로 확인합니다.

```
bin/graph login --check
```

앱에 이미 다른 값이 등록되어 있고 바꿀 수 없다면 코드를 고치지 말고
환경변수로 맞춥니다.

```
export MICROSOFT_GRAPH_REDIRECT_URI="<앱에 등록된 값>"
```

> Entra 는 `http://localhost` 를 예외로 허용한다. `127.0.0.1` 이 아니라
> `localhost` 로 적어야 합니다. 콜백 서버는 같은 포트의 `127.0.0.1` 에서 듣습니다.

---

## 2. API 권한 18종

**Microsoft Graph → 위임된 권한** 으로 추가한다. 응용 프로그램 권한이 아니다.

| # | 권한 | 관리자 동의 | 쓰는 곳 |
| --- | --- | --- | --- |
| 1 | `User.Read` | | 로그인, 본인 프로필 |
| 2 | `User.Read.All` | **필요** | 발신자 직급, 부서 (메일 트리아지 전제) |
| 3 | `User.ReadBasic.All` | | 기본 프로필 |
| 4 | `Mail.ReadWrite` | | R2 아침 브리핑, R4 초안 저장 |
| 5 | `MailboxSettings.Read` | | 근무시간, 시간대 |
| 6 | `Calendars.ReadWrite` | | R2 일정, R3 회의 준비 |
| 7 | `Calendars.Read.Shared` | | 공유 일정 |
| 8 | `Chat.Read` | | R3 회의 전 대화 맥락 |
| 9 | `ChannelMessage.Read.All` | **필요** | R3 채널 쟁점 |
| 10 | `Channel.ReadBasic.All` | | 채널 목록 |
| 11 | `Team.ReadBasic.All` | | 팀 목록 |
| 12 | `Files.ReadWrite` | | R5 결재 검토 (내 OneDrive) |
| 13 | `Files.ReadWrite.All` | | R5 결재 검토 (SharePoint 보고자료) |
| 14 | `Notes.ReadWrite` | | R7 회의록 (내 OneNote) |
| 15 | `Notes.ReadWrite.All` | | R7 회의록 (팀 노트북) |
| 16 | `Mail.Send` | | R4 회신 발송: 훅이 확인 |
| 17 | `ChatMessage.Send` | | Teams DM 발송: 훅이 확인 |
| 18 | `ChannelMessage.Send` | | 채널 게시: 훅이 확인 |

`offline_access`, `openid`, `profile` 은 OIDC 기본이라 목록에 추가하지 않아도 된다.
코드가 요청 스코프에 넣으면 자동으로 붙는다.

권한을 다 넣은 뒤 **`관리자 동의 허용`** 을 누른다. 2번과 9번은 이것 없이는 안 된다.

### 발송 3종을 빼고 테스트하려면

16~18 번을 추가하지 않고, `.claude/graph_scopes.txt` 에서 같은 세 줄을 주석 처리한다.
**둘 중 하나만 하면 로그인이 실패한다.** 요청 스코프와 동의 목록은 항상 같아야 한다.

---

## 3. 클라이언트 비밀

인증서 및 비밀 → 새 클라이언트 비밀 → 만료 선택 → 추가

**생성 직후 `값(Value)` 열을 복사한다.** `비밀 ID` 가 아니다. 값은 페이지를
벗어나면 다시 볼 수 없다.

**참고: 이 값은 기본 로그인 흐름(auth_code, PKCE)에는 쓰이지 않는다.**
위 §1 에서 설명했듯 이 앱은 퍼블릭 클라이언트라 로그인 요청에 시크릿을
보내지 않는다. 그래도 `setup_credentials.py` 가 세 값(Client ID, Tenant
ID, Client Secret)을 모두 요구하므로 생성은 그대로 하고 저장해 둔다.
나중에 `--flow client_credentials`(앱 전용 인증)를 쓸 경우에 대비한 것이다.

---

## 4. 설정: 에이전트에게 맡긴다

이 폴더에서 에이전트를 열고 아무 말이나 건다.

```
비서 역할 해줘
```

세션 시작 훅이 자격증명 없음을 감지해 설정 절차로 보낸다. 에이전트가 세 값을
여쭈면 붙여넣는다. 저장 후에는 마스킹된 형태만 화면에 남는다.

**입력 창은 뜨지 않는다.** 값은 대화창에서만 받는다.
에이전트가 `bin/graph setup` 을 표준입력으로 호출해 저장한다.

---

## 5. 확인 순서

### 5-1. 안전장치: **에이전트 안에서** 실행

```
/selftest
```

셸에서 `verify_harness.py` 만 돌리면 Stop 훅 두 개가 영원히 `미확인` 으로 남는다.
정상 8, 실패 0 이 나와야 한다.

### 5-2. 읽기: 하나씩

```
bin/graph mail --top 3
bin/graph calendar
bin/graph files recent --top 5
bin/graph notes books
bin/graph teams <Teams 메시지 URL>
```

각 명령이 무엇을 못 하는지도 본다. 예를 들어 `notes books` 가 비어 있으면
OneNote 를 안 쓰는 계정이라는 뜻이지 고장이 아니다.

### 5-3. 쓰기: 반드시 `--dry-run` 부터

```
bin/graph reply-mail <message_id> --message "테스트" --dry-run
```

`--dry-run` 없이 실행했을 때 **훅이 막는지** 확인한다. 안 막으면 안전장치가
동작하지 않는 것이므로 본부장 PC 에 배포하면 안 된다.

### 5-4. 루틴: 에이전트 안에서

```
/morning-brief
/meeting-prep
/day-end
```

Atlassian MCP 가 붙어 있으면 `/meeting-prep` 이 Confluence, Jira 까지 읽는다.

---

## 6. 자주 나오는 오류

| 메시지 | 원인 | 조치 |
| --- | --- | --- |
| `AADSTS50011` redirect_uri 불일치 | 앱 등록의 URI 가 다르다 | `http://localhost:3000/auth/callback` 정확히 |
| `AADSTS65001` 동의 없음 | 관리자 동의 미클릭 | Entra 에서 `관리자 동의 허용` |
| `AADSTS70011` invalid_scope | 요청 스코프에 동의 안 된 권한 | `graph_scopes.txt` 를 동의 목록과 맞춘다 |
| `invalid_client` | 시크릿 오타, 만료, 또는 비밀 ID 를 넣음 | `값(Value)` 열을 다시 복사 |
| `AADSTS700025` Client is public | 앱이 퍼블릭 클라이언트인데 로그인 요청에 `client_secret` 이 딸려 갔다 | `scripts/_graph_common.py` 가 PKCE 를 쓰는 최신본인지 확인 (2026-09-09 수정, 이후 `fetch_teams_message.py` 에서 이 파일로 이동). 앱을 "웹" 플랫폼으로 새로 등록했다면 §1 대로 "모바일 및 데스크톱 앱"으로 다시 등록 |
| 브라우저가 안 열림 | 콜백 포트 점유, 또는 `webbrowser.open()` 이 실패 | 터미널에 함께 출력되는 URL 을 직접 열어도 로그인은 그대로 된다. 포트 점유면 그 프로세스를 끈다 |

---

## 7. 현대차 PC 로 넘어가기 전 체크

- [ ] `/selftest` 정상 8, 실패 0
- [ ] 읽기 5종 전부 응답
- [ ] 발송을 훅이 막는 것 확인
- [ ] `/morning-brief` 가 실제 데이터로 한 장을 만든다
- [ ] Windows PC 에서 DPAPI 저장, 재읽기 확인 (macOS 에서는 검증되지 않는 경로다)
- [ ] 로그인 1회 후 **새 세션에서 재로그인 없이** `bin/graph mail --top 1` 이 되는지 확인
      (refresh token 이 DPAPI 로 저장돼 있으면 세션이 바뀌어도 유지된다)
- [ ] `.claude/graph_scopes.txt` 를 현대차 승인 목록으로 되돌린다
      (테스트에서 발송 3종을 뺐다면 다시 넣는다)
