from __future__ import annotations
"""
deliver_whatsapp.py — Delivers SmartDigest briefings via WhatsApp using Twilio.

Twilio WhatsApp Sandbox (free for testing):
  1. pip install twilio
  2. Sign up at https://www.twilio.com (free)
  3. Go to Messaging → Try it out → Send a WhatsApp message
  4. Send "join <sandbox-keyword>" to +1 415 523 8886 on WhatsApp
  5. Set env vars below

Required env vars:
    TWILIO_ACCOUNT_SID          (from Twilio Console)
    TWILIO_AUTH_TOKEN           (from Twilio Console)
    SMARTDIGEST_WHATSAPP_FROM   (e.g. whatsapp:+14155238886  — Twilio sandbox number)
    SMARTDIGEST_WHATSAPP_TO     (e.g. whatsapp:+919876543210 — your number with country code)

Usage:
    python scripts/deliver_whatsapp.py --type sod
    python scripts/deliver_whatsapp.py --type eod
    python scripts/deliver_whatsapp.py --preview
"""

import argparse
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import get_project_root, update_last_run, today_str, now_iso

MAX_MSG_LEN = 1600   # WhatsApp practical limit per message


def get_twilio_client():
    try:
        from twilio.rest import Client
    except ImportError:
        print("[whatsapp] ERROR: Run: pip install twilio", file=sys.stderr)
        sys.exit(1)

    sid   = os.environ.get("TWILIO_ACCOUNT_SID", "")
    token = os.environ.get("TWILIO_AUTH_TOKEN", "")
    if not sid or not token:
        print("[whatsapp] ERROR: Set TWILIO_ACCOUNT_SID and TWILIO_AUTH_TOKEN", file=sys.stderr)
        sys.exit(1)
    return Client(sid, token)


def get_whatsapp_numbers() -> tuple[str, str]:
    from_num = os.environ.get("SMARTDIGEST_WHATSAPP_FROM", "")
    to_num   = os.environ.get("SMARTDIGEST_WHATSAPP_TO", "")
    if not from_num or not to_num:
        print("[whatsapp] ERROR: Set SMARTDIGEST_WHATSAPP_FROM and SMARTDIGEST_WHATSAPP_TO", file=sys.stderr)
        sys.exit(1)
    # Ensure whatsapp: prefix
    if not from_num.startswith("whatsapp:"):
        from_num = f"whatsapp:{from_num}"
    if not to_num.startswith("whatsapp:"):
        to_num = f"whatsapp:{to_num}"
    return from_num, to_num


def format_sod_whatsapp(date_str: str) -> str:
    """Load and format SOD briefing for WhatsApp (plain text, emoji-friendly)."""
    data_dir = get_project_root() / "data" / "sod"
    lines = []

    # Header
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        lines.append(f"🌅 *SmartDigest Morning Brief — {dt.strftime('%a %b %d')}*\n")
    except Exception:
        lines.append(f"🌅 *SmartDigest Morning Brief — {date_str}*\n")

    # Weather
    weather_path = data_dir / "weather.json"
    if weather_path.exists():
        w = json.loads(weather_path.read_text())
        c = w["current"]
        t = w["today"]
        lines.append(
            f"☀️ *Weather — {w['city']}*\n"
            f"{c['icon']} {c['temp_c']}°C, {c['description']}\n"
            f"High {t['max_c']}°C / Low {t['min_c']}°C\n"
        )

    # Calendar
    cal_path = data_dir / "calendar.json"
    if cal_path.exists():
        cal = json.loads(cal_path.read_text())
        events = cal.get("events", [])
        if events:
            lines.append(f"📅 *Today's Meetings ({len(events)}):*")
            for ev in events[:5]:
                lines.append(f"  🕐 {ev['time']} — {ev['title']}")
                if ev.get("meet_link"):
                    lines.append(f"     🔗 {ev['meet_link']}")
            lines.append("")
        else:
            lines.append("📅 No meetings today!\n")

    # Gmail
    gmail_path = data_dir / "gmail.json"
    if gmail_path.exists():
        gm = json.loads(gmail_path.read_text())
        emails = gm.get("emails", [])
        important = [e for e in emails if e.get("is_important")]
        lines.append(f"📧 *Gmail — {len(emails)} unread*")
        if important:
            for e in important[:3]:
                lines.append(f"  ⭐ {e['subject'][:50]}")
        lines.append("")

    # Top tech items
    scored_path = get_project_root() / "data" / "scored" / date_str / "ranked.json"
    if scored_path.exists():
        ranked = json.loads(scored_path.read_text())
        items  = ranked.get("items", [])[:5]
        if items:
            lines.append(f"🔥 *Top Tech ({len(items)} picks):*")
            for i, item in enumerate(items, 1):
                score = item.get("score", 0)
                stars = "⭐⭐" if score >= 9 else ("⭐" if score >= 7 else "")
                lines.append(f"  {i}. {item['title'][:60]} {stars}")
                lines.append(f"     {item['url']}")
            lines.append("")

    lines.append("_Powered by SmartDigest_ 🤖")
    return "\n".join(lines)


