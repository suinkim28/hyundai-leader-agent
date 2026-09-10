# DEVELOPMENT.md: 개발자용

이 문서는 **스켈레톤을 만들고 배포하는 사람**(엘리스)이 읽는다. 본부장 PC 에서
읽을 일이 없고, 본부장·챔피언용 문서(`README.md`, `SETUP.md` 등)에는 여기
내용을 섞지 않는다. 그 문서들은 처음 보는 사람 기준으로 **지금 무엇을 하는지**만
적고, 과거에 어땠는지는 전부 여기에 둔다.

---

## 1. 리포와 배포

| 항목 | 값 |
| --- | --- |
| 원본 (기본 push) | GitLab `git.elicer.io/elice/ax/projects/hyundai-leader-agent` |
| 공개 미러 | GitHub `github.com/suinkim28/hyundai-leader-agent`. `git push github main` 을 따로 친다 |
| 배포물 | GitHub `main` 을 zip 으로 받아 본부장 PC 에 폴더째 복사한다. `.git` 이 없으므로 본부장 PC 에서는 git 을 쓰지 않는다 |
| 사내망 작업 반영 | 사내망에서는 git 을 못 쓴다. zip 으로 받아 이 리포에 덮어쓴다. Windows 를 거치면 실행 비트가 전부 사라지므로 내용만 덮어쓴다: `rsync -rc --no-perms --exclude PROFILE.md --exclude ORG.md --exclude '__pycache__/' <zip>/ ./` |

`PROFILE.md`, `ORG.md` 와 산출물 폴더 전부(`attachments/`, `briefings/`,
`knowledge_base/`, `logs/`, `meetings/`, `decisions/`, `drafts/`, `projects/`)는
`.gitignore` 에 있어 `.gitkeep` 외에는 커밋되지 않는다. 그래도 **`git add -A` 는
쓰지 않는다.** 2026-09-03 에 이것 때문에 본부장 프로파일과 전사본이 커밋돼
히스토리를 다시 쌓았다.

---

## 2. 배포 전 확인: 개인 데이터를 비운다

**폴더 복사는 `.gitignore` 를 무시한다.** 개발 중 쌓인 본부장 데이터가 있으면
그대로 다음 본부장 PC 로 간다. 그러면 두 가지가 한꺼번에 일어난다.

- `PROFILE.md` 상태가 `진행중` 이라 새 PC 에서 부트스트랩 훅이 뜨지 않는다
- `attachments/raw/` 에 앞선 본부장의 전사본이 있어 새 본부장의 에이전트가
  그 사람 기준으로 개인화를 시작한다

배포용 zip 을 만들기 전에 아래가 전부 참이어야 한다.

- [ ] `PROFILE.md` 와 `ORG.md` 가 `templates/` 의 원본과 같다
- [ ] 아래 폴더에 `.gitkeep` 외의 파일이 없다: `attachments/raw/`,
      `attachments/extracted/`, `meetings/logs/`, `meetings/transcripts/`,
      `decisions/`, `drafts/`, `briefings/`, `projects/`,
      `knowledge_base/` (`transcription_glossary.txt` 는 남긴다)
- [ ] `logs/` 가 비어 있다. **`logs/.harness/` 도 비운다.** 훅 실행 흔적이 남아
      있으면 새 PC 의 `/selftest` 가 24시간 동안 개발자 PC 의 흔적으로 통과한다
- [ ] `__pycache__/`, `.tmp/` 가 없다

```bash
git status --porcelain            # 추적 파일 변경 없음
git clean -ndX                    # 삭제될 무시 파일 미리보기. PROFILE.md, ORG.md, logs/... 가 보여야 한다
git clean -fdX                    # 실제 삭제 (추적 파일은 건드리지 않는다)
```

`git clean -X` 는 `.gitignore` 대상만 지우므로 소스는 안전하다. 산출물 폴더가
전부 ignore 대상이라 이 한 번으로 개인 데이터가 비워진다.

---

## 3. 개발 환경

macOS 는 **테스트 전용**이다. 본부장 PC 는 전부 Windows 이고, 문서와 명령
예시는 Windows 기준으로 쓴다. macOS 에서만 되는 것(키체인 `security` 명령,
`open`)은 코드에 있어도 문서에는 적지 않는다.

### 3-1. 엘리스 테넌트 테스트 앱

현대차 앱(`HMG-LeaderAXSession-PILOT`)은 `@hyundai.com` 계정만 로그인할 수 있어
사외에서는 쓸 수 없다. 같은 권한의 앱을 엘리스 테넌트에 두고 루틴이 실제로
도는지 확인한다.

**알려진 제약**: 현재 엘리스 테스트 앱은 **컨피덴셜 클라이언트**로 등록되어
있어 토큰 요청에 `client_secret` 을 요구한다 (`AADSTS7000218`). 코드는 현대차
앱(**퍼블릭 클라이언트**, PKCE, 시크릿 없음) 기준이므로 **이 맥에서는 Graph
실호출이 되지 않는다.** 코드는 현대차 기준을 유지한다. 테스트하려면 엘리스
앱을 아래 표대로 다시 등록해야 한다.

