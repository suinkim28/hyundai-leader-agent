#!/usr/bin/env python3
"""Create Outlook calendar event via Microsoft Graph."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

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
    get_device_code_token,
    load_dotenv,
)


def http_post_json(url: str, token: str, data: dict) -> dict:
    payload = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        raise HttpRequestError("POST", url, exc.code, body) from exc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create Outlook calendar event via Microsoft Graph.")
    parser.add_argument("--subject", required=True, help="Event subject")
    parser.add_argument("--start", required=True, help="Start datetime ISO 8601 (e.g., 2026-06-30T14:50:00)")
    parser.add_argument("--end", required=True, help="End datetime ISO 8601 (e.g., 2026-06-30T15:20:00)")
    parser.add_argument("--location", default="", help="Location display name")
    parser.add_argument("--body", default="", help="Event body/description")
    parser.add_argument("--timezone", default="Asia/Seoul", help="Timezone")
    parser.add_argument("--flow", choices=["auth_code", "device"], default="auth_code", help="Auth flow")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    try:
        load_dotenv()
        tenant_id = get_secret(ENV_TENANT_ID, KEYCHAIN_TENANT_ID)
        client_id = get_secret(ENV_CLIENT_ID, KEYCHAIN_CLIENT_ID)
        client_secret = get_secret(ENV_CLIENT_SECRET, KEYCHAIN_CLIENT_SECRET)

        if args.flow == "auth_code":
            token = get_auth_code_token(tenant_id, client_id, client_secret)
        else:
            token = get_device_code_token(tenant_id, client_id, client_secret)

        # Parse datetimes and ensure timezone
        start_dt = datetime.fromisoformat(args.start.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(args.end.replace("Z", "+00:00"))

        # If naive, assume local timezone
        if start_dt.tzinfo is None:
            start_dt = start_dt.astimezone()
        if end_dt.tzinfo is None:
            end_dt = end_dt.astimezone()

        event_data = {
            "subject": args.subject,
            "start": {
                "dateTime": start_dt.isoformat(),
                "timeZone": args.timezone,
            },
            "end": {
                "dateTime": end_dt.isoformat(),
                "timeZone": args.timezone,
            },
            "location": {
                "displayName": args.location,
            },
            "body": {
                "contentType": "text",
                "content": args.body,
            },
            "isOnlineMeeting": False,
        }

        url = f"{GRAPH_BASE}/me/events"
        result = http_post_json(url, token, event_data)
        print(f"Created event: {result.get('id')}")
        print(f"Subject: {result.get('subject')}")
        print(f"Start: {result.get('start')}")
        print(f"End: {result.get('end')}")
        print(f"WebLink: {result.get('webLink')}")
        return 0

    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


def get_secret(env_name: str, keychain_service: str) -> str:
    import os
    value = os.environ.get(env_name, "").strip()
    if value:
        return value
    # keychain_get is in fetch_teams_message
    from fetch_teams_message import keychain_get
    return keychain_get(keychain_service)


if __name__ == "__main__":
    raise SystemExit(main())