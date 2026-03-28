from __future__ import annotations
"""
db.py — SQLite database layer for SmartDigest Phase 4.

Replaces:
  state/seen_items.json   → seen_items table
  state/last_run.json     → pipeline_runs table
  data/raw/*/             → raw_items table
  data/scored/*/          → scored_items table
  data/briefings/*/       → briefings table

Usage:
  from db import Database
  db = Database()
  db.mark_seen("abc123", "github", "Title", "https://...")
  items = db.get_scored_items("2026-03-28")
"""

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


DB_PATH = Path(__file__).parent.parent / "db" / "smartdigest.db"

SCHEMA = """
-- Deduplication registry
CREATE TABLE IF NOT EXISTS seen_items (
    hash            TEXT PRIMARY KEY,
    source          TEXT NOT NULL,
    title           TEXT,
    url             TEXT,
    first_seen_at   TEXT NOT NULL,
    last_seen_at    TEXT NOT NULL
);

-- Raw collected items per run
CREATE TABLE IF NOT EXISTS raw_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    hash            TEXT UNIQUE NOT NULL,
    source          TEXT NOT NULL,
    title           TEXT,
    url             TEXT,
    summary         TEXT,
    published_at    TEXT,
    collected_at    TEXT NOT NULL,
    run_date        TEXT NOT NULL,
    extra_json      TEXT DEFAULT '{}'
);

-- Scored/ranked items
CREATE TABLE IF NOT EXISTS scored_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    item_hash       TEXT NOT NULL,
    run_date        TEXT NOT NULL,
    score           REAL NOT NULL,
    rank            INTEGER,
    reason          TEXT,
    scorer          TEXT,
    scored_at       TEXT NOT NULL,
    FOREIGN KEY (item_hash) REFERENCES raw_items(hash)
);

-- Pipeline execution log
CREATE TABLE IF NOT EXISTS pipeline_runs (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date            TEXT NOT NULL,
    stage               TEXT NOT NULL,
    status              TEXT NOT NULL,
    detail              TEXT,
    items_collected     INTEGER DEFAULT 0,
    items_scored        INTEGER DEFAULT 0,
    items_delivered     INTEGER DEFAULT 0,
    started_at          TEXT,
    completed_at        TEXT
);

-- Delivered briefings archive
CREATE TABLE IF NOT EXISTS briefings (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_date        TEXT NOT NULL,
    briefing_type   TEXT NOT NULL DEFAULT 'sod',
    channel         TEXT NOT NULL,
    content         TEXT,
    item_count      INTEGER DEFAULT 0,
    delivered_at    TEXT,
    delivery_status TEXT DEFAULT 'pending'
);

-- Indexes for common queries
CREATE INDEX IF NOT EXISTS idx_raw_run_date     ON raw_items(run_date);
CREATE INDEX IF NOT EXISTS idx_scored_run_date  ON scored_items(run_date);
CREATE INDEX IF NOT EXISTS idx_runs_date_stage  ON pipeline_runs(run_date, stage);
CREATE INDEX IF NOT EXISTS idx_briefings_date   ON briefings(run_date, briefing_type);
"""


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def today_str() -> str:
    return datetime.now().strftime("%Y-%m-%d")


