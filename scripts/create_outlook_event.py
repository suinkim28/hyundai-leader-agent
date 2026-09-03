#!/usr/bin/env python3
"""Outlook 일정 등록 (쓰기).

어디에 쓰는가
-------------
R4, R7 에서 후속 일정을 잡을 때. 되돌릴 수 없는 행동이므로 훅이 본부장
확인을 받는다. 확인을 요청하기 전에 반드시 `--dry-run` 으로 무엇이
등록될지 먼저 보여드릴 것.

    bin/graph event --subject "품질 리뷰" \
        --start 2026-09-10T14:00 --end 2026-09-10T15:00 --dry-run
    bin/graph event --subject "품질 리뷰" \
        --start 2026-09-10T14:00 --end 2026-09-10T15:00 \
        --attendee hong@example.com --location "본관 3층"

시각 표기
---------
`--start`, `--end` 는 오프셋 없이 적는다 (2026-09-10T14:00). 어느 시간대로
읽을지는 `--timezone` 이 정하며 기본값은 Asia/Seoul 이다. PC 시간대에
영향받지 않게 하기 위함이다.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from fetch_teams_message import (                             # noqa: E402
    ENV_CLIENT_ID,
    ENV_CLIENT_SECRET,
    ENV_TENANT_ID,
    GRAPH_BASE,
    HttpRequestError,
    KEYCHAIN_CLIENT_ID,
    KEYCHAIN_CLIENT_SECRET,
    KEYCHAIN_TENANT_ID,
    get_auth_code_token,
    get_device_code_token,
    get_secret,
    load_dotenv,
)


def http_post_json(url: str, token: str, data: dict) -> dict:
    payload = json.dumps(data, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HttpRequestError("POST", url, exc.code, body) from exc


def graph_datetime(value: str) -> str:
    """Graph 의 dateTime 은 오프셋 없는 로컬 표기를 받는다.

    오프셋을 함께 보내면 timeZone 필드와 충돌해 등록 시각이 어긋난다.
    """
    normalized = value.strip().replace("Z", "")
    parsed = datetime.fromisoformat(normalized.split("+")[0])
    return parsed.strftime("%Y-%m-%dT%H:%M:%S")


def build_event(args: argparse.Namespace) -> dict:
    event: dict = {
        "subject": args.subject,
        "start": {"dateTime": graph_datetime(args.start), "timeZone": args.timezone},
        "end": {"dateTime": graph_datetime(args.end), "timeZone": args.timezone},
        "body": {"contentType": "text", "content": args.body},
        "isOnlineMeeting": bool(args.online),
    }
    if args.location:
        event["location"] = {"displayName": args.location}
    if args.attendee:
        event["attendees"] = [
            {"emailAddress": {"address": a}, "type": "required"} for a in args.attendee
        ]
    if args.online:
        event["onlineMeetingProvider"] = "teamsForBusiness"
    return event


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--subject", required=True, help="일정 제목")
    parser.add_argument("--start", required=True, help="시작 (2026-09-10T14:00)")
    parser.add_argument("--end", required=True, help="종료 (2026-09-10T15:00)")
    parser.add_argument("--location", default="", help="장소")
    parser.add_argument("--body", default="", help="본문")
    parser.add_argument("--attendee", action="append", default=[],
                        help="참석자 메일 주소. 여러 번 쓸 수 있다")
    parser.add_argument("--online", action="store_true", help="Teams 온라인 회의로 만든다")
    parser.add_argument("--timezone", default="Asia/Seoul", help="시간대. 기본 Asia/Seoul")
    parser.add_argument("--dry-run", action="store_true",
                        help="등록하지 않고 무엇이 등록될지만 보여준다")
    parser.add_argument("--flow", choices=["auth_code", "device"], default="auth_code")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        event_data = build_event(args)
        url = f"{GRAPH_BASE}/me/events"

        # 확인 전에 무엇이 나가는지 보여준다. 로그인보다 먼저 한다.
        if args.dry_run:
            print(f"Target: {url}")
            print(json.dumps(event_data, ensure_ascii=False, indent=2))
            return 0

        load_dotenv()
        tenant_id = get_secret(ENV_TENANT_ID, KEYCHAIN_TENANT_ID)
        client_id = get_secret(ENV_CLIENT_ID, KEYCHAIN_CLIENT_ID)
        client_secret = get_secret(ENV_CLIENT_SECRET, KEYCHAIN_CLIENT_SECRET)

        if args.flow == "auth_code":
            token = get_auth_code_token(tenant_id, client_id, client_secret)
        else:
            token = get_device_code_token(tenant_id, client_id, client_secret)

        result = http_post_json(url, token, event_data)
        print(f"등록됨: {result.get('subject')}")
        print(f"  id      : {result.get('id')}")
        print(f"  시작    : {(result.get('start') or {}).get('dateTime')}")
        print(f"  종료    : {(result.get('end') or {}).get('dateTime')}")
        if result.get("webLink"):
            print(f"  링크    : {result['webLink']}")
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