def format_eod_whatsapp(date_str: str) -> str:
    """Load and format EOD briefing for WhatsApp."""
    lines = []
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        lines.append(f"🌙 *SmartDigest Evening Brief — {dt.strftime('%a %b %d')}*\n")
    except Exception:
        lines.append(f"🌙 *SmartDigest Evening Brief — {date_str}*\n")

    # Slack digest
    slack_path = get_project_root() / "data" / "eod" / "slack_digest.json"
    if slack_path.exists():
        slack = json.loads(slack_path.read_text())
        channels = slack.get("channels", [])
        total_msgs = sum(c.get("message_count", 0) for c in channels)
        lines.append(f"💬 *Slack Digest — {total_msgs} messages*")
        for ch in channels:
            if ch.get("highlights"):
                lines.append(f"\n  *#{ch['channel']}* ({ch['message_count']} msgs):")
                top = ch["highlights"][0]
                lines.append(f"  💬 {top['text'][:150]}...")
        lines.append("")

    # Top scored tech items from today
    scored_path = get_project_root() / "data" / "scored" / date_str / "ranked.json"
    if scored_path.exists():
        ranked = json.loads(scored_path.read_text())
        items = ranked.get("items", [])[:5]
        if items:
            lines.append(f"🔥 *Today's Tech Highlights:*")
            for i, item in enumerate(items, 1):
                lines.append(f"  {i}. {item['title'][:60]}")
                lines.append(f"     📎 {item['url']}")
            lines.append("")

    lines.append("_SmartDigest EOD — see you tomorrow!_ 👋")
    return "\n".join(lines)


def send_whatsapp(text: str, from_num: str, to_num: str, client,
                   max_attempts: int = 3) -> bool:
    # Split into chunks if needed
    chunks = [text[i:i+MAX_MSG_LEN] for i in range(0, len(text), MAX_MSG_LEN)]

    for idx, chunk in enumerate(chunks):
        for attempt in range(1, max_attempts + 1):
            try:
                msg = client.messages.create(
                    from_=from_num,
                    to=to_num,
                    body=chunk
                )
                print(f"[whatsapp] ✅ Chunk {idx+1}/{len(chunks)} sent (SID: {msg.sid})")
                break
            except Exception as e:
                print(f"[whatsapp] Attempt {attempt}/{max_attempts} failed: {e}", file=sys.stderr)
                if attempt < max_attempts:
                    time.sleep(3)
                else:
                    return False
        if len(chunks) > 1:
            time.sleep(1)

    return True


def run(briefing_type: str = "sod", date_str: str | None = None,
        preview: bool = False) -> bool:
    date_str = date_str or today_str()
    print(f"[whatsapp] Composing {briefing_type.upper()} briefing for {date_str}...")

    if briefing_type == "sod":
        text = format_sod_whatsapp(date_str)
    else:
        text = format_eod_whatsapp(date_str)

    if preview:
        print("\n--- WhatsApp Preview ---")
        print(text)
        print("--- End Preview ---")
        return True

    client = get_twilio_client()
    from_num, to_num = get_whatsapp_numbers()
    print(f"[whatsapp] Sending to {to_num}...")

    success = send_whatsapp(text, from_num, to_num, client)
    status = "success" if success else "failure"
    detail = f"sent to Twilio → {to_num}" if success else f"failed to send to {to_num}"
    update_last_run(f"whatsapp-{briefing_type}", status, detail)
    return success


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--type", choices=["sod", "eod"], default="sod")
    parser.add_argument("--date", help="YYYY-MM-DD")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    ok = run(briefing_type=args.type, date_str=args.date, preview=args.preview)
    sys.exit(0 if ok else 1)
