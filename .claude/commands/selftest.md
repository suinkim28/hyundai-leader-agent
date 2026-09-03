---
description: 하네스 자가진단 — 이 실행 환경에서 안전장치가 실제로 동작하는지 확인
---

**본부장 PC 에서 실사용을 시작하기 전에 반드시 한 번 통과시켜야 한다.**

Claude Code CLI 를 감싸는 래퍼(H Code Desktop 등) 위에서는 훅 등록이 존중되는지
밖에서 알 수 없다. 무시되더라도 오류 없이 조용히 넘어가므로, 겉보기에는
정상 동작하면서 안전장치만 빠진 상태가 될 수 있다. 그 상태는 사고가 난 뒤에야
드러난다.

순서대로 실행한다.

## 1. 현재 상태

```bash
python3 scripts/verify_harness.py
```

## 2. 카나리아 — 훅을 일부러 깨운다

아래를 **그대로 실행한다.** 존재하지 않는 도메인(`.invalid`)이므로 실제
발송은 일어나지 않는다.

```bash
python3 scripts/reply_outlook_mail.py --to selftest@example.invalid --message "하네스 카나리아 — 거절해 주십시오"
```

- **확인 창이 뜨면** → 훅 정상. **거절한다.**
- **아무 창 없이 실행되면** → 훅이 죽어 있다. 아래 4번으로 간다.

이어서 `protect_secrets` 를 깨운다. **Write 도구로 `.env.canary` 파일에
아무 내용이나 쓰려고 시도한다.**

- **차단되면** → 훅 정상. 이것이 기대하는 결과다.
- **파일이 만들어지면** → 훅이 죽어 있다. 만들어진 파일을 지우고 4번으로 간다.

자격증명 파일 보호는 값을 한 번 잃으면 복구가 안 되는 영역이라, 다른 훅과
달리 되묻지 않고 **거부**한다. 그래서 판정이 명확하다 — 파일이 생겼는가 아닌가.

## 3. 재확인

```bash
python3 scripts/verify_harness.py
```

`실패` 가 0이고 `session_start` · `guard_external_actions` · `cite_sources` ·
`grounding_check` 가 모두 `OK` 면 통과다.

## 4. 결과 보고

본부장이 아니라 **챔피언·교육담당자에게 보고할 내용**으로 정리한다.

- 하네스 식별 정보 (`verify_harness.py` 첫 줄)
- 통과 / 실패 판정
- 실패한 항목마다 `HARNESS.md` 의 대응표에서 해당 행을 찾아 조치안을 붙인다
- 결과를 `logs/YYYY-MM-DD/harness.txt` 에 저장한다

```bash
mkdir -p logs/$(date +%F) && python3 scripts/verify_harness.py > logs/$(date +%F)/harness.txt 2>&1
```

**훅이 하나라도 죽어 있으면 실사용을 시작하지 않는다.** 판단은 챔피언이
아니라 교육담당자가 한다.
