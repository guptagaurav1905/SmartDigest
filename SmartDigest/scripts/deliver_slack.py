from __future__ import annotations
"""
deliver_slack.py — Posts SmartDigest briefings TO Slack channels via webhooks.

Uses Slack Incoming Webhooks (no bot token needed for posting).

Setup:
  1. Go to api.slack.com/apps → Create App → From scratch
  2. Enable "Incoming Webhooks"
  3. Add to Workspace → Pick your #smartdigest-sod or #smartdigest-eod channel
  4. Copy the webhook URL

Required env vars:
    SMARTDIGEST_SLACK_SOD_WEBHOOK   — webhook URL for SOD channel
    SMARTDIGEST_SLACK_EOD_WEBHOOK   — webhook URL for EOD channel

Usage:
    python scripts/deliver_slack.py --type sod
    python scripts/deliver_slack.py --type eod
    python scripts/deliver_slack.py --preview
"""

import argparse
import json
import os
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import get_project_root, update_last_run, today_str, now_iso


def get_webhook(briefing_type: str) -> str:
    key = f"SMARTDIGEST_SLACK_{'SOD' if briefing_type == 'sod' else 'EOD'}_WEBHOOK"
    url = os.environ.get(key, "")
    if not url:
        print(f"[slack-post] ERROR: {key} not set.", file=sys.stderr)
        sys.exit(1)
    return url


def build_sod_blocks(date_str: str) -> list[dict]:
    """Build Slack Block Kit payload for SOD briefing."""
    data_dir = get_project_root() / "data" / "sod"
    blocks   = []

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        header_text = f"🌅 SmartDigest — {dt.strftime('%A, %B %d %Y')}"
    except Exception:
        header_text = f"🌅 SmartDigest — {date_str}"

    blocks.append({"type": "header", "text": {"type": "plain_text", "text": header_text}})
    blocks.append({"type": "divider"})

    # Weather block
    weather_path = data_dir / "weather.json"
    if weather_path.exists():
        w = json.loads(weather_path.read_text())
        c = w["current"]
        t = w["today"]
        blocks.append({
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"{c['icon']} *Weather — {w['city']}*\n"
                    f"`{c['temp_c']}°C` {c['description']} · "
                    f"High {t['max_c']}°C / Low {t['min_c']}°C · "
                    f"💧 {c['humidity_pct']}% humidity"
                )
            }
        })

    # Calendar block
    cal_path = data_dir / "calendar.json"
    if cal_path.exists():
        events = json.loads(cal_path.read_text()).get("events", [])
        if events:
            cal_text = f"📅 *Today's Meetings ({len(events)})*\n"
            for ev in events[:6]:
                meet = f" <{ev['meet_link']}|Join>" if ev.get("meet_link") else ""
                cal_text += f"• `{ev['time']}` {ev['title']}{meet}\n"
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": cal_text.strip()}
            })
        blocks.append({"type": "divider"})

    # Gmail block
    gmail_path = data_dir / "gmail.json"
    if gmail_path.exists():
        emails = json.loads(gmail_path.read_text()).get("emails", [])
        important = [e for e in emails if e.get("is_important")]
        gmail_text = f"📧 *Gmail — {len(emails)} unread*"
        if important:
            gmail_text += f" ({len(important)} important)\n"
            for e in important[:3]:
                gmail_text += f"  ⭐ *{e['subject'][:60]}*\n"
        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": gmail_text}
        })
        blocks.append({"type": "divider"})

    # Top tech items
    scored_path = get_project_root() / "data" / "scored" / date_str / "ranked.json"
    if scored_path.exists():
        items = json.loads(scored_path.read_text()).get("items", [])[:5]
        if items:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": f"🔥 *Top Tech Picks ({len(items)})*"}
            })
            for item in items:
                score = item.get("score", 0)
                stars = "⭐⭐" if score >= 9 else ("⭐" if score >= 7 else "")
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*<{item['url']}|{item['title'][:80]}>* {stars}\n`{item['source']}` · {score}/10 — _{item.get('reason', '')[:100]}_"
                    }
                })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"_SmartDigest SOD · {now_iso()}_"}]
    })
    return blocks