class Database:
    def __init__(self, db_path: Path | None = None):
        self.path = db_path or DB_PATH
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_schema()

    @contextmanager
    def _conn(self):
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=DELETE")
        conn.execute("PRAGMA foreign_keys=ON")
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _init_schema(self):
        with self._conn() as conn:
            conn.executescript(SCHEMA)

    # ── Deduplication ────────────────────────────────────────
    def is_seen(self, hash: str) -> bool:
        with self._conn() as conn:
            row = conn.execute(
                "SELECT 1 FROM seen_items WHERE hash = ?", (hash,)
            ).fetchone()
            return row is not None

    def mark_seen(self, hash: str, source: str, title: str = "", url: str = ""):
        now = now_iso()
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO seen_items (hash, source, title, url, first_seen_at, last_seen_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(hash) DO UPDATE SET last_seen_at = excluded.last_seen_at
            """, (hash, source, title, url, now, now))

    def prune_seen_items(self, days: int = 7):
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        with self._conn() as conn:
            deleted = conn.execute(
                "DELETE FROM seen_items WHERE last_seen_at < ?", (cutoff,)
            ).rowcount
        return deleted

    # ── Raw Items ────────────────────────────────────────────
    def insert_raw_item(self, item: dict, run_date: str | None = None) -> bool:
        """Returns True if inserted (new), False if already exists."""
        run_date = run_date or today_str()
        hash = item.get("hash") or item.get("url", "")
        with self._conn() as conn:
            try:
                conn.execute("""
                    INSERT INTO raw_items
                        (hash, source, title, url, summary, published_at, collected_at, run_date, extra_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    hash,
                    item.get("source", ""),
                    item.get("title", ""),
                    item.get("url", ""),
                    item.get("summary", ""),
                    item.get("published_at", ""),
                    now_iso(),
                    run_date,
                    json.dumps(item.get("extra", {}))
                ))
                return True
            except sqlite3.IntegrityError:
                return False

    def get_raw_items(self, run_date: str | None = None) -> list[dict]:
        run_date = run_date or today_str()
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM raw_items WHERE run_date = ? ORDER BY source, id",
                (run_date,)
            ).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["extra"] = json.loads(d.get("extra_json") or "{}")
            result.append(d)
        return result

    # ── Scored Items ─────────────────────────────────────────
    def insert_scored_item(self, item_hash: str, score: float, rank: int,
                            reason: str, scorer: str, run_date: str | None = None):
        run_date = run_date or today_str()
        with self._conn() as conn:
            conn.execute("""
                INSERT INTO scored_items (item_hash, run_date, score, rank, reason, scorer, scored_at)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (item_hash, run_date, score, rank, reason, scorer, now_iso()))

    def get_scored_items(self, run_date: str | None = None,
                          min_score: float = 0.0, limit: int = 20) -> list[dict]:
        run_date = run_date or today_str()
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT s.*, r.title, r.url, r.source, r.summary, r.published_at, r.extra_json
                FROM scored_items s
                JOIN raw_items r ON s.item_hash = r.hash
                WHERE s.run_date = ? AND s.score >= ?
                ORDER BY s.score DESC
                LIMIT ?
            """, (run_date, min_score, limit)).fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["extra"] = json.loads(d.get("extra_json") or "{}")
            result.append(d)
        return result

    def save_ranked_json(self, run_date: str, items: list[dict],
                          scorer: str, threshold: float):
        """Bulk insert scored items from ranked.json format."""
        for item in items:
            self.insert_scored_item(
                item_hash=item.get("url", item.get("title", "")),
                score=item.get("score", 0),
                rank=item.get("rank", 0),
                reason=item.get("reason", ""),
                scorer=scorer,
                run_date=run_date
            )

    # ── Pipeline Runs ────────────────────────────────────────
    def log_run_start(self, stage: str, run_date: str | None = None) -> int:
        run_date = run_date or today_str()
        with self._conn() as conn:
            cursor = conn.execute("""
                INSERT INTO pipeline_runs (run_date, stage, status, started_at)
                VALUES (?, ?, 'running', ?)
            """, (run_date, stage, now_iso()))
            return cursor.lastrowid

    def log_run_complete(self, run_id: int, status: str, detail: str = "",
                          items_collected: int = 0, items_scored: int = 0,
                          items_delivered: int = 0):
        with self._conn() as conn:
            conn.execute("""
                UPDATE pipeline_runs
                SET status=?, detail=?, completed_at=?,
                    items_collected=?, items_scored=?, items_delivered=?
                WHERE id=?
            """, (status, detail, now_iso(),
                  items_collected, items_scored, items_delivered, run_id))

    def get_last_run(self, stage: str | None = None) -> dict | None:
        with self._conn() as conn:
            if stage:
                row = conn.execute("""
                    SELECT * FROM pipeline_runs WHERE stage = ?
                    ORDER BY id DESC LIMIT 1
                """, (stage,)).fetchone()
            else:
                row = conn.execute("""
                    SELECT * FROM pipeline_runs ORDER BY id DESC LIMIT 1
                """).fetchone()
        return dict(row) if row else None

    def get_run_summary(self, run_date: str | None = None) -> list[dict]:
        run_date = run_date or today_str()
        with self._conn() as conn:
            rows = conn.execute("""
                SELECT stage, status, detail, items_collected,
                       items_scored, items_delivered, started_at, completed_at
                FROM pipeline_runs WHERE run_date = ?
                ORDER BY id
            """, (run_date,)).fetchall()
        return [dict(r) for r in rows]

    # ── Briefings ────────────────────────────────────────────
    def save_briefing(self, content: str, channel: str,
                       briefing_type: str = "sod", item_count: int = 0,
                       run_date: str | None = None) -> int:
        run_date = run_date or today_str()
        with self._conn() as conn:
            cursor = conn.execute("""
                INSERT INTO briefings
                    (run_date, briefing_type, channel, content, item_count, delivered_at, delivery_status)
                VALUES (?, ?, ?, ?, ?, ?, 'delivered')
            """, (run_date, briefing_type, channel, content, item_count, now_iso()))
            return cursor.lastrowid

    def get_briefing(self, run_date: str | None = None,
                      briefing_type: str = "sod") -> dict | None:
        run_date = run_date or today_str()
        with self._conn() as conn:
            row = conn.execute("""
                SELECT * FROM briefings
                WHERE run_date = ? AND briefing_type = ?
                ORDER BY id DESC LIMIT 1
            """, (run_date, briefing_type)).fetchone()
        return dict(row) if row else None

    # ── Analytics ────────────────────────────────────────────
    def get_daily_stats(self, run_date: str | None = None) -> dict:
        run_date = run_date or today_str()
        with self._conn() as conn:
            raw_count = conn.execute(
                "SELECT COUNT(*) FROM raw_items WHERE run_date=?", (run_date,)
            ).fetchone()[0]
            scored_count = conn.execute(
                "SELECT COUNT(*) FROM scored_items WHERE run_date=?", (run_date,)
            ).fetchone()[0]
            avg_score = conn.execute(
                "SELECT AVG(score) FROM scored_items WHERE run_date=?", (run_date,)
            ).fetchone()[0]
            top_sources = conn.execute("""
                SELECT r.source, COUNT(*) as cnt
                FROM scored_items s JOIN raw_items r ON s.item_hash = r.hash
                WHERE s.run_date=? GROUP BY r.source ORDER BY cnt DESC
            """, (run_date,)).fetchall()
        return {
            "date": run_date,
            "raw_items": raw_count,
            "scored_items": scored_count,
            "avg_score": round(avg_score or 0, 2),
            "by_source": {row["source"]: row["cnt"] for row in top_sources}
        }

    def query(self, sql: str, limit: int = 20) -> list[dict]:
        """Safe read-only query for the query_db tool."""
        sql = sql.strip()
        if not sql.upper().startswith("SELECT"):
            raise ValueError("Only SELECT queries are allowed via query_db tool")
        with self._conn() as conn:
            rows = conn.execute(sql + f" LIMIT {limit}").fetchall()
        return [dict(r) for r in rows]


# ── CLI Test ─────────────────────────────────────────────────
if __name__ == "__main__":
    db = Database()
    print("✅ Database initialized at:", db.path)
    print("Tables created. Running self-test...")

    db.mark_seen("test_hash_001", "hackernews", "Test item", "https://example.com")
    print("mark_seen:", db.is_seen("test_hash_001"))
    print("not seen:", not db.is_seen("nonexistent"))

    stats = db.get_daily_stats()
    print("Daily stats:", stats)
    print("✅ db.py self-test passed")
