from __future__ import annotations
"""
compose_eod.py — Composes the End-of-Day briefing from Slack digest + tech scores.

Sources:   slack_digest.json (from fetch_slack.py) + ranked.json (from groq_scorer.py)
Delivers:  Telegram + WhatsApp (based on delivery.json)

Usage:
    python scripts/compose_eod.py
    python scripts/compose_eod.py --preview
    python scripts/compose_eod.py --channels telegram whatsapp
"""

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import get_project_root, load_config, update_last_run, today_str, now_iso


def compose_eod_markdown(date_str: str) -> str:
    lines = []
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        lines.append(f"# 🌙 SmartDigest EOD — {dt.strftime('%A, %B %d %Y')}")
    except Exception:
        lines.append(f"# 🌙 SmartDigest EOD — {date_str}")
    lines.append(f"_Generated: {now_iso()}_\n")
    lines.append("---\n")

    # ── Slack Digest ──────────────────────────────────────────
    slack_path = get_project_root() / "data" / "eod" / "slack_digest.json"
    if slack_path.exists():
        slack_data = json.loads(slack_path.read_text())
        channels   = slack_data.get("channels", [])
        total_msgs = sum(c.get("message_count", 0) for c in channels)
        hours_back = slack_data.get("hours_back", 12)

        lines.append(f"## 💬 Slack Digest — Last {hours_back}h")
        lines.append(f"_{total_msgs} messages across {len(channels)} channels_\n")

        for ch in channels:
            if ch.get("message_count", 0) == 0:
                continue
            lines.append(f"### #{ch['channel']} ({ch['message_count']} messages)")
            highlights = ch.get("highlights", [])
            if highlights:
                lines.append("**Top discussions:**")
                for h in highlights[:3]:
                    eng = h.get("engagement", 0)
                    stars = f" _{eng} reactions_" if eng else ""
                    lines.append(f"- {h['text'][:200]}...{stars}")
            lines.append("")
    else:
        lines.append("## 💬 Slack Digest\n_No Slack data collected today._\n")

    # ── Tech Highlights ───────────────────────────────────────
    scored_path = get_project_root() / "data" / "scored" / date_str / "ranked.json"
    if scored_path.exists():
        ranked = json.loads(scored_path.read_text())
        items  = ranked.get("items", [])
        scorer = ranked.get("scorer", "AI")
        lines.append(f"## 🔥 Today's Tech Highlights")
        lines.append(f"_Scored by {scorer} · {len(items)} items above threshold_\n")
        for item in items[:8]:
            score = item.get("score", 0)
            stars = "⭐⭐" if score >= 9 else ("⭐" if score >= 7 else "")
            lines.append(f"### {item['rank']}. [{item['title']}]({item['url']}) {stars}")
            lines.append(f"`{item['source']}` · Score: {score}/10")
            if item.get("reason"):
                lines.append(f"_{item['reason']}_")
            lines.append("")

    # ── Daily Stats ───────────────────────────────────────────
    lines.append("## 📊 Today's Pipeline Stats")
    raw_count = 0
    for src in ["github", "hackernews", "rss", "arxiv"]:
        p = get_project_root() / "data" / "raw" / date_str / f"{src}.md"
        if p.exists():
            count = p.read_text().count("\n## ")
            raw_count += count
            lines.append(f"- `{src}`: {count} items collected")
    lines.append(f"\n**Total collected:** {raw_count} items")

    if scored_path.exists():
        ranked = json.loads(scored_path.read_text())
        lines.append(f"**Scored:** {ranked.get('total_items_evaluated', '?')} evaluated")
        lines.append(f"**Above threshold:** {ranked.get('items_above_threshold', '?')} items")

    lines.append("\n---")
    lines.append("_SmartDigest EOD — See you tomorrow! 🤖_")
    return "\n".join(lines)


def deliver_eod(date_str: str, channels: list[str], preview: bool = False) -> dict:
    results = {}

    if preview:
        print(compose_eod_markdown(date_str))
        return {"preview": True}

    if "telegram" in channels:
        try:
            # Build EOD-specific message for Telegram
            from deliver_telegram import build_telegram_message
            ranked_path = get_project_root() / "data" / "scored" / date_str / "ranked.json"
            if ranked_path.exists():
                ranked = json.loads(ranked_path.read_text())
                # Prepend EOD header
                ranked["_eod_prefix"] = "🌙 *SmartDigest EOD*\n\n"
                from deliver_telegram import run as tg_run
                ok = tg_run(date_str=date_str, preview=False)
            else:
                ok = False
            results["telegram"] = "success" if ok else "no_data"
            print(f"[eod] Telegram: {'✅' if ok else '⚠️ no scored data'}")
        except Exception as e:
            results["telegram"] = f"error: {e}"
            print(f"[eod] Telegram error: {e}")

    if "whatsapp" in channels:
        try:
            from deliver_whatsapp import run as wa_run
            ok = wa_run(briefing_type="eod", date_str=date_str)
            results["whatsapp"] = "success" if ok else "failure"
            print(f"[eod] WhatsApp: {'✅' if ok else '❌'}")
        except Exception as e:
            results["whatsapp"] = f"error: {e}"
            print(f"[eod] WhatsApp error: {e}")

    if "slack" in channels:
        try:
            from deliver_slack import run as sl_run
            ok = sl_run(briefing_type="eod", date_str=date_str)
            results["slack"] = "success" if ok else "failure"
            print(f"[eod] Slack: {'✅' if ok else '❌'}")
        except Exception as e:
            results["slack"] = f"error: {e}"

    # Always archive
    archive_path = get_project_root() / "data" / "briefings" / date_str / "eod.md"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    archive_path.write_text(compose_eod_markdown(date_str))
    print(f"[eod] Archived to {archive_path}")

    return results


def run(channels: list[str] | None = None, date_str: str | None = None,
        preview: bool = False) -> dict:
    date_str = date_str or today_str()

    if channels is None:
        cfg = load_config("delivery.json")
        channels = []
        if cfg.get("telegram", {}).get("enabled"):  channels.append("telegram")
        if cfg.get("whatsapp", {}).get("enabled"):  channels.append("whatsapp")
        if cfg.get("slack", {}).get("eod_enabled"): channels.append("slack")

    print(f"[eod] Composing EOD briefing for {date_str} → channels: {channels}")
    results = deliver_eod(date_str, channels, preview)
    update_last_run("compose-eod", "success", str(results))
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--channels", nargs="+",
                        choices=["telegram", "whatsapp", "slack"], default=None)
    parser.add_argument("--date", help="YYYY-MM-DD")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    run(channels=args.channels, date_str=args.date, preview=args.preview)
