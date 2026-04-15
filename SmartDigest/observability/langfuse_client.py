"""
observability/langfuse_client.py — Langfuse integration via direct HTTP API.

Uses Langfuse's REST ingestion endpoint directly — no SDK version issues.
Works with Langfuse Cloud (cloud.langfuse.com) or any self-hosted instance.

Required env vars (add to .env):
    LANGFUSE_PUBLIC_KEY    pk-lf-...
    LANGFUSE_SECRET_KEY    sk-lf-...
    LANGFUSE_BASE_URL      https://cloud.langfuse.com  (or your host)
"""

import base64
import json
import os
import urllib.request
import urllib.error
import uuid
from datetime import datetime, timezone


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _auth_header(public_key: str, secret_key: str) -> str:
    token = base64.b64encode(f"{public_key}:{secret_key}".encode()).decode()
    return f"Basic {token}"


class LangfuseHTTPClient:
    """
    Minimal Langfuse client using the REST ingestion API directly.
    No SDK required — works with any Langfuse version.
    """

    def __init__(self, public_key: str, secret_key: str, host: str):
        self.public_key = public_key
        self.secret_key = secret_key
        self.host = host.rstrip("/")
        self._queue: list = []

    def _ingest(self, events: list) -> bool:
        """POST a batch of events to /api/public/ingestion."""
        url = f"{self.host}/api/public/ingestion"
        payload = json.dumps({"batch": events}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "Authorization": _auth_header(self.public_key, self.secret_key),
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status in (200, 201, 207)
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            print(f"[langfuse] HTTP {e.code}: {body}")
            return False
        except Exception as e:
            print(f"[langfuse] Request failed: {e}")
            return False

    def send_generation(
        self,
        *,
        trace_id: str,
        name: str,
        model: str,
        input_text: str,
        output_text: str,
        prompt_tokens: int,
        completion_tokens: int,
        latency_ms: float,
        status: str,
        error_message: str = "",
        metadata: dict = None,
    ) -> bool:
        """Send a trace + generation as a single ingestion batch."""
        ts = _now()
        level = "ERROR" if status == "error" else "DEFAULT"

        events = [
            {
                "id":        str(uuid.uuid4()),
                "type":      "trace-create",
                "timestamp": ts,
                "body": {
                    "id":       trace_id,
                    "name":     name,
                    "metadata": {"status": status, **(metadata or {})},
                },
            },
            {
                "id":        str(uuid.uuid4()),
                "type":      "generation-create",
                "timestamp": ts,
                "body": {
                    "traceId":        trace_id,
                    "name":           "llm_call",
                    "model":          model,
                    "input":          input_text,
                    "output":         output_text if status != "error" else None,
                    "level":          level,
                    "statusMessage":  error_message or None,
                    "usage": {
                        "input":  prompt_tokens,
                        "output": completion_tokens,
                        "total":  prompt_tokens + completion_tokens,
                    },
                    "metadata": {
                        "latency_ms": latency_ms,
                        **(metadata or {}),
                    },
                },
            },
        ]
        return self._ingest(events)

    def check_connection(self) -> tuple[bool, str, str]:
        """
        Verify API keys are valid by hitting /api/public/projects.
        Returns (ok: bool, message: str, project_id: str).
        """
        url = f"{self.host}/api/public/projects"
        req = urllib.request.Request(
            url,
            headers={"Authorization": _auth_header(self.public_key, self.secret_key)},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())
                projects = data.get("data", [])
                if not projects:
                    return False, "No projects found for these keys", ""
                project = projects[0]
                project_id   = project.get("id", "")
                project_name = project.get("name", project_id)
                return True, f"Connected — project: '{project_name}' (id: {project_id})", project_id
        except urllib.error.HTTPError as e:
            body = e.read().decode()
            if e.code == 401:
                return False, "Invalid API keys (401 Unauthorized)", ""
            return False, f"HTTP {e.code}: {body[:200]}", ""
        except Exception as e:
            return False, f"Connection error: {e}", ""


def get_langfuse_client() -> "LangfuseHTTPClient | None":
    """
    Build and return a LangfuseHTTPClient from env vars.
    Returns None if keys are missing — @observe handles None gracefully.
    """
    public_key = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    secret_key  = os.environ.get("LANGFUSE_SECRET_KEY", "")
    host        = (os.environ.get("LANGFUSE_HOST")
                   or os.environ.get("LANGFUSE_BASE_URL")
                   or "https://cloud.langfuse.com")

    if not public_key or not secret_key:
        return None

    client = LangfuseHTTPClient(public_key, secret_key, host)
    print(f"[langfuse] Client ready → {host}")
    return client
