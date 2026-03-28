from __future__ import annotations
"""
test_db.py — Verifies that the SmartDigest SQLite database is working correctly.

Run this to confirm your DB is initialized, readable, and writable.
Also shows you how to query the DB directly.

Usage:
    python scripts/test_db.py             # full test suite
    python scripts/test_db.py --show      # just show what's in the DB today
    python scripts/test_db.py --reset     # wipe and reinitialize (fresh start)
"""

import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from db import Database
from utils import get_project_root, today_str


def print_section(title: str):
    print(f"\n{'─'*50}")
    print(f"  {title}")
    print('─'*50)


def run_full_test():
    print("\n🔍 SmartDigest DB Test Suite")
    print("=" * 50)

    db_path = get_project_root() / "db" / "smartdigest.db"

    # ── Step 1: Initialize ────────────────────────────────
    print_section("Step 1 — Initialize Database")
    db = Database()
    print(f"✅ DB file created at: {db_path}")
    print(f"   Size: {db_path.stat().st_size} bytes")

    # ── Step 2: Deduplication ─────────────────────────────
    print_section("Step 2 — Deduplication (seen_items)")
    db.mark_seen("hash_001", "hackernews", "Test HN Post", "https://hn.test/1")
    db.mark_seen("hash_002", "arxiv",      "Test arXiv Paper", "https://arxiv.test/2")
    db.mark_seen("hash_003", "github",     "Test Release", "https://github.test/3")

    assert db.is_seen("hash_001"),  "❌ hash_001 should be seen"
    assert not db.is_seen("hash_999"), "❌ hash_999 should NOT be seen"
    print("✅ mark_seen works")
    print("✅ is_seen works (true + false case)")

    # ── Step 3: Raw Items ─────────────────────────────────
    print_section("Step 3 — Raw Items")
    sample_items = [
        {
            "hash": "raw_001", "source": "hackernews",
            "title": "Show HN: SmartDigest — AI morning briefing agent",
            "url": "https://hn.test/show",
            "summary": "Built an autonomous briefing agent using OpenClaw and Groq.",
            "published_at": "2026-03-28T06:00:00Z",
            "extra": {"points": "342", "comments": "87"}
        },
        {
            "hash": "raw_002", "source": "arxiv",
            "title": "LLM Agents with Tool Use: A Survey",
            "url": "https://arxiv.org/abs/test.001",
            "summary": "Comprehensive survey of LLM agent architectures and tool use patterns.",
            "published_at": "2026-03-27T12:00:00Z",
            "extra": {"authors": "Smith et al.", "categories": "cs.AI"}
        },
        {
            "hash": "raw_003", "source": "rss",
            "title": "The Rise of Agentic AI Systems",
            "url": "https://blog.test/agentic-ai",
            "summary": "How autonomous AI agents are reshaping software development.",
            "published_at": "2026-03-28T08:00:00Z",
            "extra": {"feed": "Simon Willison's Weblog"}
        },
    ]

    inserted = 0
    for item in sample_items:
        if db.insert_raw_item(item, run_date=today_str()):
            inserted += 1

    fetched = db.get_raw_items(today_str())
    print(f"✅ Inserted {inserted} raw items")
    print(f"✅ Retrieved {len(fetched)} items from DB for today")
    for item in fetched:
        print(f"   [{item['source']:12}] {item['title'][:55]}")

    # ── Step 4: Scored Items ──────────────────────────────
    print_section("Step 4 — Scored Items")
    scores = [
        ("raw_001", 8.5, 1, "High engagement HN post on AI agents — direct match.", "groq/llama-3.3-70b"),
        ("raw_002", 9.2, 2, "arXiv survey on LLM tool use — top priority topic.",   "groq/llama-3.3-70b"),
        ("raw_003", 7.1, 3, "Relevant blog post on agentic AI from trusted source.", "groq/llama-3.3-70b"),
    ]

    for hash_, score, rank, reason, scorer in scores:
        db.insert_scored_item(hash_, score, rank, reason, scorer, run_date=today_str())

    scored = db.get_scored_items(today_str(), min_score=7.0)
    print(f"✅ Inserted {len(scores)} scored items")
    print(f"✅ Retrieved {len(scored)} items above score 7.0")
    for item in scored:
        print(f"   [{item['score']:4.1f}] #{item['rank']} {item['title'][:50]}")

    # ── Step 5: Pipeline Runs ─────────────────────────────
    print_section("Step 5 — Pipeline Run Logging")
    run_id = db.log_run_start("source-collector", today_str())
    db.log_run_complete(run_id, "success", "3 items collected", items_collected=3)

    run_id2 = db.log_run_start("relevance-scorer", today_str())
    db.log_run_complete(run_id2, "success", "3 scored, 3 above threshold", items_scored=3)

    summary = db.get_run_summary(today_str())
    print(f"✅ Logged {len(summary)} pipeline stages")
    for stage in summary:
        icon = "✅" if stage["status"] == "success" else "❌"
        print(f"   {icon} {stage['stage']:25} → {stage['detail']}")

    # ── Step 6: Briefings ─────────────────────────────────
    print_section("Step 6 — Briefing Archive")
    bid = db.save_briefing(
        content="🌅 SmartDigest SOD — Test briefing content here...",
        channel="telegram",
        briefing_type="sod",
        item_count=3,
        run_date=today_str()
    )
    print(f"✅ Briefing saved (ID: {bid})")

    retrieved = db.get_briefing(today_str(), "sod")
    print(f"✅ Briefing retrieved: channel={retrieved['channel']}, items={retrieved['item_count']}")

    # ── Step 7: Analytics ─────────────────────────────────
    print_section("Step 7 — Daily Stats")
    stats = db.get_daily_stats(today_str())
    print(f"✅ Daily stats for {stats['date']}:")
    print(f"   Raw items:     {stats['raw_items']}")
    print(f"   Scored items:  {stats['scored_items']}")
    print(f"   Avg score:     {stats['avg_score']}")
    print(f"   By source:     {stats['by_source']}")

    # ── Step 8: Direct SQL Query ──────────────────────────
    print_section("Step 8 — Direct SQL Query (query_db tool)")
    rows = db.query("SELECT source, COUNT(*) as count FROM raw_items GROUP BY source", limit=10)
    print("✅ Direct SQL works:")
    for row in rows:
        print(f"   {row['source']:15} → {row['count']} items")

    # ── Step 9: Dedup Pruning ─────────────────────────────
    print_section("Step 9 — Pruning Old Entries")
    pruned = db.prune_seen_items(days=7)
    print(f"✅ Prune ran (removed {pruned} entries older than 7 days)")

    # ── Final Summary ─────────────────────────────────────
    print(f"\n{'='*50}")
    print("  ✅ ALL TESTS PASSED — DB is working correctly!")
    print(f"  📁 DB location: {db_path}")
    print(f"  📊 File size:   {db_path.stat().st_size:,} bytes")
    print('='*50)


