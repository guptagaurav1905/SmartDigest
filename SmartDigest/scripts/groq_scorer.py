"""
groq_scorer.py — Relevance scorer using Groq AI (free/cheap tier) instead of Claude.

Use this for testing or cost-sensitive runs. Groq offers free inference on
Llama 3.3 70B, Mixtral, and other open models.

Usage:
    python scripts/groq_scorer.py                    # scores today's raw data
    python scripts/groq_scorer.py --date 2024-01-15  # score a specific date
    python scripts/groq_scorer.py --model llama-3.3-70b-versatile  # override model

Requires:
    pip install groq
    export GROQ_API_KEY=gsk_...   (free at console.groq.com)

Output: data/scored/YYYY-MM-DD/ranked.json  (same format as Claude scorer)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import List, Dict, Optional

sys.path.insert(0, str(Path(__file__).parent))
from utils import (
    get_data_dir, get_project_root, load_config,
    update_last_run, today_str, now_iso
)

# ── Groq Model Options (free tier) ──────────────────────────────────────────
# llama-3.3-70b-versatile   → Best quality, still very fast
# llama-3.1-8b-instant      → Ultra-fast, lower quality — good for quick tests
# mixtral-8x7b-32768        → Good at instruction following, large context
# gemma2-9b-it              → Lightweight, solid reasoning
DEFAULT_MODEL = "llama-3.3-70b-versatile"


def get_groq_client():
    try:
        from groq import Groq
    except ImportError:
        print("[groq] ERROR: groq package not installed.")
        print("       Run: pip install groq")
        sys.exit(1)

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        print("[groq] ERROR: GROQ_API_KEY not set.")
        print("       Get a free key at: https://console.groq.com")
        sys.exit(1)

    return Groq(api_key=api_key)


def parse_raw_markdown(md_path: Path) -> List[Dict]:
    """
    Parse a raw source Markdown file into a list of item dicts.
    Each item starts with '## N.' in the file.
    """
    text = md_path.read_text(encoding="utf-8")
    source_name = md_path.stem  # e.g. 'github', 'hackernews'
    items = []

    # Split on item headers: ## 1., ## 2., etc.
    sections = re.split(r'\n## \d+\.', text)
    for section in sections[1:]:  # skip file header
        lines = section.strip().split('\n')
        title = lines[0].strip() if lines else "Untitled"

        url = ""
        published = ""
        summary_lines = []
        extra = {}
        in_summary = False

        for line in lines[1:]:
            line = line.strip()
            if line.startswith('- **URL**:'):
                url = line.replace('- **URL**:', '').strip()
            elif line.startswith('- **Published**:'):
                published = line.replace('- **Published**:', '').strip()
            elif line.startswith('- **') and ':' in line:
                key = re.search(r'\*\*(.+?)\*\*', line)
                val = line.split(':', 1)[1].strip() if ':' in line else ""
                if key and key.group(1) not in ('URL', 'Source', 'Published'):
                    extra[key.group(1).lower()] = val
            elif line == '---':
                break
            elif line and not line.startswith('-'):
                summary_lines.append(line)

        summary = ' '.join(summary_lines).strip()[:600]
        items.append({
            "title": title,
            "url": url,
            "source": source_name,
            "published_at": published,
            "summary": summary or "_No summary._",
            "extra": extra
        })

    return items


def score_batch(client, items: List[Dict], interests: Dict, user_profile: str, model: str) -> List[Dict]:
    """
    Send a batch of items to Groq for scoring.
    Batching reduces API calls significantly.
    """
    if not items:
        return []

    # Build compact item list for prompt
    items_text = ""
    for i, item in enumerate(items):
        items_text += f"\n[{i}] SOURCE: {item['source']}\nTITLE: {item['title']}\nSUMMARY: {item['summary'][:300]}\n"

    blocklist = ', '.join(interests.get('blocklist', []))
    high = ', '.join(interests.get('high_priority', []))
    medium = ', '.join(interests.get('medium_priority', []))

    prompt = f"""You are a relevance scorer for a tech briefing agent.

USER INTERESTS:
- High priority topics: {high}
- Medium priority topics: {medium}
- Blocklist (score 0 if matched): {blocklist}

USER PROFILE NOTES:
{user_profile[:800]}

TASK: Score each item below from 0.0 to 10.0 for relevance.
Scoring guide:
- 9-10: Directly matches high-priority interests, highly actionable
- 7-8: Relevant to high or medium priority, interesting
- 5-6: Tangentially related
- 3-4: Low relevance
- 0-2: Off-topic, noise, or blocklist match

ITEMS TO SCORE:
{items_text}

