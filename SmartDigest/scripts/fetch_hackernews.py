"""
fetch_hackernews.py — Fetches top stories from Hacker News API.

Usage:
    python fetch_hackernews.py
    python fetch_hackernews.py --dry-run
    python fetch_hackernews.py --date 2024-01-15

Uses official HN Firebase API (no auth required).
Output: data/raw/YYYY-MM-DD/hackernews.md
"""
from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Union, List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    item_hash, is_seen, mark_seen, load_seen_items, save_seen_items,
    load_config, write_raw_output, update_last_run, now_iso, days_ago
)

HN_API = "https://hacker-news.firebaseio.com/v0"


def hn_get(url: str) -> Union[Dict, List, None]:
    try:
        with urllib.request.urlopen(url, timeout=8) as resp:
            return json.loads(resp.read())
    except Exception as e:
        print(f"[hn] Error: {url} → {e}", file=sys.stderr)
        return None


def fetch_story(story_id: int) -> Optional[Dict]:
    return hn_get(f"{HN_API}/item/{story_id}.json")


def run(dry_run: bool = False, date_str: Optional[str] = None) -> int:
    print("[hn] Starting fetch...")
    config = load_config("sources.json")
    hn_cfg = config.get("hackernews", {})

    if not hn_cfg.get("enabled", True):
        print("[hn] Disabled in sources.json")
        update_last_run("source-collector-hn", "skipped", "disabled")
        return 0

    fetch_top = hn_cfg.get("fetch_top", 30)
    min_points = hn_cfg.get("min_points", 100)
    min_comments = hn_cfg.get("min_comments", 10)
    cfg_timeout = load_config("schedule.json").get("rate_limits", {}).get("hackernews_timeout_seconds", 15)

    # Get top story IDs
    print(f"[hn] Fetching top {fetch_top} story IDs...")
    top_ids = hn_get(f"{HN_API}/topstories.json")
    if not top_ids:
        update_last_run("source-collector-hn", "failure", "could not fetch topstories")
        return 0

    top_ids = top_ids[:fetch_top]
    seen = load_seen_items()
    all_items = []
    cutoff = days_ago(1)  # Only items from last 24h

    for story_id in top_ids:
        story = fetch_story(story_id)
        if not story or story.get("type") != "story":
            continue

        score = story.get("score", 0)
        comments = story.get("descendants", 0)

        if score < min_points or comments < min_comments:
            continue

        # Time filter
        ts = story.get("time", 0)
        pub_dt = datetime.fromtimestamp(ts, tz=timezone.utc) if ts else None
        if pub_dt and pub_dt < cutoff:
            continue

        url = story.get("url", f"https://news.ycombinator.com/item?id={story_id}")
        title = story.get("title", "Untitled")
        published = pub_dt.isoformat() if pub_dt else "unknown"

        h = item_hash("hackernews", url, title)
        if is_seen(h, seen):
            continue
        mark_seen(h, seen)

        # Build a concise summary from available metadata
        summary = (
            f"**Points:** {score} | **Comments:** {comments}\n"
            f"**Discussion:** https://news.ycombinator.com/item?id={story_id}\n"
            f"_{story.get('by', 'unknown')} posted this story_"
        )

        all_items.append({
            "title": title,
            "url": url,
            "source": "hackernews",
            "published_at": published,
            "summary": summary,
            "extra": {
                "points": str(score),
                "comments": str(comments),
                "by": story.get("by", "unknown"),
                "hn_id": str(story_id)
            }
        })
        print(f"  [+] [{score}pts] {title[:70]}")

    print(f"[hn] Collected {len(all_items)} qualifying items")

    if dry_run:
        for item in all_items:
            print(f"  {item['title']}")
        return len(all_items)

    save_seen_items(seen)

    if all_items:
        out = write_raw_output("hackernews", all_items, date_str)
        print(f"[hn] Written to {out}")
    else:
        print("[hn] No qualifying items today")

    update_last_run("source-collector-hn", "success", f"{len(all_items)} items")
    return len(all_items)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch HN data for SmartDigest")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--date", help="Target date YYYY-MM-DD")
    args = parser.parse_args()
    count = run(dry_run=args.dry_run, date_str=args.date)
    print(f"[hn] Done. {count} items.")
