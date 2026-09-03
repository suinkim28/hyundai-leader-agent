#!/usr/bin/env python3
"""Teams 채팅, 채널 메시지 키워드 검색 (Microsoft Search API).

어디에 쓰는가
-------------
R3 회의 준비의 "Teams 대화 중 관련 맥락"을 자동으로 찾는다. 대화 링크를
몰라도 키워드만으로 채팅과 채널 메시지를 함께 검색한다.

    bin/graph teams-search "본부장 AX"
    bin/graph teams-search "Graph 연결" --top 10 --json

찾은 메시지의 webLink 를 `bin/graph teams <url>` 에 넣으면 스레드 전체를
읽을 수 있다.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _graph_common import FLOWS, graph_post, token_for   # noqa: E402


def brief(hit: dict) -> dict:
    resource = hit.get("resource", {})
    sender = (resource.get("from") or {}).get("emailAddress", {})
    channel = resource.get("channelIdentity") or {}
    return {
        "from": sender.get("name"),
        "summary": hit.get("summary"),
        "created": resource.get("createdDateTime"),
        "chat_or_channel": "channel" if channel.get("channelId") else "chat",
        "webLink": resource.get("webLink"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("query", help="검색어")
    ap.add_argument("--top", type=int, default=20)
    ap.add_argument("--flow", choices=FLOWS, default="auth_code")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        token = token_for(args.flow)
        body = {
            "requests": [{
                "entityTypes": ["chatMessage"],
                "query": {"queryString": args.query},
                "from": 0,
                "size": args.top,
            }]
        }
        data = graph_post(token, "/search/query", body)
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    containers = (data.get("value") or [{}])[0].get("hitsContainers", [{}])
    hits_container = containers[0] if containers else {}
    total = hits_container.get("total", 0)
    items = [brief(h) for h in hits_container.get("hits", [])]

    if args.json:
        print(json.dumps({"total": total, "count": len(items), "items": items},
                         ensure_ascii=False, indent=2))
    else:
        print(f"검색어: {args.query!r}  전체 {total}건 중 {len(items)}건 표시\n")
        for it in items:
            print(f"[{it['chat_or_channel']}] {it['from']}  {it['created']}")
            print(f"  {it['summary']}")
            print(f"  {it['webLink']}")
            print()
    return 0


if __name__ == "__main__":
    sys.exit(main())
