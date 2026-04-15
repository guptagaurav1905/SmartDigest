from __future__ import annotations
"""
compose_sod.py — Composes the Start-of-Day briefing from all SOD data sources
and orchestrates delivery to configured channels.

Sources:   weather.json + calendar.json + gmail.json + ranked.json
Delivers:  Telegram + WhatsApp + Slack (based on delivery.json config)

Usage:
    python scripts/compose_sod.py
    python scripts/compose_sod.py --preview
    python scripts/compose_sod.py --channels telegram whatsapp
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import get_project_root, load_config, update_last_run, today_str, now_iso


def compose_sod_markdown(date_str: str) -> str:
    """Build the canonical Markdown SOD briefing (used for archiving)."""
    data_dir = get_project_root() / "data" / "sod"
    lines    = []

    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        lines.append(f"# 🌅 SmartDigest — {dt.strftime('%A, %B %d %Y')}")
    except Exception:
        lines.append(f"# 🌅 SmartDigest — {date_str}")
    lines.append(f"_Generated: {now_iso()}_\n")
    lines.append("---\n")

    # ── Weather ──────────────────────────────────────────────
    weather_path = data_dir / "weather.json"
    if weather_path.exists():
        w = json.loads(weather_path.read_text())
        c = w["current"]
        t = w["today"]
        lines.append(f"## {c['icon']} Weather — {w['city']}")
        lines.append(f"**Now:** {c['temp_c']}°C (feels {c['feels_like_c']}°C) · {c['description']}")
        lines.append(f"**Today:** High {t['max_c']}°C / Low {t['min_c']}°C · 💧 {c['humidity_pct']}% humidity · 💨 {c['wind_kmph']} km/h")
        hourly = t.get("hourly_forecast", [])
        if hourly:
            lines.append("**Forecast:** " + " · ".join(
                f"{s['icon']} {s['time']} {s['temp_c']}°C" for s in hourly
            ))
        lines.append("")

    # ── Calendar ─────────────────────────────────────────────
    cal_path = data_dir / "calendar.json"
    if cal_path.exists():
        events = json.loads(cal_path.read_text()).get("events", [])
        lines.append(f"## 📅 Today's Calendar ({len(events)} events)")
        if events:
            for ev in events:
                icon = "🕐" if not ev.get("is_allday") else "📌"
                line = f"- {icon} **{ev['time']}** — {ev['title']}"
                if ev.get("duration_min"):
                    h, m = divmod(ev["duration_min"], 60)
                    line += f" _({h}h {m}m)_" if h else f" _({m}m)_"
                lines.append(line)
                if ev.get("location"):
                    lines.append(f"  - 📍 {ev['location']}")
                if ev.get("attendees"):
                    lines.append(f"  - 👥 {', '.join(ev['attendees'][:3])}")
                if ev.get("meet_link"):
                    lines.append(f"  - 🔗 [Join Meet]({ev['meet_link']})")
        else:
            lines.append("_No meetings today!_ 🎉")
        lines.append("")

    # ── Gmail ─────────────────────────────────────────────────
    gmail_path = data_dir / "gmail.json"
    if gmail_path.exists():
        emails = json.loads(gmail_path.read_text()).get("emails", [])
        important = [e for e in emails if e.get("is_important")]
        lines.append(f"## 📧 Gmail — {len(emails)} Unread")
        if important:
            lines.append(f"**⭐ Important ({len(important)}):**")
            for e in important[:5]:
                lines.append(f"- **{e['subject'][:70]}**")
                lines.append(f"  _From: {e['from'][:50]}_")
                lines.append(f"  {e['snippet'][:150]}...")
        others = [e for e in emails if not e.get("is_important")]
        if others:
            lines.append(f"\n**Other ({len(others)}):**")
            for e in others[:5]:
                lines.append(f"- {e['subject'][:70]} — _{e['from'][:40]}_")
        lines.append("")

    # ── Tech News ─────────────────────────────────────────────
    scored_path = get_project_root() / "data" / "scored" / date_str / "ranked.json"
    if scored_path.exists():
        ranked = json.loads(scored_path.read_text())
        items  = ranked.get("items", [])
        threshold = ranked.get("threshold", 6.0)
        lines.append(f"## 🔥 Top Tech Today ({len(items)} picks · threshold {threshold})")
        for item in items:
            score = item.get("score", 0)
            stars = "⭐⭐" if score >= 9 else ("⭐" if score >= 7 else "")
            lines.append(f"\n### {item['rank']}. [{item['title']}]({item['url']}) {stars}")
            lines.append(f"**Source:** `{item['source']}` · **Score:** {score}/10")
            lines.append(f"_{item.get('reason', '')}_")
            if item.get("summary"):
                lines.append(f"\n{item['summary'][:300]}...")
    lines.append("\n---")
    lines.append(f"_SmartDigest SOD · Powered by OpenClaw_")
    return "\n".join(lines)


def deliver_sod(date_str: str, channels: list[str], preview: bool = False) -> dict:
    results = {}

    if preview:
        print(compose_sod_markdown(date_str))
        return {"preview": True}

    if "telegram" in channels:
        try:
            from deliver_telegram import run as tg_run
            ok = tg_run(date_str=date_str, preview=False)
            results["telegram"] = "success" if ok else "failure"
            print(f"[sod] Telegram: {'✅' if ok else '❌'}")
        except Exception as e:
            results["telegram"] = f"error: {e}"
            print(f"[sod] Telegram error: {e}")

    if "whatsapp" in channels:
        try:
            from deliver_whatsapp import run as wa_run
            ok = wa_run(briefing_type="sod", date_str=date_str)
            results["whatsapp"] = "success" if ok else "failure"
            print(f"[sod] WhatsApp: {'✅' if ok else '❌'}")
        except Exception as e:
            results["whatsapp"] = f"error: {e}"
            print(f"[sod] WhatsApp error: {e}")

    if "slack" in channels:
        try:
            from deliver_slack import run as sl_run
            ok = sl_run(briefing_type="sod", date_str=date_str)
            results["slack"] = "success" if ok else "failure"
            print(f"[sod] Slack: {'✅' if ok else '❌'}")
        except Exception as e:
            results["slack"] = f"error: {e}"
            print(f"[sod] Slack error: {e}")

    # Always archive
    archive_path = get_project_root() / "data" / "briefings" / date_str / "sod.md"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(compose_sod_markdown(date_str))
    print(f"[sod] Archived to {archive_path}")

    return results


def run(channels: list[str] | None = None, date_str: str | None = None,
        preview: bool = False) -> dict:
    date_str = date_str or today_str()

    if channels is None:
        cfg = load_config("delivery.json")
        channels = []
        if cfg.get("telegram", {}).get("enabled"):  channels.append("telegram")
        if cfg.get("whatsapp", {}).get("enabled"):  channels.append("whatsapp")
        if cfg.get("slack", {}).get("sod_enabled"): channels.append("slack")

    print(f"[sod] Composing SOD briefing for {date_str} → channels: {channels}")

    # Collect all SOD data first
    data_dir = get_project_root() / "data" / "sod"
    data_dir.mkdir(parents=True, exist_ok=True)

    has_weather  = (data_dir / "weather.json").exists()
    has_calendar = (data_dir / "calendar.json").exists()
    has_gmail    = (data_dir / "gmail.json").exists()
    has_tech     = (get_project_root() / "data" / "scored" / date_str / "ranked.json").exists()

    print(f"[sod] Data available: weather={has_weather} calendar={has_calendar} "
          f"gmail={has_gmail} tech={has_tech}")

    results = deliver_sod(date_str, channels, preview)

    any_failure = any("error" in str(v) or v == "failure" for v in results.values())
    any_success = any(v == "success" for v in results.values())
    if any_failure:
        overall = "failure"
    elif any_success:
        overall = "success"
    else:
        overall = "skipped"
    update_last_run("compose-sod", overall, str(results))
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--channels", nargs="+",
                        choices=["telegram", "whatsapp", "slack"],
                        default=None)
    parser.add_argument("--date", help="YYYY-MM-DD")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    run(channels=args.channels, date_str=args.date, preview=args.preview)
