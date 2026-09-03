#!/usr/bin/env python3
"""Fetch Outlook calendar events for a date window via Microsoft Graph."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta

from fetch_teams_message import (
    ENV_CLIENT_ID,
    ENV_CLIENT_SECRET,
    ENV_TENANT_ID,
    GRAPH_BASE,
    HttpRequestError,
    KEYCHAIN_CLIENT_ID,
    KEYCHAIN_CLIENT_SECRET,
    KEYCHAIN_TENANT_ID,
    get_auth_code_token,
    get_client_credentials_token,
    get_device_code_token,
    get_secret,
    load_dotenv,
)


def http_get_json(url: str, token: str, timezone_name: str) -> dict:
    req = urllib.request.Request(url, method="GET")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("Prefer", f'outlook.timezone="{timezone_name}"')
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HttpRequestError("GET", url, exc.code, body) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch Outlook calendar events from Microsoft Graph."
    )
    parser.add_argument(
        "--start",
        help="Window start in ISO 8601. Default: today 00:00 in local timezone.",
    )
    parser.add_argument(
        "--end",
        help="Window end in ISO 8601. Default: tomorrow 00:00 in local timezone.",
    )
    parser.add_argument(
        "--date",
        help="Convenience date in YYYY-MM-DD. Uses the local timezone day window.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=1,
        help="Number of days from --date to fetch. Default: 1.",
    )
    parser.add_argument(
        "--timezone",
        default="Asia/Seoul",
        help='Microsoft timezone name for display. Default: "Asia/Seoul".',
    )
    parser.add_argument(
        "--flow",
        choices=["auth_code", "device", "client_credentials"],
        default="auth_code",
        help="Auth flow to use. Default is delegated localhost auth-code flow.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full structured JSON output.",
    )
    return parser.parse_args()


def parse_iso_datetime(value: str) -> datetime:
    normalized = value.replace("Z", "+00:00")
    dt = datetime.fromisoformat(normalized)
    if dt.tzinfo is None:
        raise ValueError(f"Timezone is required in datetime: {value}")
    return dt


def resolve_window(args: argparse.Namespace) -> tuple[datetime, datetime]:
    if args.start and args.end:
        return parse_iso_datetime(args.start), parse_iso_datetime(args.end)

    if args.date:
        target_day = date.fromisoformat(args.date)
    else:
        target_day = datetime.now().astimezone().date()

    start_dt = datetime.combine(target_day, time.min).astimezone()
    end_dt = start_dt + timedelta(days=args.days)
    return start_dt, end_dt


def fetch_calendar_view(token: str, start_dt: datetime, end_dt: datetime, timezone_name: str) -> list[dict]:
    query = urllib.parse.urlencode(
        {
            "startDateTime": start_dt.isoformat(),
            "endDateTime": end_dt.isoformat(),
            "$top": "100",
            "$orderby": "start/dateTime",
        }
    )
    url = f"{GRAPH_BASE}/me/calendarView?{query}"
    data = http_get_json(url, token, timezone_name)
    return data.get("value", [])


def main() -> int:
    args = parse_args()

    try:
        load_dotenv()
        start_dt, end_dt = resolve_window(args)
        tenant_id = get_secret(ENV_TENANT_ID, KEYCHAIN_TENANT_ID)
        client_id = get_secret(ENV_CLIENT_ID, KEYCHAIN_CLIENT_ID)
        client_secret = get_secret(ENV_CLIENT_SECRET, KEYCHAIN_CLIENT_SECRET)

        if args.flow == "client_credentials":
            token = get_client_credentials_token(tenant_id, client_id, client_secret)
        elif args.flow == "auth_code":
            token = get_auth_code_token(tenant_id, client_id, client_secret)
        else:
            token = get_device_code_token(tenant_id, client_id, client_secret)

        events = fetch_calendar_view(token, start_dt, end_dt, args.timezone)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    output = {
        "timezone": args.timezone,
        "start": start_dt.isoformat(),
        "end": end_dt.isoformat(),
        "count": len(events),
        "events": events,
    }

    if args.json:
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0

    print(f"Timezone: {output['timezone']}")
    print(f"Window: {output['start']} -> {output['end']}")
    print(f"Events: {output['count']}")

    for idx, event in enumerate(events, start=1):
        start_info = event.get("start", {})
        end_info = event.get("end", {})
        organizer = ((event.get("organizer") or {}).get("emailAddress") or {}).get("name", "")
        location = ((event.get("location") or {}).get("displayName") or "").strip()
        print()
        print(f"[{idx}] {event.get('subject') or '(no subject)'}")
        print(f"Start: {start_info.get('dateTime')} ({start_info.get('timeZone')})")
        print(f"End: {end_info.get('dateTime')} ({end_info.get('timeZone')})")
        if organizer:
            print(f"Organizer: {organizer}")
        if location:
            print(f"Location: {location}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
