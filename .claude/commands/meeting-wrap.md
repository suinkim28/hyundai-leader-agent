---
description: 회의 정리, 전사 원문 저장, 요약, 실행사항 분해
argument-hint: [오디오 경로 또는 회의명]
---

`ROUTINES.md` 의 **R7, 회의 정리** 를 실행한다. 대상: $ARGUMENTS

**먼저 녹음이 허용된 회의인지 확인한다.** `PROFILE.md` §6 과 `ORG.md` §5 의
목록에 없으면 녹음 파일을 처리하지 않고 본부장께 여쭙는다.

```bash
bin/graph transcribe <오디오경로> \
  --output meetings/transcripts/<오늘>_<제목>_TRANSCRIPT.md \
  --json-output meetings/transcripts/<오늘>_<제목>_TRANSCRIPT.json
```

`knowledge_base/용어집.txt` 를 프롬프트에 넣어 고유명사 정확도를 올린다.

1. **원문을 먼저 저장한다.** 요약이 틀렸을 때 돌아갈 곳이다. 원본 오디오
   경로를 파일 머리에 적는다.
2. 논의된 것 / 합의된 것 / **합의되지 않은 것** 으로 나눠 요약한다.
3. 실행사항을 `무엇 / 누가 / 언제까지 / 왜` 로 분해한다. 담당자나 기한이
   회의에서 정해지지 않았으면 `[미확보]` 로 두고 그 사실을 알린다.
   **비워두고 넘어가지 않는다.**
4. 오래 갈 결정은 `decisions/` 에, 과제 상태 변화는 `ORG.md` §4 에 반영한다.
5. 본부장의 선호가 드러난 대목은 `PROFILE.md` 에 반영한다.

`meetings/logs/<오늘>_<제목>_LOG.md` 로 저장한다.
