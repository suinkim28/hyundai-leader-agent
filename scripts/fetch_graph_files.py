#!/usr/bin/env python3
"""OneDrive·SharePoint 파일 조회. 2026-09-03 승인된 Files 권한을 쓴다.

어디에 쓰는가
-------------
R5 결재·보고자료 검토. 메일에 첨부된 보고자료가 SharePoint 링크로만 오는
경우가 많고, 그 원문을 읽어야 근거를 확인할 수 있다.

    bin/graph files recent --top 20
    bin/graph files search "본부장 AX"
    bin/graph files get <item-id> --out attachments/raw/보고서.pptx
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from _graph_common import FLOWS, graph_download, graph_get, token_for   # noqa: E402

FIELDS = "id,name,size,lastModifiedDateTime,webUrl,file,folder,parentReference"


def brief(item: dict) -> dict:
    return {
        "id": item.get("id"),
        "name": item.get("name"),
        "size": item.get("size"),
        "modified": item.get("lastModifiedDateTime"),
        "kind": "folder" if item.get("folder") else "file",
        "path": (item.get("parentReference") or {}).get("path", ""),
        "url": item.get("webUrl"),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("action", choices=["recent", "search", "list", "get"])
    ap.add_argument("query", nargs="?", help="search 의 검색어, get 의 item id, list 의 폴더 경로")
    ap.add_argument("--top", type=int, default=25)
    ap.add_argument("--out", help="get 에서 저장할 경로")
    ap.add_argument("--flow", choices=FLOWS, default="auth_code")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    try:
        token = token_for(args.flow)
        if args.action == "recent":
            data = graph_get(token, "/me/drive/recent",
                             {"$top": args.top, "$select": FIELDS})
            items = [brief(x) for x in data.get("value", [])]
        elif args.action == "search":
            if not args.query:
                ap.error("search 에는 검색어가 필요합니다")
            data = graph_get(token, f"/me/drive/root/search(q='{args.query}')",
                             {"$top": args.top, "$select": FIELDS})
            items = [brief(x) for x in data.get("value", [])]
        elif args.action == "list":
            path = args.query or ""
            endpoint = ("/me/drive/root/children" if not path
                        else f"/me/drive/root:/{path.strip('/')}:/children")
            data = graph_get(token, endpoint, {"$top": args.top, "$select": FIELDS})
            items = [brief(x) for x in data.get("value", [])]
        else:
            if not args.query:
                ap.error("get 에는 item id 가 필요합니다")
            meta = graph_get(token, f"/me/drive/items/{args.query}", {"$select": FIELDS})
            dest = Path(args.out) if args.out else Path("attachments/raw") / meta["name"]
            n = graph_download(token, f"/me/drive/items/{args.query}/content", dest)
            print(f"{dest}  ({n:,} bytes)")
            return 0
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    if args.json:
        print(json.dumps({"count": len(items), "items": items}, ensure_ascii=False, indent=2))
    else:
        for it in items:
            size = f"{it['size']:,}" if it.get("size") else "-"
            print(f"  [{it['kind']:<6}] {it['modified'][:10] if it.get('modified') else '':<10} "
                  f"{size:>12}  {it['name']}")
            print(f"           id={it['id']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
