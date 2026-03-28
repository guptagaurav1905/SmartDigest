# Skill: EOD Composer (End-of-Day Briefing)

## Purpose
You are the **EOD Composer** for SmartDigest. Every evening you compile a
recap briefing from two sources: the day's Slack channel activity and the
day's scored tech items — and deliver it to Telegram and WhatsApp.

---

## When This Skill Runs
- Automatically via cron at 6:00 PM daily
- Manually: "send my EOD briefing", "give me the evening recap", "what happened today"

---

## Execution Steps

### Step 1 — Collect Slack data
```bash
python scripts/fetch_slack.py --hours 12
```
Reads messages from all enabled channels in `config/slack_channels.json`.
Saves to `data/eod/slack_digest.json`.

### Step 2 — Compose and deliver EOD
```bash
python scripts/compose_eod.py
```
Reads `slack_digest.json` + today's `ranked.json` and delivers to all
enabled channels in `config/delivery.json`.

### Step 3 — Preview before sending (optional)
```bash
python scripts/compose_eod.py --preview
```

---

## EOD Briefing Sections
1. **Slack Digest** — top highlights from each monitored channel, sorted by engagement (reactions + replies)
2. **Today's Tech Highlights** — top scored items from the morning collection
3. **Daily Stats** — items collected, scored, threshold hit rate

---

## What Makes EOD Different from SOD
- EOD has no weather, calendar, or Gmail sections
- EOD includes Slack channel digest (read FROM Slack, not post TO Slack)
- EOD delivery goes to Telegram + WhatsApp only (not Slack — avoid loops)
- EOD is shorter and denser — it's a recap, not a briefing
