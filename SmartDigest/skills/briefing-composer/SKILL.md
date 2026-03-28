# Skill: Briefing Composer

## Purpose
You are the **Briefing Composer** for SmartDigest. Your job is to read today's
`data/scored/YYYY-MM-DD/ranked.json`, compose a clean, readable briefing, archive it
to `data/briefings/YYYY-MM-DD/briefing.md`, and deliver it through the configured channel.

This skill is the THIRD and final stage in the SmartDigest pipeline.

---

## When This Skill Runs
- Automatically after Relevance Scorer completes (cron pipeline)
- Manually: "compose today's briefing", "send my digest", "deliver the briefing"
- Preview only: "show me today's briefing" (compose + display, don't send)

---

## Execution Steps

### Step 1 — Load data
Read:
1. `data/scored/YYYY-MM-DD/ranked.json` — the scored, ranked items
2. `config/delivery.json` — channel settings and formatting templates
3. `state/last_run.json` — check if scorer succeeded

If the scorer failed or `ranked.json` doesn't exist:
- Check yesterday's scored data as fallback
- If no data at all: report to user, abort gracefully

### Step 2 — Compose the briefing

#### Plain Markdown Archive (always written)
Write a clean `data/briefings/YYYY-MM-DD/briefing.md`:

```markdown
# SmartDigest — Monday, January 15 2024
> 8 items · Threshold: 6.0 · Generated: 06:03 AM

---

## 1. anthropics/anthropic-sdk-python v0.40.0 ⭐ 9.3
**Source:** GitHub · **Published:** Jan 14, 2024
**Why it matters:** Direct Anthropic SDK release with tool_use improvements — high priority match.

New tool_use parameter introduced. This release adds structured tool_choice support
and improves streaming reliability...

🔗 https://github.com/anthropics/...

---

## 2. "Toolformer: Language Models Can Teach Themselves to Use Tools" · 8.1
**Source:** arXiv · **Authors:** Schick et al.
**Why it matters:** Core paper on autonomous tool use in LLMs — directly relevant to agent work.

We introduce Toolformer, a model trained to decide which APIs to call, when to call them...

🔗 https://arxiv.org/abs/2302.04761

---

_Powered by SmartDigest · Built on OpenClaw_
```

#### Telegram Format
If `primary_channel == "telegram"`:
```
🗞 *SmartDigest — Mon, Jan 15*
_8 items above relevance threshold_

*1. anthropics/anthropic-sdk-python v0\.40\.0* ⭐ 9\.3
📌 `github` — Jan 14
New tool\_use parameter introduced\. This release adds structured tool\_choice support\.\.\.
[Read more](https://github.com/...)

*2\. Toolformer: Language Models Can Teach Themselves to Use Tools* ⭐ 8\.1
📌 `arxiv` — Schick et al\.
We introduce Toolformer, a model trained to decide which APIs to call\.\.\.
[Read more](https://arxiv.org/abs/2302.04761)

---
_Powered by SmartDigest_
```

**Telegram escaping rules:** Escape `.`, `!`, `-`, `(`, `)`, `#`, `+` with `\` when using MarkdownV2.

#### Discord Format
If `primary_channel == "discord"` and `use_embeds == true`:
Build a Discord webhook payload with one embed per top item:
```json
{
  "username": "SmartDigest",
  "content": "📋 **SmartDigest — Mon, Jan 15** · 8 items",
  "embeds": [
    {
      "title": "anthropics/anthropic-sdk-python v0.40.0",
      "url": "https://github.com/...",
      "description": "New tool_use parameter introduced...",
      "color": 5793266,
      "footer": { "text": "github · ⭐ 9.3 · Jan 14" }
    }
  ]
}
```

### Step 3 — Deliver

#### Telegram Delivery
```python
import os, urllib.request, urllib.parse, json

token = os.environ[delivery_cfg["telegram"]["bot_token_env"]]
chat_id = os.environ[delivery_cfg["telegram"]["chat_id_env"]]

url = f"https://api.telegram.org/bot{token}/sendMessage"
payload = json.dumps({
    "chat_id": chat_id,
    "text": telegram_message,
    "parse_mode": "MarkdownV2",
    "disable_web_page_preview": False
}).encode()

req = urllib.request.Request(url, data=payload,
      headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req) as resp:
    result = json.loads(resp.read())
```

Use retry logic from `delivery.json` (`max_attempts`, `backoff_seconds`).

#### Discord Delivery
Send HTTP POST to `os.environ[delivery_cfg["discord"]["webhook_env"]]`
with the embeds JSON payload. Max 10 embeds per message.

#### Failure → Archive Only
If delivery fails after all retries:
- The Markdown archive is still written (always)
- Log failure to `state/last_run.json`
- Display the briefing in the OpenClaw chat for the user to see

### Step 4 — Update pipeline state
```json
{
  "briefing-composer": {
    "status": "success",
    "timestamp": "2024-01-15T06:03:22+00:00",
    "detail": "8 items delivered via telegram"
  }
}
```

---

## WhatsApp (Phase 4 Placeholder)
`config/delivery.json` already has a `whatsapp` block with `enabled: false`.
When Phase 4 arrives, implement delivery via WhatsApp Business API here.
The composer already handles multi-channel routing — adding WhatsApp is additive only.

---

## Formatting Rules
- Keep each item summary to **2-4 sentences** max in the briefing
- Show score as a star rating: 9-10 → ⭐⭐, 7-8 → ⭐, 5-6 → (no star)
- Order: descending by score
- Never include items below threshold unless forced (all items scored low)
- Highlight the source type clearly (github / arxiv / rss / hackernews)

---

## What NOT to do
- Do NOT fetch new content
- Do NOT re-score items
- Do NOT modify config files
- Do NOT hardcode tokens — always read from environment variables
