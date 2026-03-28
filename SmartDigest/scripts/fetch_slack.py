from __future__ import annotations
"""
fetch_slack.py — Reads messages from configured Slack channels for EOD digest.

Requires:
    pip install slack-sdk
    export SMARTDIGEST_SLACK_BOT_TOKEN=xoxb-...

Bot needs scopes: channels:history, channels:read, groups:history, groups:read

Usage:
    python scripts/fetch_slack.py
    python scripts/fetch_slack.py --dry-run
    python scripts/fetch_slack.py --hours 8    # look back 8 hours
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import get_project_root, load_config, update_last_run, now_iso


def get_slack_client():
    try:
        from slack_sdk import WebClient
    except ImportError:
        print("[slack] ERROR: slack-sdk not installed. Run: pip install slack-sdk", file=sys.stderr)
        sys.exit(1)
    token = os.environ.get("SMARTDIGEST_SLACK_BOT_TOKEN", "")
    if not token:
        print("[slack] ERROR: SMARTDIGEST_SLACK_BOT_TOKEN not set.", file=sys.stderr)
        sys.exit(1)
    return WebClient(token=token)


def fetch_channel_messages(client, channel_id: str, channel_name: str,
                            hours_back: int = 12) -> list[dict]:
    oldest = (datetime.now(timezone.utc) - timedelta(hours=hours_back)).timestamp()
    messages = []
    try:
        resp = client.conversations_history(
            channel=channel_id,
            oldest=str(oldest),
            limit=100
        )
        for msg in resp.get("messages", []):
            # Skip bot messages and channel join notifications
            if msg.get("subtype") in ("channel_join", "bot_message"):
                continue
            if not msg.get("text", "").strip():
                continue

            ts = float(msg.get("ts", 0))
            dt = datetime.fromtimestamp(ts, tz=timezone.utc)
            reactions = msg.get("reactions", [])
            reaction_count = sum(r.get("count", 0) for r in reactions)
            reply_count = msg.get("reply_count", 0)

            messages.append({
                "text": msg["text"][:500],
                "user": msg.get("user", "unknown"),
                "timestamp": dt.isoformat(),
                "channel": channel_name,
                "reactions": reaction_count,
                "replies": reply_count,
                "thread_ts": msg.get("thread_ts", ""),
                "is_threaded": bool(msg.get("thread_ts"))
            })

    except Exception as e:
        print(f"[slack] Error fetching {channel_name}: {e}", file=sys.stderr)
    return messages


def summarize_channel(messages: list[dict], channel_name: str) -> dict:
    """Create a structured summary of channel activity."""
    if not messages:
        return {"channel": channel_name, "message_count": 0, "highlights": []}

    # Sort by engagement (reactions + replies)
    sorted_msgs = sorted(
        messages,
        key=lambda m: m["reactions"] + m["replies"],
        reverse=True
    )

    highlights = []
    for msg in sorted_msgs[:5]:
        highlights.append({
            "text": msg["text"][:300],
            "timestamp": msg["timestamp"],
            "engagement": msg["reactions"] + msg["replies"]
        })

    return {
        "channel": channel_name,
        "message_count": len(messages),
        "active_since": messages[-1]["timestamp"] if messages else "",
        "highlights": highlights,
        "top_message": sorted_msgs[0]["text"][:400] if sorted_msgs else ""
    }


def run(hours_back: int = 12, dry_run: bool = False) -> list[dict]:
    print(f"[slack] Fetching messages from last {hours_back}h...")

    cfg_path = get_project_root() / "config" / "slack_channels.json"
    if not cfg_path.exists():
        print("[slack] No slack_channels.json found.", file=sys.stderr)
        update_last_run("fetch-slack", "skipped", "no config file")
        return []

    channels_cfg = json.loads(cfg_path.read_text())
    channels = [c for c in channels_cfg.get("channels", []) if c.get("enabled", True)]

    if not channels:
        print("[slack] No enabled channels configured.")
        return []

    client = get_slack_client()
    all_summaries = []

    for ch in channels:
        channel_id = ch.get("id", "")
        channel_name = ch.get("name", channel_id)
        print(f"[slack] → Reading #{channel_name}...")

        msgs = fetch_channel_messages(client, channel_id, channel_name, hours_back)
        summary = summarize_channel(msgs, channel_name)
        all_summaries.append(summary)
        print(f"  {len(msgs)} messages, {len(summary['highlights'])} highlights")

    if dry_run:
        for s in all_summaries:
            print(f"\n#{s['channel']} ({s['message_count']} msgs):")
            for h in s["highlights"]:
                print(f"  [{h['engagement']}⭐] {h['text'][:80]}...")
        return all_summaries

    # Save
    out_path = get_project_root() / "data" / "eod" / "slack_digest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps({
        "fetched_at": now_iso(),
        "hours_back": hours_back,
        "channels": all_summaries
    }, indent=2))
    print(f"[slack] ✅ Saved to {out_path}")
    update_last_run("fetch-slack", "success",
                    f"{sum(s['message_count'] for s in all_summaries)} messages across {len(channels)} channels")
    return all_summaries


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--hours", type=int, default=12, help="Hours to look back")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(hours_back=args.hours, dry_run=args.dry_run)