| 항목 | 값 |
| --- | --- |
| 플랫폼 | **모바일 및 데스크톱 앱**. "웹"이 아니다. `http://localhost` 리디렉션은 이 플랫폼에서만 허용되고, 이 플랫폼은 자동으로 퍼블릭 클라이언트가 된다 |
| 리디렉션 URI | `http://localhost:3000/auth/callback` (포트, 경로까지 정확히. `127.0.0.1` 아님) |
| 계정 유형 | 이 조직 디렉터리의 계정만 |
| 권한 | `.claude/graph_scopes.txt` 의 목록을 **위임된 권한**으로 전부 추가. `User.Read.All`, `ChannelMessage.Read.All` 은 관리자 동의 필요 |
| 클라이언트 비밀 | 로그인에는 쓰이지 않지만 `bin/graph setup` 이 세 값을 받으므로 만들어 둔다. **`값(Value)` 열**을 복사한다. `비밀 ID` 가 아니다 |

요청 스코프(`graph_scopes.txt`)와 동의 목록은 항상 같아야 한다. 한쪽에만 있는
권한이 있으면 로그인이 실패한다.

### 3-2. 확인 순서

```
/selftest                                  # 에이전트 안에서. 정상 7, 실패 0
bin/graph check                            # 연결 진단
bin/graph mail --top 3
bin/graph calendar
bin/graph files recent --top 5
bin/graph notes books                      # 비어 있으면 OneNote 를 안 쓰는 계정이다. 고장 아님
bin/graph reply-mail <id> --message "테스트" --dry-run
/morning-brief                             # 실제 데이터로 한 장이 나오는지
```

### 3-3. 자주 나오는 오류

| 메시지 | 원인 | 조치 |
| --- | --- | --- |
| `AADSTS50011` redirect_uri 불일치 | 앱 등록의 URI 가 다르다 | `bin/graph login --check` 로 현재 값 확인. 앱을 못 고치면 `MICROSOFT_GRAPH_REDIRECT_URI` |
| `AADSTS65001` 동의 없음 | 관리자 동의 미클릭 | Entra 에서 `관리자 동의 허용` |
| `AADSTS70011` invalid_scope | 요청 스코프에 동의 안 된 권한 | `graph_scopes.txt` 를 동의 목록과 맞춘다 |
| `AADSTS700025` Client is public | 퍼블릭 클라이언트에 `client_secret` 을 보냈다 | 코드는 PKCE 다. 앱을 "웹"으로 등록했다면 "모바일 및 데스크톱 앱"으로 재등록 |
| `AADSTS7000218` client_secret 필요 | 앱이 컨피덴셜 클라이언트다 | 위 3-1 제약. 앱을 퍼블릭으로 재등록 |
| `CERTIFICATE_VERIFY_FAILED` | 사내 SSL 인스펙션 프록시 | `pip install truststore` (Python 3.10+). 프록시 없는 망이면 안 나온다 |
| 브라우저가 안 열림 | 콜백 포트 점유, 또는 `webbrowser.open()` 실패 | 터미널에 출력되는 URL 을 직접 연다 |

### 3-4. 현대차 PC 로 넘기기 전

- [ ] §2 개인 데이터 비움
- [ ] `/selftest` 정상 7, 실패 0
- [ ] Windows PC 에서 DPAPI 저장, 재읽기 확인 (macOS 에서는 검증되지 않는 경로다)
- [ ] 로그인 1회 후 **새 세션에서 재로그인 없이** `bin\graph.cmd mail --top 1` 이 된다
- [ ] `.claude/graph_scopes.txt` 가 현대차 승인 목록과 같다

---

## 4. 결정과 변경 이력

처음 보는 사람에게는 없는 맥락이므로 다른 문서에는 적지 않는다. 여기만 쌓는다.

### 2026-08-27: `.env` 폐기
에이전트가 `.env` 를 `.env.example` 로 덮어써 시크릿 4개가 날아갔다. git 에도
스냅샷에도 없어 3개는 키체인과 세션 기록에서 복구했고 Graph Client Secret 은
재발급했다. 이후 자격증명은 OS 저장소(Windows DPAPI, macOS 키체인)에만 두고,
`protect_secrets.py` 훅이 `.env` 쓰기를 막는다.

### 2026-09-03: 개인 데이터 분리, Windows 실행 경로
- `git add -A` 로 본부장 프로파일과 전사본이 커밋돼 있었다. 오염된 커밋을 버리고
  깨끗한 커밋 위에 다시 쌓았다. `PROFILE.md`, `ORG.md` 와 산출물 폴더를
  `.gitignore` 에 넣고 `templates/` 에 빈 원본만 둔다
- 훅이 `python3` 로 등록돼 있어 Windows 에서 통째로 안 돌았다. `.claude/hooks/run`
  런처와 `bin/graph`(sh) + `bin/graph.cmd` 로 진입점을 통일했다
- 현대차 ICT 가 `HMG-LeaderAXSession-PILOT` 앱에 위임 권한 19종을 승인했다.
  `graph_scopes.txt` 가 그 목록이다

