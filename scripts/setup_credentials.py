#!/usr/bin/env python3
"""Microsoft Graph 자격증명을 이 컴퓨터의 보안 저장소에 넣는다.

누가 실행하는가
---------------
**에이전트다.** 본부장은 터미널을 열지 않는다. 대화로 값을 말하면 에이전트가
이 스크립트를 호출해 저장한다.

    본부장 : "설정해줘. Client ID 는 ..., Tenant ID 는 ..., Secret 은 ..."
    에이전트: python3 scripts/setup_credentials.py --stdin <<'JSON'
              {"client_id": "...", "tenant_id": "...", "client_secret": "..."}
              JSON

저장 위치
---------
    macOS   로그인 키체인
    Windows DPAPI (사용자 계정에 묶인 암호화 파일)

값은 워크스페이스 파일에 절대 쓰지 않는다. `.env` 도 만들지 않는다.

대화를 거치지 않는 경로
-----------------------
AX 챔피언이 세팅할 때는 `--prompt` 를 쓴다. 입력 창이 떠서 값이 대화 기록에
남지 않는다. 본부장이 직접 할 때는 창을 다루는 부담이 있어 기본값이 아니다.

    python3 scripts/setup_credentials.py --prompt

확인만
------
    python3 scripts/setup_credentials.py --check
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import secret_store as ss                                    # noqa: E402

GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-"
                  r"[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")

FIELDS = [
    ("client_id", "Client ID", ss.GRAPH_CLIENT_ID, False),
    ("tenant_id", "Tenant ID", ss.GRAPH_TENANT_ID, False),
    ("client_secret", "Client Secret", ss.GRAPH_CLIENT_SECRET, True),
]


def validate(values: dict[str, str]) -> list[str]:
    problems = []
    for key, label, _, is_secret in FIELDS:
        value = (values.get(key) or "").strip()
        if not value:
            problems.append(f"{label} 이(가) 비어 있습니다")
            continue
        if not is_secret and not GUID.match(value):
            problems.append(
                f"{label} 형식이 GUID 가 아닙니다 "
                f"(예: d48b7ab1-3364-43a1-96e2-dcc808d8639c)"
            )
        if is_secret and len(value) < 20:
            problems.append(f"{label} 이(가) 너무 짧습니다. 값을 다시 확인하십시오")
        if is_secret and GUID.match(value):
            problems.append(
                f"{label} 자리에 GUID 가 들어왔습니다. "
                f"Secret 값(Entra 의 '값' 열)인지 확인하십시오"
            )
    return problems


def store(values: dict[str, str]) -> str:
    where = ""
    for key, label, service, _ in FIELDS:
        where = ss.keychain_set(service[1], values[key])
    return where


def read_back() -> dict[str, str]:
    return {key: ss.keychain_get(service[1]) for key, _, service, _ in FIELDS}


def report(values: dict[str, str], where: str = "") -> int:
    print()
    if where:
        print(f"저장 위치: {where}")
    missing = []
    for key, label, _, is_secret in FIELDS:
        value = values.get(key) or ""
        if value:
            print(f"  OK   {label:<14} {ss.mask(value)}")
        else:
            print(f"  없음 {label:<14} -")
            missing.append(label)
    print()
    if missing:
        print("아직 없는 값: " + ", ".join(missing))
        return 1
    print("다음: python3 bin/graph login  (브라우저가 열립니다)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--stdin", action="store_true",
                   help="JSON 을 표준입력으로 받는다 (에이전트가 쓰는 기본 경로)")
    g.add_argument("--prompt", action="store_true",
                   help="입력 창을 띄운다. 값이 대화 기록에 남지 않는다 (챔피언용)")
    g.add_argument("--check", action="store_true", help="저장 상태만 확인한다")
    args = ap.parse_args()

    if args.check:
        return report(read_back())

    if args.prompt:
        try:
            import secret_prompt
        except ImportError as exc:
            print(f"입력 창 모듈을 못 불러왔습니다: {exc}", file=sys.stderr)
            return 2
        try:
            values = secret_prompt.ask(
                [(k, l, s) for k, l, _, s in FIELDS],
                title="Microsoft Graph 자격증명",
            )
        except KeyboardInterrupt as exc:
            print(f"취소됨: {exc}", file=sys.stderr)
            return 130
        except Exception as exc:
            print(f"입력 창을 띄울 수 없습니다: {exc}", file=sys.stderr)
            print("에이전트가 --stdin 경로로 저장하도록 하십시오.", file=sys.stderr)
            return 2
    else:
        raw = sys.stdin.read().strip()
        if not raw:
            print("표준입력이 비어 있습니다. --stdin 으로 JSON 을 주거나 "
                  "--prompt 로 입력 창을 띄우십시오.", file=sys.stderr)
            return 2
        try:
            values = json.loads(raw)
        except json.JSONDecodeError as exc:
            print(f"JSON 을 읽지 못했습니다: {exc}", file=sys.stderr)
            return 2
        if not isinstance(values, dict):
            print("JSON 최상위는 객체여야 합니다.", file=sys.stderr)
            return 2

    problems = validate(values)
    if problems:
        print("입력값에 문제가 있습니다. 저장하지 않았습니다.", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    try:
        where = store(values)
    except Exception as exc:
        print(f"저장 실패: {exc}", file=sys.stderr)
        return 1

    return report(read_back(), where)


if __name__ == "__main__":
    sys.exit(main())
