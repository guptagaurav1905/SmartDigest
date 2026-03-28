from __future__ import annotations
"""
tool_registry.py — Central tool schema definitions for SmartDigest Phase 4.

These tool schemas are passed to Claude / OpenClaw so the agent can call
SmartDigest functions natively as tools instead of running exec commands.

Usage (in skill context):
    from tools.tool_registry import TOOLS, dispatch_tool
    result = dispatch_tool("fetch_source", {"source": "hackernews"})
"""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

# ── Tool Schemas (OpenAI-compatible format) ────────────────────────────────

TOOLS = [
    {
        "name": "fetch_source",
        "description": (
            "Fetch fresh content from one or all configured sources. "
            "Runs the appropriate fetch script and returns item count per source."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["github", "hackernews", "rss", "arxiv", "slack", "all"],
                    "description": "Which source to fetch. Use 'all' for full pipeline run."
                },
                "dry_run": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, fetch and return items without writing to DB."
                },
                "date": {
                    "type": "string",
                    "description": "Target date YYYY-MM-DD. Defaults to today."
                }
            },
            "required": ["source"]
        }
    },
    {
        "name": "score_items",
        "description": (
            "Score raw collected items for relevance using Groq or Claude. "
            "Reads from DB, writes scored results back to DB."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {
                    "type": "string",
                    "description": "Date to score YYYY-MM-DD. Defaults to today."
                },
                "model": {
                    "type": "string",
                    "default": "groq/llama-3.3-70b-versatile",
                    "description": "Model to use for scoring."
                }
            },
            "required": []
        }
    },
    {
        "name": "deliver_briefing",
        "description": (
            "Compose and deliver a briefing to one or more channels. "
            "Supports SOD (morning) and EOD (evening) briefing types."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "channels": {
                    "type": "array",
                    "items": {"type": "string", "enum": ["telegram", "whatsapp", "slack"]},
                    "description": "List of delivery channels."
                },
                "briefing_type": {
                    "type": "string",
                    "enum": ["sod", "eod"],
                    "default": "sod",
                    "description": "sod = Start of Day (morning). eod = End of Day (evening)."
                },
                "date": {
                    "type": "string",
                    "description": "Date YYYY-MM-DD. Defaults to today."
                },
                "preview": {
                    "type": "boolean",
                    "default": False,
                    "description": "If true, return briefing text without sending."
                }
            },
            "required": ["channels"]
        }
    },
    {
        "name": "query_db",
        "description": (
            "Run a read-only SQL SELECT query against the SmartDigest database. "
            "Tables: seen_items, raw_items, scored_items, pipeline_runs, briefings."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "sql": {
                    "type": "string",
                    "description": "A SQL SELECT query. Must start with SELECT."
                },
                "limit": {
                    "type": "integer",
                    "default": 20,
                    "description": "Max rows to return."
                }
            },
            "required": ["sql"]
        }
    },
    {
        "name": "get_pipeline_status",
        "description": "Return today's pipeline run status per stage with item counts.",
        "input_schema": {
            "type": "object",
            "properties": {
                "date": {"type": "string", "description": "YYYY-MM-DD, defaults to today"}
            },
            "required": []
        }
    },
    {
        "name": "fetch_sod_context",
        "description": (
            "Fetch all Start-of-Day context: weather, calendar events, gmail summary. "
            "Returns structured data for SOD briefing composition."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "include_weather":  {"type": "boolean", "default": True},
                "include_calendar": {"type": "boolean", "default": True},
                "include_gmail":    {"type": "boolean", "default": True}
            },
            "required": []
        }
    }
]


# ── Tool Dispatcher ─────────────────────────────────────────────────────────

def dispatch_tool(tool_name: str, tool_input: dict) -> dict:
    """
    Route a tool call to the correct handler module.
    Returns a dict: {"success": bool, "result": any, "error": str | None}
    """
    try:
        if tool_name == "fetch_source":
            from tool_fetch import handle_fetch_source
            return handle_fetch_source(tool_input)

        elif tool_name == "score_items":
            from tool_score import handle_score_items
            return handle_score_items(tool_input)

        elif tool_name == "deliver_briefing":
            from tool_deliver import handle_deliver_briefing
            return handle_deliver_briefing(tool_input)

        elif tool_name == "query_db":
            from db import Database
            db = Database()
            rows = db.query(tool_input["sql"], limit=tool_input.get("limit", 20))
            return {"success": True, "result": rows, "count": len(rows)}

        elif tool_name == "get_pipeline_status":
            from db import Database
            db = Database()
            date = tool_input.get("date")
            summary = db.get_run_summary(date)
            stats = db.get_daily_stats(date)
            return {"success": True, "result": {"runs": summary, "stats": stats}}

        elif tool_name == "fetch_sod_context":
            from tool_fetch import handle_fetch_sod_context
            return handle_fetch_sod_context(tool_input)

        else:
            return {"success": False, "error": f"Unknown tool: {tool_name}"}

    except Exception as e:
        return {"success": False, "error": str(e), "result": None}


if __name__ == "__main__":
    print(f"✅ {len(TOOLS)} tools registered:")
    for t in TOOLS:
        print(f"   - {t['name']}: {t['description'][:60]}...")
