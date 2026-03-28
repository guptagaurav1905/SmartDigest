from __future__ import annotations
"""
fetch_gmail.py — Fetches Gmail unread summary for SOD briefing.

Requires: python scripts/setup_google.py (one-time OAuth setup)
Scopes needed: gmail.readonly

Usage:
    python scripts/fetch_gmail.py                # unread from last 3 days (default)
    python scripts/fetch_gmail.py --days 3       # explicitly last 3 days
    python scripts/fetch_gmail.py --days 7       # last 7 days
    python scripts/fetch_gmail.py --dry-run      # print to terminal, no file write
    python scripts/fetch_gmail.py --max 20       # max emails to fetch
"""

import argparse
import base64
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import get_project_root, load_config, update_last_run, now_iso

TOKEN_PATH = get_project_root() / "state" / "google_token.json"
CREDS_PATH = get_project_root() / "state" / "google_credentials.json"
SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly"
]


def get_gmail_service():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("[gmail] ERROR: Run: pip install google-auth google-auth-oauthlib google-api-python-client")
        sys.exit(1)

    if not CREDS_PATH.exists():
        print(f"[gmail] ERROR: Run: python scripts/setup_google.py")
        sys.exit(1)

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json())

    return build("gmail", "v1", credentials=creds)


def decode_body(part: dict) -> str:
    data = part.get("body", {}).get("data", "")
    if not data:
        return ""
    try:
        decoded = base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="ignore")
        # Strip HTML tags
        decoded = re.sub(r"<[^>]+>", " ", decoded)
        decoded = re.sub(r"\s+", " ", decoded).strip()
        return decoded[:500]
    except Exception:
        return ""


def fetch_unread_emails(service, max_results: int = 15, days: int = 3) -> list[dict]:
    cfg = load_config("sod_config.json")
    gmail_cfg = cfg.get("gmail", {})
    labels = gmail_cfg.get("labels", ["INBOX"])
    important_senders = gmail_cfg.get("important_senders", [])

    # Date filter — only emails from the last N days
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y/%m/%d")

    query_parts = [f"is:unread after:{cutoff_date}"]
    if important_senders:
        sender_query = " OR ".join(f"from:{s}" for s in important_senders)
        query_parts.append(f"({sender_query})")
    query = " ".join(query_parts)
    print(f"[gmail] Query: {query}")

    try:
        result = service.users().messages().list(
            userId="me",
            q=query,
            maxResults=max_results,
            labelIds=labels
        ).execute()
    except Exception as e:
        print(f"[gmail] API error: {e}", file=sys.stderr)
        return []

    messages = result.get("messages", [])
    emails = []

    for msg_ref in messages:
        try:
            msg = service.users().messages().get(
                userId="me",
                id=msg_ref["id"],
                format="full"
            ).execute()

            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            subject = headers.get("Subject", "(no subject)")
            sender  = headers.get("From", "Unknown")
            date    = headers.get("Date", "")

            # Extract snippet
            snippet = msg.get("snippet", "")[:300]

            # Determine importance
            label_ids = msg.get("labelIds", [])
            is_important = "IMPORTANT" in label_ids or "STARRED" in label_ids

            emails.append({
                "subject":      subject,
                "from":         sender,
                "date":         date,
                "snippet":      snippet,
                "is_important": is_important,
                "labels":       label_ids,
                "message_id":   msg_ref["id"]
            })
        except Exception as e:
            print(f"[gmail] Error fetching message {msg_ref['id']}: {e}", file=sys.stderr)
            continue

    # Sort: important first
    emails.sort(key=lambda e: (not e["is_important"], e["date"]))
    return emails


def format_for_briefing(emails: list[dict]) -> str:
    if not emails:
        return "📧 *Gmail* — Inbox zero! 🎉 No unread emails."

    important = [e for e in emails if e["is_important"]]
    others    = [e for e in emails if not e["is_important"]]

    lines = [f"📧 *Gmail — {len(emails)} unread*"]

    if important:
        lines.append(f"\n⭐ *Important ({len(important)}):*")
        for e in important[:3]:
            sender_short = re.sub(r"<.*?>", "", e["from"]).strip()
            lines.append(f"  • *{e['subject'][:50]}*\n    _From: {sender_short}_\n    {e['snippet'][:100]}...")

    if others:
        lines.append(f"\n📬 *Other unread ({len(others)}):*")
        for e in others[:5]:
            sender_short = re.sub(r"<.*?>", "", e["from"]).strip()
            lines.append(f"  • {e['subject'][:60]} — _{sender_short}_")

    return "\n".join(lines)


def run(max_results: int = 15, days: int = 3, dry_run: bool = False) -> list[dict]:
    print(f"[gmail] Fetching up to {max_results} unread emails from last {days} day(s)...")
    try:
        service = get_gmail_service()
        emails = fetch_unread_emails(service, max_results, days=days)
        important_count = sum(1 for e in emails if e["is_important"])
        print(f"[gmail] Found {len(emails)} unread emails ({important_count} important) from last {days} days")

        if dry_run:
            print(format_for_briefing(emails))
            return emails

        out_path = get_project_root() / "data" / "sod" / "gmail.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({
            "fetched_at": now_iso(),
            "days_filter": days,
            "emails": emails
        }, indent=2))
        print(f"[gmail] ✅ Saved to {out_path}")
        update_last_run("fetch-gmail", "success", f"{len(emails)} unread (last {days} days)")
        return emails

    except SystemExit:
        raise
    except Exception as e:
        print(f"[gmail] ERROR: {e}", file=sys.stderr)
        update_last_run("fetch-gmail", "failure", str(e))
        return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--max",  type=int, default=15,  help="Max emails to fetch")
    parser.add_argument("--days", type=int, default=3,   help="Only unread from last N days (default: 3)")
    parser.add_argument("--dry-run", action="store_true", help="Print output, don't save file")
    args = parser.parse_args()
    run(max_results=args.max, days=args.days, dry_run=args.dry_run)
