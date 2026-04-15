"""
TraceStore — SQLite-backed persistence for LLMTrace objects.
Lightweight, zero-infra, works everywhere. Swap for Postgres in prod.
"""

import sqlite3
import json
from pathlib import Path
from typing import List, Optional, Dict, Any
from .observer import LLMTrace


class TraceStore:
    """
    Local SQLite store.  One row = one LLM call.

    Usage:
        store = TraceStore("db/genai_traces.db")
        store.save(trace)
        df = store.to_dataframe()
    """

    DDL = """
    CREATE TABLE IF NOT EXISTS llm_traces (
        trace_id          TEXT PRIMARY KEY,
        usecase           TEXT,
        model             TEXT,
        prompt            TEXT,
        response          TEXT,
        prompt_tokens     INTEGER,
        completion_tokens INTEGER,
        total_tokens      INTEGER,
        latency_ms        REAL,
        status            TEXT,
        error_message     TEXT,
        cost_usd          REAL,
        metadata          TEXT,
        created_at        TEXT
    )
    """

    def __init__(self, db_path: str = "genai_traces.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(self.DDL)
            conn.execute("CREATE INDEX IF NOT EXISTS idx_usecase ON llm_traces(usecase)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_created ON llm_traces(created_at)")

    def save(self, trace: LLMTrace):
        d = trace.to_dict()
        d["metadata"] = json.dumps(d.get("metadata", {}))
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """INSERT OR REPLACE INTO llm_traces VALUES
                   (:trace_id, :usecase, :model, :prompt, :response,
                    :prompt_tokens, :completion_tokens, :total_tokens,
                    :latency_ms, :status, :error_message, :cost_usd,
                    :metadata, :created_at)""",
                d,
            )

    def fetch(
        self,
        usecase: Optional[str] = None,
        model: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 1000,
    ) -> List[Dict[str, Any]]:
        query = "SELECT * FROM llm_traces WHERE 1=1"
        params = []
        if usecase:
            query += " AND usecase = ?"; params.append(usecase)
        if model:
            query += " AND model = ?"; params.append(model)
        if status:
            query += " AND status = ?"; params.append(status)
        query += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)

        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(query, params).fetchall()
        return [dict(r) for r in rows]

    def summary_stats(self) -> Dict[str, Any]:
        """Quick aggregates for dashboard cards."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            stats = conn.execute("""
                SELECT
                    COUNT(*) as total_calls,
                    SUM(CASE WHEN status='ok' THEN 1 ELSE 0 END) as ok_calls,
                    SUM(CASE WHEN status='error' THEN 1 ELSE 0 END) as error_calls,
                    AVG(latency_ms) as avg_latency_ms,
                    MAX(latency_ms) as max_latency_ms,
                    SUM(total_tokens) as total_tokens,
                    SUM(cost_usd) as total_cost_usd
                FROM llm_traces
            """).fetchone()
        return dict(stats) if stats else {}

    def to_dataframe(self):
        """Returns a pandas DataFrame — call only when pandas is available."""
        import pandas as pd
        rows = self.fetch(limit=100_000)
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df["created_at"] = pd.to_datetime(df["created_at"])
        df["metadata"] = df["metadata"].apply(
            lambda x: json.loads(x) if isinstance(x, str) else {}
        )
        return df

    def clear(self):
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("DELETE FROM llm_traces")
