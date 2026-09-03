#!/usr/bin/env python3
"""OneNote 조회. 2026-09-03 승인된 Notes 권한을 쓴다.

어디에 쓰는가
-------------
R7 회의 정리. 본부장이 OneNote 로 회의 메모를 관리하는 경우, 회의록을
그쪽 체계에 맞춰 정리해야 한다. 먼저 기존 구조를 읽는다.

    bin/graph notes books
    bin/graph notes sections <notebook-id>
    bin/graph notes pages <section-id> --top 20
    bin/graph notes read <page-id>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _graph_common import FLOWS, graph_get, token_for      # noqa: E402
from fetch_teams_message import GRAPH_BASE                  # noqa: E402
import urllib.request                                       # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["books", "sections", "pages", "read"])
    ap.add_argument("target", nargs="?", help="sections/pages/read 의 상위 id")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--flow", choices=FLOWS, default="auth_code")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        token = token_for(args.flow)
        if args.action == "books":
            data = graph_get(token, "/me/onenote/notebooks",
                             {"$select": "id,displayName,lastModifiedDateTime"})
            rows = [(x["id"], x["displayName"], x.get("lastModifiedDateTime", "")[:10])
                    for x in data.get("value", [])]
        elif args.action == "sections":
            if not args.target:
                ap.error("sections 에는 notebook id 가 필요합니다")
            data = graph_get(token, f"/me/onenote/notebooks/{args.target}/sections",
                             {"$select": "id,displayName,lastModifiedDateTime"})
            rows = [(x["id"], x["displayName"], x.get("lastModifiedDateTime", "")[:10])
                    for x in data.get("value", [])]
        elif args.action == "pages":
            if not args.target:
                ap.error("pages 에는 section id 가 필요합니다")
            data = graph_get(token, f"/me/onenote/sections/{args.target}/pages",
                             {"$top": args.top, "$select": "id,title,lastModifiedDateTime"})
            rows = [(x["id"], x.get("title", "(제목 없음)"),
                     x.get("lastModifiedDateTime", "")[:10]) for x in data.get("value", [])]
        else:
            if not args.target:
                ap.error("read 에는 page id 가 필요합니다")
            req = urllib.request.Request(
                f"{GRAPH_BASE}/me/onenote/pages/{args.target}/content",
                headers={"Authorization": f"Bearer {token}"})
            with urllib.request.urlopen(req) as resp:
                print(resp.read().decode("utf-8", errors="ignore"))
            return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps([{"id": r[0], "name": r[1], "modified": r[2]} for r in rows],
                         ensure_ascii=False, indent=2))
    else:
        for rid, name, mod in rows:
            print(f"  {mod:<10}  {name}")
            print(f"              id={rid}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
