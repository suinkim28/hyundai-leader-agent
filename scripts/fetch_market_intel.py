#!/usr/bin/env python3
"""Collect raw material for the daily market/tech briefing.

Two sources:
  1. 한경 글로벌마켓 YouTube channel (videos tab RSS + streams tab), with
     Korean auto-generated transcripts cleaned to plain text.
  2. Hacker News front page via the official Firebase API, with the
     comment threads (comments matter more than the articles here).

Writes one markdown bundle that a briefing session reads as its input.
"""

import argparse
import datetime as dt
import html
import json
import re
import subprocess
import sys
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

CHANNEL_ID = "UCWskYkV4c4S9D__rsfOl2JA"
CHANNEL_NAME = "한경 글로벌마켓"
CHANNEL_HANDLE = "%ED%95%9C%EA%B2%BD%EA%B8%80%EB%A1%9C%EB%B2%8C%EB%A7%88%EC%BC%93"
RSS_URL = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
STREAMS_URL = f"https://www.youtube.com/@{CHANNEL_HANDLE}/streams"
HN_API = "https://hacker-news.firebaseio.com/v0"
KST = dt.timezone(dt.timedelta(hours=9))


def log(msg):
    print(msg, file=sys.stderr)


def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


# --------------------------------------------------------------------------
# YouTube
# --------------------------------------------------------------------------