### 2026-09-09 (사내망 작업)
- **한글 콘솔 인코딩**: cp949 와 Python 출력 인코딩 불일치로 메일이 깨졌다.
  `bin/graph`, `bin/graph.cmd`, `.claude/hooks/run` 에 `PYTHONUTF8=1`.
  `graph.cmd` 에 한글이 있으면 cmd.exe 가 오파싱하므로 ASCII 만 쓴다
- **PKCE 전환**: 앱이 퍼블릭 클라이언트인데 `client_secret` 을 보내 `AADSTS700025`
  로 거부됐다. 인증 코드 교환과 refresh 에서 시크릿을 빼고 `code_verifier` 를
  쓴다. 브라우저 실행을 `webbrowser.open()` 으로(기존엔 macOS `open` 만),
  refresh token 을 DPAPI 로(기존엔 평문 파일) 바꿨다
- **SSL 인스펙션 프록시**: HMG 사내망이 Graph HTTPS 를 가로채 자체 CA 를 내민다.
  Python 은 certifi 만 신뢰해 `CERTIFICATE_VERIFY_FAILED`. `_graph_common.py`
  첫머리에서 `truststore.inject_into_ssl()` 로 OS 인증서 저장소를 쓴다. 검증을
  끄는 것이 아니라 신뢰 소스를 바꾸는 것이라 프록시 없는 망에서도 그대로 동작한다
- **인증 코드 이동**: 인증/토큰/시크릿/HTTP 코드 전체가 `fetch_teams_message.py`
  에 있었고 9개 스크립트가 거기서 import 했다 (Teams 를 제일 먼저 만들면서 굳은
  구조). `_graph_common.py` 로 옮기고 `fetch_teams_message.py` 는 Teams 조회만
  남겼다. 옮긴 18개 함수 중 13개는 그대로, 5개는 위 PKCE·브라우저·DPAPI 변경

### 2026-09-10
- `check_connections.py` 가 토큰 재발급 함수를 인자 없이 불러 항상 "액세스 토큰
  없음"으로 오탐했다. 조용한 refresh 로 고쳤다
- `reply_outlook_mail.py` 에 `--cc`, `--attach` 추가 (createReply → PATCH → send)
- **DRM(AIP) 규칙 제거**: AIP 문서가 권한 있는 사용자에게 자동으로 열리는 것이
  확인됐다. "못 읽는다" 전제의 규칙을 걷고, 예외용 절차만 `CONNECTIONS.md` §9 에
  남겼다
- **발송 확인 훅 제거**: `guard_external_actions.py` 는 명령 문자열 매칭이라
  `--help` 까지 잡는 오탐이 잦았고 세션 몰입을 깼다. 훅, `gate_policy.json`,
  등급 3종, 부트스트랩 Q11·Q12(위임 범위)를 함께 없앴다. 이제 발송을 막는
  기계적 장치는 없고, `bin/graph check` 가 그 사실을 주의 항목으로 보고한다
- **기억 훅 재설계**: `keep_memory_portable.py` 가 `.claude/` 를 통째로 막고
  있었는데, Claude Code 의 auto memory 는 `~/.claude/projects/<p>/memory/` 에
  쌓이므로 그 규칙은 표적을 빗나가고 있었다. 로컬 상태(`settings.local.json`,
  `.jsonl`, `memory/`, `*-local/`, `.claude/CLAUDE.md`)만 막는 차단 목록으로
  뒤집고, `autoMemoryEnabled: false` 로 원천을 끄고, 막을 때 어느 파일에 대신
  쓸지 안내한다. Windows 경로 비교(`normcase`, `CLAUDE_CONFIG_DIR`)도 고쳤다
- **평문 자격증명 폴백 제거**: `~/.config/hmg-agent/secrets.json` 을 없앴다.
  macOS 키체인, Windows DPAPI 둘뿐이고, 그 외 환경에서는 저장하지 않고 실패한다
- **`CLAUDE.md` 포인터 수정**: 내용이 `SYSTEM.md` 한 줄이라 Claude Code 가
  글자로만 읽고 있었다. `@SYSTEM.md` 로 바꿔 실제로 import 되게 했다
- 문서에서 날짜 절과 과거 서술을 걷어 여기로 옮겼다. `TESTING.md` 는 §3 으로
  흡수했다. `CONNECTIONS.md` 는 뒤에 덧붙은 절이 앞 절과 겹치고 Atlassian
  등록 명령이 두 곳에서 달랐다 (`sse` / `http`). Atlassian 은 챔피언이 사내
  절차로 연결하므로 등록 상세를 문서에서 뺐다
- **지시 작업 로깅**: 본부장이 루틴 밖으로 지시한 작업은
  `projects/YYYY-MM-DD-<이름>/README.md` 부터 만들어 그 안에 남기도록 했다
  (`SYSTEM.md` §8-2-1, `~/Secretary` 의 운영 방식을 그대로 옮김). 그 전에는
  루틴 밖 분석 결과가 화면 답변으로 끝나 사라졌다. 산출물 폴더
  (`meetings/`, `decisions/`, `drafts/`, `projects/`)를 `.gitignore` 에 추가했다.
