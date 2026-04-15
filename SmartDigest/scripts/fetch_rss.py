"""
fetch_rss.py — Fetches and parses RSS/Atom feeds.

Usage:
    python fetch_rss.py
    python fetch_rss.py --dry-run
    python fetch_rss.py --date 2024-01-15

No external dependencies — uses stdlib xml.etree.ElementTree.
Output: data/raw/YYYY-MM-DD/rss.md
"""
from __future__ import annotations

import argparse
import sys
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Optional, List, Dict

sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    item_hash, is_seen, mark_seen, load_seen_items, save_seen_items,
    load_config, write_raw_output, update_last_run, days_ago
)

LOOKBACK_DAYS = 2
NS = {
    "atom": "http://www.w3.org/2005/Atom",
    "content": "http://purl.org/rss/1.0/modules/content/",
    "dc": "http://purl.org/dc/elements/1.1/",
    "media": "http://search.yahoo.com/mrss/",
}


def fetch_feed_xml(url: str, timeout: int = 10) -> Optional[str]:
    headers = {
        "User-Agent": "SmartDigest/1.0 RSS Reader (+https://github.com/smartdigest)"
    }
    req = urllib.request.Request(url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", errors="replace")
    except Exception as e:
        print(f"[rss] Error fetching {url}: {e}", file=sys.stderr)
        return None


def parse_date(date_str: Optional[str]) -> Optional[datetime]:
    if not date_str:
        return None
    # Try RFC 2822 (RSS)
    try:
        return parsedate_to_datetime(date_str)
    except Exception:
        pass
    # Try ISO 8601 (Atom)
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S.%f%z"):
        try:
            return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
        except ValueError:
            continue
    return None


def strip_html(text: str) -> str:
    """Very basic HTML stripping — avoids BeautifulSoup dependency."""
    import re
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def parse_rss(xml_text: str, feed_name: str) -> List[Dict]:
    """Parse RSS 2.0 format."""
    root = ET.fromstring(xml_text)
    channel = root.find("channel")
    if channel is None:
        return []

    items = []
    cutoff = days_ago(LOOKBACK_DAYS)

    for item in channel.findall("item"):
        title = (item.findtext("title") or "").strip()
        url = (item.findtext("link") or "").strip()
        pub_str = item.findtext("pubDate") or item.findtext("dc:date", namespaces=NS)
        pub_dt = parse_date(pub_str)

        if pub_dt and pub_dt < cutoff:
            continue

        description = item.findtext("description") or ""
        content = item.findtext("content:encoded", namespaces=NS) or description
        summary = strip_html(content)[:500]

        items.append({
            "title": title,
            "url": url,
            "source": "rss",
            "published_at": pub_dt.isoformat() if pub_dt else "unknown",
            "summary": summary or "_No summary._",
            "extra": {"feed": feed_name}
        })
    return items


def parse_atom(xml_text: str, feed_name: str) -> List[Dict]:
    """Parse Atom 1.0 format."""
    root = ET.fromstring(xml_text)
    items = []
    cutoff = days_ago(LOOKBACK_DAYS)

    for entry in root.findall("atom:entry", NS):
        title = (entry.findtext("atom:title", namespaces=NS) or "").strip()

        # Atom links can be tricky
        url = ""
        for link in entry.findall("atom:link", NS):
            if link.get("rel") in (None, "alternate"):
                url = link.get("href", "")
                break

        pub_str = entry.findtext("atom:published", namespaces=NS) or \
                  entry.findtext("atom:updated", namespaces=NS)
        pub_dt = parse_date(pub_str)

        if pub_dt and pub_dt < cutoff:
            continue

        summary_el = entry.find("atom:summary", NS)
        content_el = entry.find("atom:content", NS)
        raw = (content_el.text if content_el is not None else None) or \
              (summary_el.text if summary_el is not None else "") or ""
        summary = strip_html(raw)[:500]

        items.append({
            "title": title,
            "url": url,
            "source": "rss",
            "published_at": pub_dt.isoformat() if pub_dt else "unknown",
            "summary": summary or "_No summary._",
            "extra": {"feed": feed_name}
        })
    return items


def parse_feed(xml_text: str, feed_name: str) -> List[Dict]:
    """Auto-detect RSS vs Atom and parse accordingly."""
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"[rss] XML parse error for {feed_name}: {e}", file=sys.stderr)
        return []

    tag = root.tag.lower()
    if "feed" in tag or "atom" in tag:
        return parse_atom(xml_text, feed_name)
    return parse_rss(xml_text, feed_name)


def run(dry_run: bool = False, date_str: Optional[str] = None) -> int:
    print("[rss] Starting fetch...")
    config = load_config("sources.json")
    feeds = [f for f in config.get("rss", []) if f.get("enabled", True)]
    timeout = load_config("schedule.json").get("rate_limits", {}).get("rss_timeout_seconds", 10)

    if not feeds:
        print("[rss] No enabled feeds in sources.json")
        update_last_run("source-collector-rss", "skipped", "no enabled feeds")
        return 0

    seen = load_seen_items()
    all_items = []

    for feed in feeds:
        name = feed.get("name", "Unknown Feed")
        url = feed.get("url", "")
        if not url:
            continue

        print(f"[rss] Fetching: {name}")
        xml_text = fetch_feed_xml(url, timeout=timeout)
        if not xml_text:
            continue

        items = parse_feed(xml_text, name)
        new_count = 0
        for item in items:
            h = item_hash("rss", item["url"], item["title"])
            if is_seen(h, seen):
                continue
            mark_seen(h, seen)
            all_items.append(item)
            new_count += 1
            print(f"  [+] {item['title'][:70]}")

        print(f"  → {new_count} new items from {name}")

    print(f"[rss] Collected {len(all_items)} new items total")

    if dry_run:
        for item in all_items:
            print(f"  [{item['extra'].get('feed', '')}] {item['title']}")
        return len(all_items)

    save_seen_items(seen)

    if all_items:
        out = write_raw_output("rss", all_items, date_str)
        print(f"[rss] Written to {out}")

    update_last_run("source-collector-rss", "success", f"{len(all_items)} items")
    return len(all_items)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch RSS feeds for SmartDigest")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--date", help="Target date YYYY-MM-DD")
    args = parser.parse_args()
    count = run(dry_run=args.dry_run, date_str=args.date)
    print(f"[rss] Done. {count} items.")
