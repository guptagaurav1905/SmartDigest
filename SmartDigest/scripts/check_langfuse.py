"""
check_langfuse.py — Verify Langfuse connectivity and send a test trace.

Usage:
    python3 scripts/check_langfuse.py

Checks:
    1. Env vars are set
    2. API keys are valid (hits /api/public/projects)
    3. Sends a real test trace and prints the URL to view it
"""

import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parent.parent))

from utils import get_project_root
from observability import get_langfuse_client

import os

def main():
    print("\n── Langfuse Health Check ──────────────────────────")

    # 1. Env vars
    pub  = os.environ.get("LANGFUSE_PUBLIC_KEY", "")
    sec  = os.environ.get("LANGFUSE_SECRET_KEY", "")
    host = os.environ.get("LANGFUSE_BASE_URL") or os.environ.get("LANGFUSE_HOST") or "https://cloud.langfuse.com"

    print(f"  PUBLIC_KEY : {'✅ ' + pub[:12] + '...' if pub else '❌ not set'}")
    print(f"  SECRET_KEY : {'✅ ' + sec[:12] + '...' if sec else '❌ not set'}")
    print(f"  HOST       : {host}")

    if not pub or not sec:
        print("\n❌ Missing keys. Add to .env:")
        print("   LANGFUSE_PUBLIC_KEY=pk-lf-...")
        print("   LANGFUSE_SECRET_KEY=sk-lf-...")
        sys.exit(1)

    # 2. Connection check
    client = get_langfuse_client()
    if not client:
        print("\n❌ Could not create client")
        sys.exit(1)

    print("\n  Testing connection...")
    ok, msg, project_id = client.check_connection()
    if ok:
        print(f"  ✅ {msg}")
    else:
        print(f"  ❌ {msg}")
        sys.exit(1)

    # 3. Send test trace
    print("\n  Sending test trace...")
    trace_id = str(uuid.uuid4())
    sent = client.send_generation(
        trace_id=trace_id,
        name="smartdigest-health-check",
        model="llama-3.3-70b-versatile",
        input_text="[health-check] Is Langfuse receiving traces?",
        output_text="[health-check] Yes, SmartDigest observability is connected.",
        prompt_tokens=12,
        completion_tokens=10,
        latency_ms=42.0,
        status="ok",
        metadata={"source": "check_langfuse.py"},
    )

    if sent:
        print(f"  ✅ Trace sent!")
        print(f"\n  View it at:")
        print(f"  {host}/project/{project_id}/traces/{trace_id}")
    else:
        print("  ❌ Trace send failed — check output above for HTTP error")
        sys.exit(1)

    print("\n── All checks passed ✅ ────────────────────────────\n")


if __name__ == "__main__":
    main()
