"""
fetch_github.py — Fetches releases and issues from configured GitHub repositories.

Usage:
    python fetch_github.py
    python fetch_github.py --dry-run     (print items, don't write files)
    python fetch_github.py --date 2024-01-15

Requires env var: GITHUB_TOKEN (optional but strongly recommended to avoid rate limits)
Output: data/raw/YYYY-MM-DD/github.md
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

# Allow running as standalone or from project root
sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    item_hash, is_seen, mark_seen, load_seen_items, save_seen_items,
    load_config, write_raw_output, update_last_run, now_iso, days_ago
)

GITHUB_API = "https://api.github.com"
LOOKBACK_DAYS = 2  # Only fetch items from the last N days


def make_headers() -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def gh_get(url: str) -> list | dict | None:
    """Simple GitHub API GET with error handling."""
    req = urllib.request.Request(url, headers=make_headers())
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        print(f"[github] HTTP {e.code} for {url}", file=sys.stderr)
        if e.code == 403:
            print("[github] Rate limited. Set GITHUB_TOKEN env var.", file=sys.stderr)
        return None
    except Exception as e:
        print(f"[github] Error fetching {url}: {e}", file=sys.stderr)
        return None


def fetch_releases(repo: str) -> list[dict]:
    """Fetch recent releases for a repo."""
    data = gh_get(f"{GITHUB_API}/repos/{repo}/releases?per_page=5")
    if not data:
        return []

    cutoff = days_ago(LOOKBACK_DAYS)
    items = []
    for release in data:
        published = release.get("published_at", "")
        if not published:
            continue
        try:
            pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
        except ValueError:
            continue
        if pub_dt < cutoff:
            continue

        body = release.get("body", "") or ""
        summary = body[:500].strip() if body else "_No release notes._"
        items.append({
            "title": f"[Release] {repo} {release.get('tag_name', '')} — {release.get('name', '')}",
            "url": release.get("html_url", ""),
            "source": "github",
            "published_at": published,
            "summary": summary,
            "extra": {
                "repo": repo,
                "tag": release.get("tag_name", ""),
                "prerelease": str(release.get("prerelease", False)),
                "type": "release"
            }
        })
    return items


def fetch_issues(repo: str) -> list[dict]:
    """Fetch recently opened high-engagement issues."""
    data = gh_get(
        f"{GITHUB_API}/repos/{repo}/issues?state=open&sort=created"
        f"&direction=desc&per_page=10"
    )
    if not data:
        return []

    cutoff = days_ago(LOOKBACK_DAYS)
    items = []
    for issue in data:
        # Skip pull requests (GitHub returns them in issues endpoint)
        if "pull_request" in issue:
            continue
        if (issue.get("comments", 0) < 3) and (issue.get("reactions", {}).get("total_count", 0) < 5):
            continue

        created = issue.get("created_at", "")
        try:
            pub_dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
        except ValueError:
            continue
        if pub_dt < cutoff:
            continue

        body = issue.get("body", "") or ""
        summary = body[:400].strip() if body else "_No description._"
        labels = [l["name"] for l in issue.get("labels", [])]

        items.append({
            "title": f"[Issue] {repo} #{issue.get('number')}: {issue.get('title', '')}",
            "url": issue.get("html_url", ""),
            "source": "github",
            "published_at": created,
            "summary": summary,
            "extra": {
                "repo": repo,
                "comments": str(issue.get("comments", 0)),
                "labels": ", ".join(labels) if labels else "none",
                "type": "issue"
            }
        })
    return items[:3]  # Cap issues per repo to avoid noise


def run(dry_run: bool = False, date_str: str | None = None) -> int:
    print("[github] Starting fetch...")
    config = load_config("sources.json")
    repos = [r for r in config.get("github", []) if r.get("enabled", True)]

    if not repos:
        print("[github] No enabled repos in sources.json")
        update_last_run("source-collector-github", "skipped", "no enabled repos")
        return 0

    seen = load_seen_items()
    all_items = []

    for repo_cfg in repos:
        repo = repo_cfg["repo"]
        watch = repo_cfg.get("watch", ["releases"])
        print(f"[github] Fetching {repo} ({', '.join(watch)})...")

        if "releases" in watch:
            for item in fetch_releases(repo):
                h = item_hash("github", item["url"], item["title"])
                if is_seen(h, seen):
                    print(f"  [skip] Already seen: {item['title'][:60]}")
                    continue
                mark_seen(h, seen)
                all_items.append(item)
                print(f"  [+] {item['title'][:70]}")

        if "issues" in watch:
            for item in fetch_issues(repo):
                h = item_hash("github", item["url"], item["title"])
                if is_seen(h, seen):
                    continue
                mark_seen(h, seen)
                all_items.append(item)
                print(f"  [+] {item['title'][:70]}")

    print(f"[github] Collected {len(all_items)} new items")

    if dry_run:
        print("\n--- DRY RUN OUTPUT ---")
        for item in all_items:
            print(f"  {item['title']}")
        return len(all_items)

    if not dry_run:
        save_seen_items(seen)

    if all_items:
        out = write_raw_output("github", all_items, date_str)
        print(f"[github] Written to {out}")
    else:
        print("[github] No new items — skipping file write")

    update_last_run("source-collector-github", "success", f"{len(all_items)} items")
    return len(all_items)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch GitHub data for SmartDigest")
    parser.add_argument("--dry-run", action="store_true", help="Print items without writing files")
    parser.add_argument("--date", help="Target date YYYY-MM-DD (default: today)")
    args = parser.parse_args()
    count = run(dry_run=args.dry_run, date_str=args.date)
    print(f"[github] Done. {count} items.")
