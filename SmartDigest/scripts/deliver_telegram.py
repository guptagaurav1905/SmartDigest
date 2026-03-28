"""
deliver_telegram.py — Reads today's ranked.json and delivers the briefing to Telegram.

Usage:
    python scripts/deliver_telegram.py
    python scripts/deliver_telegram.py --date 2024-01-15
    python scripts/deliver_telegram.py --preview   # print to terminal, don't send

Requires env vars:
    SMARTDIGEST_TELEGRAM_BOT_TOKEN
    SMARTDIGEST_TELEGRAM_CHAT_ID
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Union

sys.path.insert(0, str(Path(__file__).parent))
from utils import get_project_root, load_config, update_last_run, today_str, now_iso

TELEGRAM_API = "https://api.telegram.org"
MAX_MSG_LENGTH = 4000   # Telegram limit is 4096, keep safe margin


def escape_md(text: str) -> str:
    """Escape special characters for Telegram Markdown (V1 — simpler, more forgiving)."""
    # Only escape characters that break Markdown v1
    for ch in ['_', '*', '`', '[']:
        text = text.replace(ch, f'\\{ch}')
    return text


def score_to_stars(score: float) -> str:
    if score >= 9.0:
        return "⭐⭐"
    elif score >= 7.0:
        return "⭐"
    return ""


def format_source_emoji(source: str) -> str:
    return {
        "github": "🐙",
        "hackernews": "🔶",
        "arxiv": "📄",
        "rss": "📰",
    }.get(source, "🔗")


def build_telegram_message(ranked: dict) -> list[str]:
    """
    Build the briefing text. Returns a list of message chunks
    (Telegram has a 4096 char limit per message).
    """
    date_str = ranked.get("date", today_str())
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        friendly_date = dt.strftime("%a, %b %d %Y")
    except ValueError:
        friendly_date = date_str

    items = ranked.get("items", [])
    count = ranked.get("items_above_threshold", len(items))
    scorer = ranked.get("scorer", "claude")

    # Header
    header = (
        f"☀️ *SmartDigest — {friendly_date}*\n"
        f"_{count} items above relevance threshold_\n\n"
    )

    chunks = []
    current = header

    for item in items:
        rank = item.get("rank", "?")
        title = item.get("title", "Untitled")
        url = item.get("url", "")
        source = item.get("source", "unknown")
        score = item.get("score", 0)
        reason = item.get("reason", "")
        summary = item.get("summary", "")
        published = item.get("published_at", "")

        # Format published date nicely
        pub_short = ""
        if published and published != "unknown":
            try:
                pub_dt = datetime.fromisoformat(published.replace("Z", "+00:00"))
                pub_short = pub_dt.strftime("%b %d")
            except ValueError:
                pub_short = published[:10]

        stars = score_to_stars(score)
        src_emoji = format_source_emoji(source)

        # Build item block
        item_text = (
            f"*{rank}. [{title}]({url})* {stars}\n"
            f"{src_emoji} `{source}`"
        )
        if pub_short:
            item_text += f" · {pub_short}"
        item_text += f"\n"

        if reason:
            item_text += f"_{reason}_\n"

        # Add a snippet of summary (keep it short for readability)
        if summary and summary != "_No summary._":
            snippet = summary[:200].strip()
            if len(summary) > 200:
                snippet += "..."
            item_text += f"{snippet}\n"

        item_text += "\n"

        # Chunk if we'd exceed limit
        if len(current) + len(item_text) > MAX_MSG_LENGTH:
            chunks.append(current)
            current = item_text
        else:
            current += item_text

    # Footer
    footer = f"---\n_Scored by SmartDigest · {scorer}_"
    if len(current) + len(footer) > MAX_MSG_LENGTH:
        chunks.append(current)
        chunks.append(footer)
    else:
        current += footer
        chunks.append(current)

    return chunks


def send_telegram_message(text: str, token: str, chat_id: str,
                           max_attempts: int = 3, backoff: int = 5) -> bool:
    url = f"{TELEGRAM_API}/bot{token}/sendMessage"
    payload = json.dumps({
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": False
    }).encode("utf-8")

    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(
            url, data=payload,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                result = json.loads(resp.read())
                if result.get("ok"):
                    return True
                print(f"[telegram] API error: {result.get('description')}")
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"[telegram] HTTP {e.code}: {body}")
        except Exception as e:
            print(f"[telegram] Error (attempt {attempt}/{max_attempts}): {e}")

        if attempt < max_attempts:
            print(f"[telegram] Retrying in {backoff}s...")
            time.sleep(backoff)

    return False


def run(date_str: Union[str, None] = None, preview: bool = False) -> bool:
    if date_str is None:
        date_str = today_str()

    # Load ranked data
    ranked_path = get_project_root() / "data" / "scored" / date_str / "ranked.json"
    if not ranked_path.exists():
        # Try yesterday as fallback
        from datetime import timedelta
        yesterday = (datetime.strptime(date_str, "%Y-%m-%d") - timedelta(days=1)).strftime("%Y-%m-%d")
        ranked_path = get_project_root() / "data" / "scored" / yesterday / "ranked.json"
        if ranked_path.exists():
            print(f"[telegram] Using yesterday's data ({yesterday}) — today's not found")
            date_str = yesterday
        else:
            print(f"[telegram] ERROR: No scored data found for {date_str}")
            print(f"           Run the scorer first: python scripts/groq_scorer.py")
            update_last_run("briefing-composer", "failure", "no scored data")
            return False

    ranked = json.loads(ranked_path.read_text())
    items = ranked.get("items", [])

    if not items:
        print("[telegram] No items above threshold — nothing to deliver")
        update_last_run("briefing-composer", "skipped", "0 items above threshold")
        return True

    messages = build_telegram_message(ranked)

    print(f"[telegram] Built briefing: {len(items)} items, {len(messages)} message chunk(s)")

    if preview:
        print("\n" + "="*60)
        print("PREVIEW (not sending to Telegram):")
        print("="*60)
        for i, msg in enumerate(messages, 1):
            print(f"\n--- Chunk {i} ---")
            print(msg)
        print("="*60)
        return True

    # Get credentials
    token = os.environ.get("SMARTDIGEST_TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("SMARTDIGEST_TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("[telegram] ERROR: Missing env vars:")
        if not token: print("  export SMARTDIGEST_TELEGRAM_BOT_TOKEN=...")
        if not chat_id: print("  export SMARTDIGEST_TELEGRAM_CHAT_ID=...")
        return False

    cfg = load_config("delivery.json")
    retry_cfg = cfg.get("retry", {})
    max_attempts = retry_cfg.get("max_attempts", 3)
    backoff = retry_cfg.get("backoff_seconds", 5)

    # Send all chunks
    all_ok = True
    for i, msg in enumerate(messages, 1):
        print(f"[telegram] Sending chunk {i}/{len(messages)}...")
        ok = send_telegram_message(msg, token, chat_id, max_attempts, backoff)
        if ok:
            print(f"[telegram] ✅ Chunk {i} delivered")
        else:
            print(f"[telegram] ❌ Chunk {i} failed")
            all_ok = False
        if i < len(messages):
            time.sleep(1)  # Brief pause between chunks

    # Archive the briefing as Markdown
    archive_dir = get_project_root() / "data" / "briefings" / date_str
    archive_dir.mkdir(parents=True, exist_ok=True)
    archive_path = archive_dir / "briefing.md"
    archive_path.write_text("\n\n".join(messages))
    print(f"[telegram] Archived to {archive_path}")

    status = "success" if all_ok else "partial"
    update_last_run("briefing-composer", status,
                    f"{len(items)} items via telegram ({len(messages)} chunks)")
    return all_ok


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Deliver SmartDigest briefing to Telegram")
    parser.add_argument("--date", help="Date to deliver YYYY-MM-DD (default: today)")
    parser.add_argument("--preview", action="store_true",
                        help="Print briefing to terminal without sending")
    args = parser.parse_args()
    success = run(date_str=args.date, preview=args.preview)
    sys.exit(0 if success else 1)
