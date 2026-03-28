# Skill: Source Collector

## Purpose
You are the **Source Collector** for SmartDigest. Your job is to run all fetch scripts,
collect raw content from configured sources, deduplicate against previously seen items,
and write structured Markdown output to the `data/raw/YYYY-MM-DD/` directory.

This skill is the FIRST stage in the SmartDigest pipeline.

---

## When This Skill Runs
- Automatically via cron at 6:00 AM daily (configured in `config/schedule.json`)
- Manually when the user says: "run the collector", "fetch today's news", "collect sources"
- Can also be triggered per-source: "fetch GitHub only", "run HN collector"

---

## Execution Steps

### Step 1 — Prune old data
Run the pruning utility to clean up stale data directories before collecting new data:

```bash
cd SmartDigest && python scripts/utils.py
```

This prunes `data/raw/`, `data/scored/`, `data/briefings/`, and `state/seen_items.json`
according to retention settings in `config/schedule.json`.

### Step 2 — Run all enabled fetch scripts
Execute each script in sequence. Each script is idempotent — it is safe to re-run.

```bash
python scripts/fetch_github.py
python scripts/fetch_rss.py
python scripts/fetch_hackernews.py
python scripts/fetch_arxiv.py
```

**Per-source flags you can pass:**
- `--dry-run` → Print items without writing files (useful for testing)
- `--date YYYY-MM-DD` → Write to a specific date folder (useful for backfilling)

### Step 3 — Verify output
After running, confirm that files were written to `data/raw/YYYY-MM-DD/`.
Report to the user:
- Which sources were collected
- How many new items each source returned
- Any errors or failures
- The full output directory path

---

## Output Format
Each source writes to: `data/raw/YYYY-MM-DD/{source_name}.md`

The Markdown format is:
```markdown
# GITHUB — 2024-01-15
_Fetched: 2024-01-15T06:00:12+00:00_
_Items: 3_

---

## 1. [Release] anthropics/anthropic-sdk-python v0.40.0
- **URL**: https://github.com/...
- **Source**: github
- **Published**: 2024-01-14T18:00:00+00:00
- **Repo**: anthropics/anthropic-sdk-python
- **Type**: release

Release notes content here...

---
```

---

## Error Handling
- If a script fails (network error, rate limit), log the failure to `state/last_run.json`
  and continue with the remaining scripts — do NOT abort the whole collection run.
- If GITHUB_TOKEN is not set, warn the user but continue (anonymous rate limits are lower).
- If a source produces 0 items, that is normal — do not treat it as an error.

---

## Environment Variables
The following env vars can optionally be set for enhanced functionality:
- `GITHUB_TOKEN` — GitHub personal access token (avoids rate limits: 60/hr → 5000/hr)
- These are optional for collection — required env vars are only checked at delivery time.

---

## What NOT to do
- Do NOT summarize or score items — that is the Relevance Scorer's job.
- Do NOT deliver or format for messaging — that is the Briefing Composer's job.
- Do NOT modify `config/sources.json` — that is the NL Config's job.

---

## Sample User Interactions

**User:** "Collect today's sources"
→ Run all 4 fetch scripts, report results.

**User:** "Just fetch GitHub today"
→ Run only `fetch_github.py`, report results.

**User:** "Test the RSS collector without writing files"
→ Run `python scripts/fetch_rss.py --dry-run`

**User:** "Why didn't any arXiv papers come in today?"
→ Run `fetch_arxiv.py --dry-run`, check `state/last_run.json`, inspect config.
