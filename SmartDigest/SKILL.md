# SmartDigest — Root Orchestrator

## What is SmartDigest?
SmartDigest is an autonomous daily briefing agent. Every morning it:
1. **Collects** content from GitHub repos, RSS feeds, Hacker News, and arXiv papers
2. **Scores** each item for relevance to your personal interests using AI
3. **Composes** a ranked, readable briefing
4. **Delivers** it to your configured channel (Telegram / Discord / archived locally)

Zero manual prompting required once configured.

---

## Quick Start for Users

| What you want | Just say... |
|---|---|
| Run today's full briefing | "Run SmartDigest" or "Give me my morning briefing" |
| Add a new source | "Add the Rust blog to my feeds" |
| Change interests | "I only care about AI agents and Rust now" |
| Switch delivery channel | "Send my briefing to Discord instead" |
| See yesterday's briefing | "Show me yesterday's digest" |
| Test without sending | "Preview today's briefing" |
| Check pipeline status | "What happened in the last run?" |

---

## Full Pipeline Execution

When the user asks to run SmartDigest (or when the cron fires), execute in this order:

### Stage 1: Source Collector
> Invoke: `skills/source-collector/SKILL.md`

Run all enabled fetch scripts. Collect raw data to `data/raw/YYYY-MM-DD/`.
Report item counts per source. Proceed even if some sources fail.

### Stage 2: Relevance Scorer
> Invoke: `skills/relevance-scorer/SKILL.md`

Read raw data, score items against interests, write `data/scored/YYYY-MM-DD/ranked.json`.
Check `state/last_run.json` to confirm Stage 1 completed before proceeding.

### Stage 3: Briefing Composer
> Invoke: `skills/briefing-composer/SKILL.md`

Read ranked data, compose briefing, archive to `data/briefings/YYYY-MM-DD/briefing.md`,
then deliver via configured channel. Always archive regardless of delivery success.

---

## Pipeline Abort Logic

```
Stage 1 (Collector) fails completely (0 items, all scripts errored)
  → Ask user: "No content was collected. Retry or use yesterday's data?"
  → If retry: re-run Stage 1
  → If yesterday: pass yesterday's date to Stage 2

Stage 2 (Scorer) fails
  → Log failure to state/last_run.json
  → Check if yesterday's scored data exists
  → If yes: use it and note in briefing: "⚠️ Using yesterday's scored data (scorer failed today)"
  → If no: abort, report to user

Stage 3 (Composer) — delivery fails
  → Always write the archive first (never block archive on delivery)
  → Retry delivery up to max_attempts (from config/delivery.json)
  → If all retries fail: display briefing inline in chat
```

---

## Non-Pipeline Commands (Route to Appropriate Skill)

| User intent | Route to |
|---|---|
| Add/remove sources, change interests, update config | `skills/nl-config/SKILL.md` |
| "Score these items" / re-run scorer only | `skills/relevance-scorer/SKILL.md` |
| "Re-send my briefing" | `skills/briefing-composer/SKILL.md` |
| "Collect HN only" | `skills/source-collector/SKILL.md` |

---

## Showing Pipeline Status

When user asks "what happened in the last run?" or "is everything working?":

1. Read `state/last_run.json`
2. Display per-stage status (success/failure/skipped, timestamp, item counts)
3. List today's files in `data/raw/YYYY-MM-DD/` if they exist
4. Report delivery status from composer stage

Example output:
```
📊 SmartDigest — Last Run Status (Jan 15, 06:03 AM)

✅ source-collector-github    → 3 items
✅ source-collector-rss       → 7 items
✅ source-collector-hn        → 12 items
✅ source-collector-arxiv     → 5 items
✅ relevance-scorer           → 47 evaluated, 8 above threshold (6.0)
✅ briefing-composer          → 8 items delivered via telegram

Next run: Tomorrow at 6:00 AM
```

---

## Showing Past Briefings

When user asks for a past briefing:
1. Read `data/briefings/YYYY-MM-DD/briefing.md`
2. Display it inline in the chat
3. Offer to re-deliver it if needed

---

## Project Extensibility (Phase 4+)
This architecture is designed for the following planned additions:
- **Tool integrations**: Weather, calendar, stock data as additional source types
- **Database**: SQLite for richer deduplication and analytics (replace seen_items.json)
- **WhatsApp delivery**: Already stubbed in config/delivery.json — just enable it
- **Deep reports**: Weekly summary skill, trend analysis, paper deep-dives
- **ClawHub publishing**: Package as installable SmartDigest skill bundle

All extensions are additive — Phase 3 files are not modified by Phase 4.

---

## File Structure Reference

```
SmartDigest/
├── SKILL.md                    ← You are here (root orchestrator)
├── config/
│   ├── sources.json            ← What to fetch
│   ├── interests.json          ← How to score
│   ├── delivery.json           ← Where to send
│   └── schedule.json           ← When to run
├── skills/
│   ├── source-collector/SKILL.md
│   ├── relevance-scorer/SKILL.md
│   ├── briefing-composer/SKILL.md
│   └── nl-config/SKILL.md
├── scripts/
│   ├── utils.py                ← Shared: paths, dedup, state
│   ├── fetch_github.py
│   ├── fetch_rss.py
│   ├── fetch_hackernews.py
│   └── fetch_arxiv.py
├── data/
│   ├── raw/YYYY-MM-DD/         ← Stage 1 output
│   ├── scored/YYYY-MM-DD/      ← Stage 2 output
│   └── briefings/YYYY-MM-DD/   ← Stage 3 output (archive)
└── state/
    ├── seen_items.json         ← Dedup ring buffer
    ├── last_run.json           ← Pipeline health
    └── user_profile.md        ← AI memory of your interests
```
