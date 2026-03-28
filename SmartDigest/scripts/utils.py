"""
utils.py — Shared utilities for all SmartDigest fetch scripts.
No OpenClaw dependencies. Fully testable standalone.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional, Union


# ─── Auto-load .env ──────────────────────────────────────────────────────────
# Loads SmartDigest/.env automatically so every script works without
# manually sourcing .env or running via run.sh.

def _load_dotenv() -> None:
    """
    Parse SmartDigest/.env and inject into os.environ (no external package needed).
    Lines starting with # are comments. Supports: KEY=VALUE and KEY="VALUE".
    Already-set env vars are NOT overwritten (shell wins).
    """
    env_path = Path(__file__).parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip('"').strip("'")
        if key and key not in os.environ:   # shell vars take priority
            os.environ[key] = val

_load_dotenv()


# ─── Path Helpers ────────────────────────────────────────────────────────────

def get_project_root() -> Path:
    """Returns SmartDigest/ root regardless of where the script is called from."""
    return Path(__file__).parent.parent


def get_data_dir(subdirectory: str, date_str: Optional[str] = None) -> Path:
    """
    Returns a dated data directory, creating it if needed.
    subdirectory: 'raw', 'scored', or 'briefings'
    date_str: 'YYYY-MM-DD', defaults to today
    """
    if date_str is None:
        date_str = today_str()
    path = get_project_root() / "data" / subdirectory / date_str
    path.mkdir(parents=True, exist_ok=True)
    return path


def get_state_path(filename: str) -> Path:
    return get_project_root() / "state" / filename


def get_config_path(filename: str) -> Path:
    return get_project_root() / "config" / filename


# ─── Time Helpers ─────────────────────────────────────────────────────────────

def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def days_ago(n: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=n)


# ─── Deduplication ───────────────────────────────────────────────────────────

def item_hash(source: str, url: str, title: str) -> str:
    """Stable hash for deduplication — based on source + url + title."""
    raw = f"{source}|{url}|{title}".lower().strip()
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def load_seen_items() -> dict[str, str]:
    """
    Returns {hash: iso_timestamp} of all previously seen items.
    Automatically prunes entries older than seen_items_days from schedule.json.
    """
    path = get_state_path("seen_items.json")
    if not path.exists():
        return {}

    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}

    # Prune stale entries
    retention_days = _get_retention_days()
    cutoff = days_ago(retention_days).isoformat()
    pruned = {k: v for k, v in data.items() if v >= cutoff}

    if len(pruned) < len(data):
        save_seen_items(pruned)

    return pruned


def save_seen_items(seen: dict[str, str]) -> None:
    path = get_state_path("seen_items.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(seen, indent=2))


def is_seen(h: str, seen: dict[str, str]) -> bool:
    return h in seen


def mark_seen(h: str, seen: dict[str, str]) -> None:
    seen[h] = now_iso()


def _get_retention_days() -> int:
    try:
        cfg = json.loads(get_config_path("schedule.json").read_text())
        return cfg.get("retention", {}).get("seen_items_days", 7)
    except Exception:
        return 7


# ─── Pipeline State ──────────────────────────────────────────────────────────

def load_last_run() -> dict:
    path = get_state_path("last_run.json")
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def update_last_run(stage: str, status: str, detail: str = "") -> None:
    state = load_last_run()
    state[stage] = {
        "status": status,           # "success" | "failure" | "skipped"
        "timestamp": now_iso(),
        "detail": detail
    }
    path = get_state_path("last_run.json")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, indent=2))


# ─── Config Loaders ──────────────────────────────────────────────────────────

def load_config(filename: str) -> dict:
    path = get_config_path(filename)
    try:
        return json.loads(path.read_text())
    except Exception as e:
        print(f"[utils] ERROR loading config/{filename}: {e}", file=sys.stderr)
        return {}


# ─── Markdown Helpers ────────────────────────────────────────────────────────

def write_raw_output(source_name: str, items: list, date_str: Optional[str] = None) -> Path:
    """
    Writes structured Markdown to data/raw/YYYY-MM-DD/{source_name}.md
    Each item dict: {title, url, summary, source, published_at, extra: {}}
    Returns the written file path.
    """
    out_dir = get_data_dir("raw", date_str)
    out_path = out_dir / f"{source_name}.md"

    lines = [
        f"# {source_name.upper()} — {today_str()}",
        f"_Fetched: {now_iso()}_",
        f"_Items: {len(items)}_",
        "",
        "---",
        ""
    ]

    for i, item in enumerate(items, 1):
        lines += [
            f"## {i}. {item.get('title', 'Untitled')}",
            f"- **URL**: {item.get('url', '')}",
            f"- **Source**: {item.get('source', source_name)}",
            f"- **Published**: {item.get('published_at', 'unknown')}",
        ]
        extra = item.get("extra", {})
        for k, v in extra.items():
            lines.append(f"- **{k.capitalize()}**: {v}")
        lines += [
            "",
            item.get("summary", "_No summary available._"),
            "",
            "---",
            ""
        ]

    out_path.write_text("\n".join(lines))
    return out_path


# ─── Pruning ─────────────────────────────────────────────────────────────────

def prune_old_data() -> None:
    """Remove data directories older than configured retention windows."""
    try:
        cfg = load_config("schedule.json").get("retention", {})
    except Exception:
        cfg = {}

    rules = [
        ("raw",       cfg.get("raw_data_days", 7)),
        ("scored",    cfg.get("scored_data_days", 14)),
        ("briefings", cfg.get("briefings_days", 30)),
    ]

    for subdir, days in rules:
        base = get_project_root() / "data" / subdir
        if not base.exists():
            continue
        cutoff_str = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        for date_dir in base.iterdir():
            if date_dir.is_dir() and date_dir.name < cutoff_str:
                import shutil
                shutil.rmtree(date_dir)
                print(f"[utils] Pruned {subdir}/{date_dir.name}")


# ─── CLI Test ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Project root:", get_project_root())
    print("Today:", today_str())
    print("Seen items count:", len(load_seen_items()))
    print("Last run:", load_last_run())