def build_eod_blocks(date_str: str) -> list[dict]:
    """Build Slack Block Kit payload for EOD briefing."""
    blocks = []

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        header_text = f"🌙 SmartDigest EOD — {dt.strftime('%A, %B %d')}"
    except Exception:
        header_text = f"🌙 SmartDigest EOD — {date_str}"

    blocks.append({"type": "header", "text": {"type": "plain_text", "text": header_text}})
    blocks.append({"type": "divider"})

    # Slack digest from channels
    slack_path = get_project_root() / "data" / "eod" / "slack_digest.json"
    if slack_path.exists():
        slack_data = json.loads(slack_path.read_text())
        channels   = slack_data.get("channels", [])
        total_msgs = sum(c.get("message_count", 0) for c in channels)

        blocks.append({
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"💬 *Slack Digest — {total_msgs} messages across {len(channels)} channels*"}
        })

        for ch in channels:
            if not ch.get("highlights"):
                continue
            ch_text = f"*#{ch['channel']}* ({ch['message_count']} msgs)\n"
            for h in ch["highlights"][:2]:
                ch_text += f"> {h['text'][:150]}...\n"
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": ch_text}
            })
        blocks.append({"type": "divider"})

    # Tech highlights
    scored_path = get_project_root() / "data" / "scored" / date_str / "ranked.json"
    if scored_path.exists():
        items = json.loads(scored_path.read_text()).get("items", [])[:5]
        if items:
            blocks.append({
                "type": "section",
                "text": {"type": "mrkdwn", "text": "🔥 *Today's Top Tech*"}
            })
            for item in items:
                blocks.append({
                    "type": "section",
                    "text": {
                        "type": "mrkdwn",
                        "text": f"*<{item['url']}|{item['title'][:80]}>*\n`{item['source']}` · {item.get('score', 0)}/10"
                    }
                })

    blocks.append({"type": "divider"})
    blocks.append({
        "type": "context",
        "elements": [{"type": "mrkdwn", "text": f"_SmartDigest EOD · {now_iso()}_"}]
    })
    return blocks


def post_to_slack(webhook_url: str, blocks: list[dict],
                   fallback_text: str, max_attempts: int = 3) -> bool:
    payload = json.dumps({
        "text": fallback_text,
        "blocks": blocks
    }).encode("utf-8")

    for attempt in range(1, max_attempts + 1):
        req = urllib.request.Request(
            webhook_url, data=payload,
            headers={"Content-Type": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode()
                if body == "ok":
                    return True
                print(f"[slack-post] Unexpected response: {body}", file=sys.stderr)
        except Exception as e:
            print(f"[slack-post] Attempt {attempt}/{max_attempts}: {e}", file=sys.stderr)
            if attempt < max_attempts:
                time.sleep(3)
    return False


def run(briefing_type: str = "sod", date_str: str | None = None,
        preview: bool = False) -> bool:
    date_str = date_str or today_str()
    print(f"[slack-post] Building {briefing_type.upper()} briefing for {date_str}...")

    if briefing_type == "sod":
        blocks = build_sod_blocks(date_str)
        fallback = f"SmartDigest SOD — {date_str}"
    else:
        blocks = build_eod_blocks(date_str)
        fallback = f"SmartDigest EOD — {date_str}"

    if preview:
        print(json.dumps({"text": fallback, "blocks": blocks}, indent=2))
        return True

    webhook = get_webhook(briefing_type)
    success = post_to_slack(webhook, blocks, fallback)

    status = "success" if success else "failure"
    update_last_run(f"slack-post-{briefing_type}", status, f"posted to Slack {briefing_type.upper()}")
    if success:
        print(f"[slack-post] ✅ {briefing_type.upper()} posted to Slack")
    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["sod", "eod"], default="sod")
    parser.add_argument("--date", help="YYYY-MM-DD")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    ok = run(briefing_type=args.type, date_str=args.date, preview=args.preview)
    sys.exit(0 if ok else 1)