Respond with ONLY valid JSON array, one object per item, in this exact format:
[
  {{"index": 0, "score": 8.5, "reason": "One sentence explanation"}},
  {{"index": 1, "score": 3.0, "reason": "One sentence explanation"}}
]
No extra text, no markdown fences. Just the JSON array."""

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,   # Low temp for consistent scoring
            max_tokens=1500,
        )
        raw = response.choices[0].message.content.strip()

        # Clean up any accidental markdown fences
        raw = re.sub(r'^```json?\s*', '', raw)
        raw = re.sub(r'\s*```$', '', raw)

        scores = json.loads(raw)
        return scores

    except json.JSONDecodeError as e:
        print(f"[groq] JSON parse error: {e}")
        print(f"[groq] Raw response: {raw[:300]}")
        return []
    except Exception as e:
        print(f"[groq] API error: {e}")
        return []


def run(model: str = DEFAULT_MODEL, date_str: Optional[str] = None) -> int:
    print(f"[groq] Starting relevance scoring with model: {model}")
    client = get_groq_client()

    if date_str is None:
        date_str = today_str()

    # Load config and user profile
    interests = load_config("interests.json")
    profile_path = get_project_root() / "state" / "user_profile.md"
    user_profile = profile_path.read_text() if profile_path.exists() else ""

    threshold = interests.get("scoring", {}).get("threshold", 6.0)
    max_items = interests.get("scoring", {}).get("max_items_per_briefing", 10)
    source_boost = interests.get("scoring", {}).get("source_boost", {})

    # Load all raw data for the date
    raw_dir = get_project_root() / "data" / "raw" / date_str
    if not raw_dir.exists():
        print(f"[groq] No raw data found for {date_str}")
        print(f"       Run the source collector first: python scripts/fetch_hackernews.py")
        update_last_run("relevance-scorer", "failure", f"no raw data for {date_str}")
        return 0

    all_items = []
    for md_file in sorted(raw_dir.glob("*.md")):
        items = parse_raw_markdown(md_file)
        print(f"[groq] Parsed {len(items)} items from {md_file.name}")
        all_items.extend(items)

    if not all_items:
        print("[groq] No items to score")
        return 0

    print(f"[groq] Scoring {len(all_items)} items in batches of 10...")

    # Score in batches to stay within token limits
    BATCH_SIZE = 10
    scored_items = []

    for batch_start in range(0, len(all_items), BATCH_SIZE):
        batch = all_items[batch_start:batch_start + BATCH_SIZE]
        print(f"[groq] Batch {batch_start//BATCH_SIZE + 1} ({len(batch)} items)...")

        scores = score_batch(client, batch, interests, user_profile, model)

        for score_obj in scores:
            idx = score_obj.get("index", -1)
            if 0 <= idx < len(batch):
                item = batch[idx].copy()
                raw_score = float(score_obj.get("score", 0))
                boost = source_boost.get(item["source"], 0)
                final_score = min(10.0, round(raw_score + boost, 2))

                item["score"] = final_score
                item["reason"] = score_obj.get("reason", "")
                scored_items.append(item)

    # Filter, sort, cap
    above_threshold = [i for i in scored_items if i["score"] >= threshold]
    above_threshold.sort(key=lambda x: x["score"], reverse=True)
    top_items = above_threshold[:max_items]

    # Add rank
    for rank, item in enumerate(top_items, 1):
        item["rank"] = rank

    print(f"[groq] {len(scored_items)} scored, {len(top_items)} above threshold ({threshold})")

    # Write output
    out_dir = get_project_root() / "data" / "scored" / date_str
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "ranked.json"

    output = {
        "date": date_str,
        "scored_at": now_iso(),
        "scorer": f"groq/{model}",
        "threshold": threshold,
        "total_items_evaluated": len(scored_items),
        "items_above_threshold": len(top_items),
        "items": top_items
    }

    out_path.write_text(json.dumps(output, indent=2))
    print(f"[groq] Written to {out_path}")

    update_last_run("relevance-scorer", "success",
                    f"{len(scored_items)} evaluated, {len(top_items)} above threshold — groq/{model}")
    return len(top_items)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Score items using Groq AI")
    parser.add_argument("--model", default=DEFAULT_MODEL,
                        choices=["llama-3.3-70b-versatile", "llama-3.1-8b-instant",
                                 "mixtral-8x7b-32768", "gemma2-9b-it"],
                        help="Groq model to use")
    parser.add_argument("--date", help="Target date YYYY-MM-DD (default: today)")
    args = parser.parse_args()

    count = run(model=args.model, date_str=args.date)
    print(f"[groq] Done. {count} items above threshold.")