def show_current_data():
    """Show a snapshot of what's currently in the DB."""
    print("\n📊 SmartDigest DB — Current State")
    print("=" * 50)
    db = Database()
    date = today_str()

    stats = db.get_daily_stats(date)
    print(f"\n📅 Today ({date}):")
    print(f"   Raw items collected : {stats['raw_items']}")
    print(f"   Items scored        : {stats['scored_items']}")
    print(f"   Average score       : {stats['avg_score']}")
    if stats['by_source']:
        print(f"   Sources             : {stats['by_source']}")

    runs = db.get_run_summary(date)
    if runs:
        print(f"\n⚙️  Pipeline Runs ({len(runs)} stages):")
        for r in runs:
            icon = "✅" if r["status"] == "success" else ("⚠️" if r["status"] == "skipped" else "❌")
            print(f"   {icon} {r['stage']:25} {r['status']:10} — {r.get('detail','')[:50]}")
    else:
        print("\n⚙️  No pipeline runs logged today yet.")

    briefing = db.get_briefing(date, "sod")
    if briefing:
        print(f"\n📨 SOD Briefing: {briefing['item_count']} items via {briefing['channel']} at {briefing['delivered_at'][:19]}")
    else:
        print("\n📨 No SOD briefing delivered today yet.")

    scored = db.get_scored_items(date, min_score=6.0, limit=5)
    if scored:
        print(f"\n🔥 Top scored items today (threshold 6.0):")
        for item in scored:
            print(f"   [{item['score']:4.1f}] {item['title'][:60]}")
    else:
        print("\n🔥 No scored items in DB yet for today.")

    print("\n💡 Tip: run 'python scripts/test_db.py' to run the full test suite")


def reset_db():
    db_path = get_project_root() / "db" / "smartdigest.db"
    if db_path.exists():
        db_path.unlink()
        print(f"🗑️  Deleted {db_path}")
    db = Database()
    print(f"✅ Fresh database initialized at {db_path}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SmartDigest DB verification")
    parser.add_argument("--show",  action="store_true", help="Show current DB contents")
    parser.add_argument("--reset", action="store_true", help="Wipe and reinitialize DB")
    args = parser.parse_args()

    if args.reset:
        reset_db()
    elif args.show:
        show_current_data()
    else:
        run_full_test()
