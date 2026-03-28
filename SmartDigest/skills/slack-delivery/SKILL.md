# Skill: Slack Delivery

## Purpose
Two distinct Slack capabilities:
1. **READ** from Slack channels → used by EOD to build the channel digest
2. **POST** to Slack channels → used by SOD to deliver morning briefing

---

## Setup

### Reading FROM Slack (for EOD digest)
1. Go to api.slack.com/apps → Create App → From scratch
2. OAuth & Permissions → Bot Token Scopes: `channels:history`, `channels:read`, `groups:history`
3. Install to Workspace → Copy Bot Token
4. `export SMARTDIGEST_SLACK_BOT_TOKEN=xoxb-...`
5. Edit `config/slack_channels.json` — add your channel IDs and set `"enabled": true`

**Get channel ID:** Right-click channel name in Slack → Copy link → last segment of URL is the ID

### Posting TO Slack (for SOD briefing)
1. Same app → Incoming Webhooks → Turn on
2. Add New Webhook → pick #smartdigest-sod channel → Copy URL
3. Repeat for #smartdigest-eod
4. `export SMARTDIGEST_SLACK_SOD_WEBHOOK=https://hooks.slack.com/services/...`
5. `export SMARTDIGEST_SLACK_EOD_WEBHOOK=https://hooks.slack.com/services/...`

---

## Commands

**Read Slack channels (EOD digest):**
```bash
python scripts/fetch_slack.py --hours 12 --dry-run
```

**Post SOD to Slack:**
```bash
python scripts/deliver_slack.py --type sod
python scripts/deliver_slack.py --type sod --preview   # see Block Kit JSON
```

**Post EOD to Slack:**
```bash
python scripts/deliver_slack.py --type eod
```

---

## When User Says
- "Enable Slack"          → Set `sod_enabled: true` and/or `eod_enabled: true` in delivery.json
- "Add #dev channel"      → Add entry to config/slack_channels.json with channel ID
- "Stop reading #general" → Set `"enabled": false` for that channel in slack_channels.json
