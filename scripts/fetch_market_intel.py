#!/usr/bin/env python3
"""R1 시장 동향 브리핑의 재료를 모은다.

무엇을 읽을지는 코드가 아니라 `config/market_sources.json` 이 정한다.
본부장마다 관심 분야가 다르므로 소스를 코드에 박아두지 않는다.

  1. 설정된 YouTube 채널 (videos 탭 RSS + streams 탭), 한국어 자막을
     평문으로 정리
  2. Hacker News 프런트 페이지 (설정에서 켠 경우). 기사보다 코멘트가 정보다

브리핑 세션이 입력으로 읽는 마크다운 묶음 하나를 쓴다.
소스가 하나도 설정되지 않았으면 아무것도 만들지 않고 그렇게 알린다.
"""

import argparse
import datetime as dt
import html
import json
import re
import subprocess
import sys
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SOURCES_FILE = ROOT / "config" / "market_sources.json"
HN_API = "https://hacker-news.firebaseio.com/v0"
KST = dt.timezone(dt.timedelta(hours=9))


def log(msg):
    print(msg, file=sys.stderr)


def load_sources():
    """소스 설정을 읽는다. 파일이 없으면 빈 설정으로 본다."""
    if not SOURCES_FILE.exists():
        log(f"[warn] {SOURCES_FILE} 가 없습니다. 수집할 소스가 없습니다")
        return {"youtube_channels": [], "hacker_news": False}
    try:
        raw = json.loads(SOURCES_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise SystemExit(f"{SOURCES_FILE} 를 읽을 수 없습니다: {exc}")
    channels = []
    for ch in raw.get("youtube_channels") or []:
        cid = (ch.get("id") or "").strip()
        if not cid or cid.startswith("UCxxxx"):
            continue
        channels.append({
            "id": cid,
            "name": (ch.get("name") or cid).strip(),
            "handle": (ch.get("handle") or "").strip(),
        })
    return {"youtube_channels": channels, "hacker_news": bool(raw.get("hacker_news"))}


def get_json(url, timeout=30):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.load(resp)


# --------------------------------------------------------------------------
# YouTube
# --------------------------------------------------------------------------

def rss_entries(channel):
    """Videos tab, with reliable published timestamps."""
    url = f"https://www.youtube.com/feeds/videos.xml?channel_id={channel['id']}"
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
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
            "channel": channel["name"],
        }
    return out


def stream_ids(channel, limit):
    """Streams tab. Livestreams do not reliably show up in the channel RSS."""
    if not channel.get("handle"):
        return {}
    handle = urllib.parse.quote(channel["handle"])
    cmd = [
        "yt-dlp", "--flat-playlist", "--no-warnings", "--ignore-errors",
        "--playlist-end", str(limit), "--print", "%(id)s\t%(title)s",
        f"https://www.youtube.com/@{handle}/streams",
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
                            "published": None, "source": "streams",
                            "channel": channel["name"]}
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


def collect_youtube(channels, since, max_videos, workdir):
    entries = {}
    for channel in channels:
        try:
            entries.update(rss_entries(channel))
        except Exception as exc:
            log(f"[error] {channel['name']} RSS 실패: {exc}")
        for vid, meta in stream_ids(channel, max_videos + 4).items():
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

    L.append("\n## 1. YouTube\n")
    if skipped:
        L.append("\n> 수집하지 못한 항목 (브리핑에 반드시 명시할 것):\n")
        for s in skipped:
            L.append(f"> - {s['title']} ({s['reason']}) https://www.youtube.com/watch?v={s['id']}")
        L.append("")
    if not videos:
        L.append("_수집 범위 내 신규 영상 없음._\n")
    for v in videos:
        L.append(f"\n### {v['title']}")
        L.append(f"- 채널: {v.get('channel', '(미상)')}")
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
        L.append(f"- {s.get('score',0)} points, {s.get('descendants',0)} comments")
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

    sources = load_sources()
    channels = sources["youtube_channels"]
    want_hn = sources["hacker_news"]
    if not channels and not want_hn:
        raise SystemExit(
            f"수집할 소스가 없습니다.\n"
            f"  {SOURCES_FILE} 에 본부장의 관심 분야에 맞는 소스를 넣으십시오.\n"
            f"  설정 전까지 R1 은 웹 검색으로 대신합니다."
        )

    now = dt.datetime.now(KST)
    since = now - dt.timedelta(hours=args.since_hours)

    workdir = Path(__file__).resolve().parent.parent / ".tmp" / "market_intel"
    workdir.mkdir(parents=True, exist_ok=True)
    for stale in workdir.glob("*.vtt"):
        stale.unlink()

    videos, stories, skipped = [], [], []
    if channels and not args.skip_youtube:
        try:
            videos, skipped = collect_youtube(channels, since, args.max_videos, workdir)
        except Exception as exc:
            log(f"[error] youtube collection failed: {exc}")
            skipped = [{"title": "YouTube 수집 전체 실패", "id": "", "reason": str(exc)[:200]}]
    if want_hn and not args.skip_hn:
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
