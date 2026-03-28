"""
fetch_arxiv.py — Fetches recent papers from arXiv using the public Atom API.

Usage:
    python fetch_arxiv.py
    python fetch_arxiv.py --dry-run
    python fetch_arxiv.py --date 2024-01-15

No auth required. Uses the official arXiv API.
Output: data/raw/YYYY-MM-DD/arxiv.md
"""
from __future__ import annotations

import argparse
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    item_hash, is_seen, mark_seen, load_seen_items, save_seen_items,
    load_config, write_raw_output, update_last_run
)

ARXIV_API = "https://export.arxiv.org/api/query"
NS = {"atom": "http://www.w3.org/2005/Atom", "arxiv": "http://arxiv.org/schemas/atom"}


def fetch_arxiv_papers(query: str, max_results: int = 10) -> List[Dict]:
    """Query arXiv API and return structured paper items."""
    params = urllib.parse.urlencode({
        "search_query": f"all:{query}",
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending"
    })
    url = f"{ARXIV_API}?{params}"

    try:
        with urllib.request.urlopen(url, timeout=15) as resp:
            xml_text = resp.read().decode("utf-8")
    except Exception as e:
        print(f"[arxiv] Error fetching query '{query}': {e}", file=sys.stderr)
        return []

    # Rate-limit courtesy delay
    time.sleep(1)

    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError as e:
        print(f"[arxiv] XML parse error: {e}", file=sys.stderr)
        return []

    items = []
    for entry in root.findall("atom:entry", NS):
        arxiv_id_url = entry.findtext("atom:id", namespaces=NS) or ""
        # Clean URL: https://arxiv.org/abs/XXXX.XXXXX
        url = arxiv_id_url.strip()

        title = (entry.findtext("atom:title", namespaces=NS) or "").replace("\n", " ").strip()
        summary = (entry.findtext("atom:summary", namespaces=NS) or "").replace("\n", " ").strip()
        published = entry.findtext("atom:published", namespaces=NS) or ""
        updated = entry.findtext("atom:updated", namespaces=NS) or ""

        # Authors
        authors = []
        for author in entry.findall("atom:author", NS):
            name = author.findtext("atom:name", namespaces=NS)
            if name:
                authors.append(name.strip())

        # Categories
        categories = []
        for cat in entry.findall("atom:category", NS):
            term = cat.get("term", "")
            if term:
                categories.append(term)

        # PDF link
        pdf_url = ""
        for link in entry.findall("atom:link", NS):
            if link.get("type") == "application/pdf":
                pdf_url = link.get("href", "")
                break

        summary_trimmed = summary[:600] + ("..." if len(summary) > 600 else "")

        items.append({
            "title": title,
            "url": url,
            "source": "arxiv",
            "published_at": published,
            "summary": summary_trimmed,
            "extra": {
                "authors": ", ".join(authors[:3]) + (" et al." if len(authors) > 3 else ""),
                "categories": ", ".join(categories[:3]),
                "pdf": pdf_url,
                "updated": updated,
                "query": query
            }
        })

    return items


def run(dry_run: bool = False, date_str: Optional[str] = None) -> int:
    print("[arxiv] Starting fetch...")
    config = load_config("sources.json")
    queries = [q for q in config.get("arxiv", []) if q.get("enabled", True)]
    max_per_run = load_config("schedule.json").get("rate_limits", {}).get("arxiv_requests_per_run", 20)

    if not queries:
        print("[arxiv] No enabled queries in sources.json")
        update_last_run("source-collector-arxiv", "skipped", "no enabled queries")
        return 0

    seen = load_seen_items()
    all_items = []
    total_fetched = 0

    for q_cfg in queries:
        query = q_cfg.get("query", "")
        max_results = min(q_cfg.get("max_results", 10), max_per_run - total_fetched)
        if max_results <= 0:
            print(f"[arxiv] Rate limit reached ({max_per_run} requests/run)")
            break
        if not query:
            continue

        print(f"[arxiv] Query: '{query}' (max {max_results})")
        papers = fetch_arxiv_papers(query, max_results)
        total_fetched += len(papers)

        for paper in papers:
            h = item_hash("arxiv", paper["url"], paper["title"])
            if is_seen(h, seen):
                print(f"  [skip] {paper['title'][:60]}")
                continue
            mark_seen(h, seen)
            all_items.append(paper)
            print(f"  [+] {paper['title'][:70]}")

    print(f"[arxiv] Collected {len(all_items)} new papers")

    if dry_run:
        for item in all_items:
            print(f"  {item['title']}")
        return len(all_items)

    save_seen_items(seen)

    if all_items:
        out = write_raw_output("arxiv", all_items, date_str)
        print(f"[arxiv] Written to {out}")

    update_last_run("source-collector-arxiv", "success", f"{len(all_items)} papers")
    return len(all_items)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch arXiv papers for SmartDigest")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--date", help="Target date YYYY-MM-DD")
    args = parser.parse_args()
    count = run(dry_run=args.dry_run, date_str=args.date)
    print(f"[arxiv] Done. {count} papers.")
