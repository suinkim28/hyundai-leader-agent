---
description: 아침 브리핑 (08:00) — 일정·미결 결정·회신 필요·지연 과제 한 장
---

`ROUTINES.md` 의 **R2 — 아침 브리핑** 을 실행한다.

```bash
date +%F
python3 scripts/fetch_outlook_calendar.py --date $(date +%F) --days 1
python3 scripts/fetch_outlook_mail.py --unread --top 50
```

Graph 조회가 실패하면 `[미확보 — Graph 미승인]` 으로 표시하고 나머지만으로
작성한다. **조용히 건너뛰지 않는다.**

이어서 `ORG.md` §4 의 지연 과제, `decisions/` 의 미결 건,
`meetings/logs/` 최근 회의록의 미완료 실행사항을 확인한다.

**정보보다 결정이 먼저다.** "오늘 결정하실 것"을 맨 위에 둔다.
메일은 전체를 나열하지 말고 상위 5건과 나머지 건수만 쓴다.
화면 한 장을 넘기면 안 읽힌다.

`briefings/$(date +%F)_아침브리핑.md` 로 저장한다.