def rss_entries():
    """Videos tab, with reliable published timestamps."""
    req = urllib.request.Request(RSS_URL, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        root = ET.fromstring(resp.read())
    ns = {"a": "http://www.w3.org/2005/Atom", "yt": "http://www.youtube.com/xml/schemas/2015"}
    out = {}
    for e in root.findall("a:entry", ns):
        vid = e.find("yt:videoId", ns).text
        published = dt.datetime.fromisoformat(e.find("a:published", ns).text)
        out[vid] = {
            "id": vid,
            "title": e.find("a:title", ns).text,
            "published": published.astimezone(KST),
            "source": "videos",
        }
    return out


def stream_ids(limit):
    """Streams tab. Livestreams do not reliably show up in the channel RSS."""
    cmd = [
        "yt-dlp", "--flat-playlist", "--no-warnings", "--ignore-errors",
        "--playlist-end", str(limit), "--print", "%(id)s\t%(title)s", STREAMS_URL,
    ]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    except subprocess.TimeoutExpired:
        log("[warn] streams tab listing timed out")
        return {}
    out = {}
    for line in res.stdout.splitlines():
        if "\t" not in line:
            continue
        vid, title = line.split("\t", 1)
        out[vid.strip()] = {"id": vid.strip(), "title": title.strip(),
                            "published": None, "source": "streams"}
    return out


def video_published(vid):
    """Returns (datetime | None, reason). Members-only streams are common here."""
    cmd = ["yt-dlp", "--no-warnings", "--skip-download", "--print",
           "%(timestamp)s", f"https://www.youtube.com/watch?v={vid}"]
    try:
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        err = res.stderr or ""
        if "members-only" in err or "available to this channel's members" in err:
            return None, "멤버십 전용"
        ts = res.stdout.strip().splitlines()[-1]
        return dt.datetime.fromtimestamp(int(ts), tz=dt.timezone.utc).astimezone(KST), None
    except Exception as exc:
        return None, f"조회 실패 ({type(exc).__name__})"


def clean_vtt(path):
    raw = Path(path).read_text(encoding="utf-8", errors="ignore")
    lines = []
    for ln in raw.splitlines():
        if "-->" in ln or ln.startswith(("WEBVTT", "Kind:", "Language:")) or not ln.strip():
            continue
        ln = re.sub(r"<[^>]+>", "", ln).strip()
        if ln and (not lines or lines[-1] != ln):
            lines.append(ln)
    return re.sub(r"\s+", " ", " ".join(lines)).strip()


def transcript(vid, workdir):
    """Korean subtitles, manual first then auto-generated."""
    for args in (["--write-subs"], ["--write-auto-subs"]):
        cmd = ["yt-dlp", "--no-warnings", "--ignore-errors", "--skip-download",
               *args, "--sub-langs", "ko", "--sub-format", "vtt",
               "-o", str(workdir / f"{vid}.%(ext)s"),
               f"https://www.youtube.com/watch?v={vid}"]
        try:
            subprocess.run(cmd, capture_output=True, text=True, timeout=300)
        except subprocess.TimeoutExpired:
            continue
        hits = sorted(workdir.glob(f"{vid}*.vtt"))
        if hits:
            return clean_vtt(hits[0])
    return ""


def collect_youtube(since, max_videos, workdir):
    entries = rss_entries()
    for vid, meta in stream_ids(max_videos + 4).items():
        entries.setdefault(vid, meta)

    # Fill in dates for streams-tab-only entries.
    unknown = [v for v, m in entries.items() if m["published"] is None]
    skipped = []
    if unknown:
        with ThreadPoolExecutor(max_workers=4) as pool:
            for vid, (when, reason) in zip(unknown, pool.map(video_published, unknown)):
                entries[vid]["published"] = when
                if when is None:
                    skipped.append({"title": entries[vid]["title"], "id": vid,
                                    "reason": reason or "날짜 불명"})

    fresh = [m for m in entries.values() if m["published"] and m["published"] >= since]
    fresh.sort(key=lambda m: m["published"], reverse=True)
    fresh = fresh[:max_videos]

    log(f"[youtube] {len(entries)} known, {len(fresh)} within window, {len(skipped)} inaccessible")
    for meta in fresh:
        meta["transcript"] = transcript(meta["id"], workdir)
        log(f"[youtube] {meta['id']} transcript {len(meta['transcript'])} chars")
    return fresh, skipped


# --------------------------------------------------------------------------
# Hacker News
# --------------------------------------------------------------------------

def strip_html(text):
    if not text:
        return ""
    text = re.sub(r"<p>", "\n", text)
    text = re.sub(r"<[^>]+>", "", text)
    return html.unescape(text).strip()


def hn_item(item_id):
    try:
        return get_json(f"{HN_API}/item/{item_id}.json")
    except Exception:
        return None


def collect_hn(n_stories, n_comments):
    top = get_json(f"{HN_API}/topstories.json")[: n_stories * 2]
    with ThreadPoolExecutor(max_workers=10) as pool:
        raw = [s for s in pool.map(hn_item, top) if s]

    stories = [s for s in raw if s.get("type") == "story"][:n_stories]
    log(f"[hn] {len(stories)} stories")

    for story in stories:
        kid_ids = (story.get("kids") or [])[: n_comments * 2]
        with ThreadPoolExecutor(max_workers=10) as pool:
            kids = [k for k in pool.map(hn_item, kid_ids) if k]
        comments = []
        for kid in kids:
            if kid.get("deleted") or kid.get("dead") or not kid.get("text"):
                continue
            entry = {"by": kid.get("by", "?"), "text": strip_html(kid["text"]), "replies": []}
            # One level of replies: disagreement usually lives here.
            reply_ids = (kid.get("kids") or [])[:2]
            for reply in (hn_item(r) for r in reply_ids):
                if reply and reply.get("text") and not reply.get("deleted"):
                    entry["replies"].append(
                        {"by": reply.get("by", "?"), "text": strip_html(reply["text"])})
            comments.append(entry)
            if len(comments) >= n_comments:
                break
        story["_comments"] = comments
        log(f"[hn] {story.get('id')} {len(comments)} comments")
    return stories


# --------------------------------------------------------------------------
# Output
# --------------------------------------------------------------------------

def render(videos, stories, since, now, cap, skipped=()):
    L = []
    L.append(f"# Market & Tech Intel Bundle")
    L.append(f"\n생성: {now:%Y-%m-%d %H:%M} KST, 수집 범위: {since:%Y-%m-%d %H:%M} 이후\n")

    L.append(f"\n## 1. {CHANNEL_NAME} (YouTube)\n")
    if skipped:
        L.append("\n> 수집하지 못한 항목 (브리핑에 반드시 명시할 것):\n")
        for s in skipped:
            L.append(f"> - {s['title']} ({s['reason']}) https://www.youtube.com/watch?v={s['id']}")
        L.append("")
    if not videos:
        L.append("_수집 범위 내 신규 영상 없음._\n")
    for v in videos:
        L.append(f"\n### {v['title']}")
        L.append(f"- 게시: {v['published']:%Y-%m-%d %H:%M} KST ({v['source']} 탭)")
        L.append(f"- URL: https://www.youtube.com/watch?v={v['id']}")
        text = v.get("transcript") or ""
        if not text:
            L.append("- 자막: 없음 (제목만으로 판단할 것)")
        else:
            truncated = text[:cap]
            L.append(f"- 자막 {len(text)}자" + (f" (앞 {cap}자만 수록)" if len(text) > cap else ""))
            L.append(f"\n```\n{truncated}\n```")

    L.append(f"\n\n## 2. Hacker News Top {len(stories)}\n")
    for i, s in enumerate(stories, 1):
        L.append(f"\n### {i}. {s.get('title','(no title)')}")
        L.append(f"- {s.get('score',0)} points · {s.get('descendants',0)} comments")
        if s.get("url"):
            L.append(f"- 원문: {s['url']}")
        L.append(f"- 토론: https://news.ycombinator.com/item?id={s['id']}")
        if s.get("text"):
            L.append(f"- 본문: {strip_html(s['text'])[:600]}")
        cs = s.get("_comments") or []
        if not cs:
            L.append("- 코멘트 없음")
        else:
            L.append(f"\n**코멘트 ({len(cs)}건):**\n")
            for c in cs:
                L.append(f"- **{c['by']}**: {c['text'][:1200]}")
                for r in c["replies"]:
                    L.append(f"    - ↳ **{r['by']}**: {r['text'][:700]}")
    return "\n".join(L) + "\n"


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--since-hours", type=float, default=24.0)
    ap.add_argument("--max-videos", type=int, default=4)
    ap.add_argument("--hn-stories", type=int, default=10)
    ap.add_argument("--hn-comments", type=int, default=12)
    ap.add_argument("--transcript-cap", type=int, default=20000,
                    help="max transcript chars written per video")
    ap.add_argument("--out", default=None, help="output markdown path")
    ap.add_argument("--skip-youtube", action="store_true")
    ap.add_argument("--skip-hn", action="store_true")
    args = ap.parse_args()

    now = dt.datetime.now(KST)
    since = now - dt.timedelta(hours=args.since_hours)

    workdir = Path(__file__).resolve().parent.parent / ".tmp" / "market_intel"
    workdir.mkdir(parents=True, exist_ok=True)
    for stale in workdir.glob("*.vtt"):
        stale.unlink()

    videos, stories, skipped = [], [], []
    if not args.skip_youtube:
        try:
            videos, skipped = collect_youtube(since, args.max_videos, workdir)
        except Exception as exc:
            log(f"[error] youtube collection failed: {exc}")
            skipped = [{"title": "YouTube 수집 전체 실패", "id": "", "reason": str(exc)[:200]}]
    if not args.skip_hn:
        try:
            stories = collect_hn(args.hn_stories, args.hn_comments)
        except Exception as exc:
            log(f"[error] hacker news collection failed: {exc}")

    doc = render(videos, stories, since, now, args.transcript_cap, skipped)

    out = args.out or str(workdir / f"bundle_{now:%Y%m%d}.md")
    Path(out).write_text(doc, encoding="utf-8")
    print(out)


if __name__ == "__main__":
    main()
