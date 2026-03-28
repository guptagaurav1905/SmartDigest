from __future__ import annotations
"""
fetch_calendar.py — Fetches today's Google Calendar events for SOD briefing.

Requires one-time setup: python scripts/setup_google.py
Then: state/google_token.json is created automatically.

Usage:
    python scripts/fetch_calendar.py
    python scripts/fetch_calendar.py --dry-run
    python scripts/fetch_calendar.py --days 1    # look ahead N days
"""

import argparse
import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import get_project_root, update_last_run, now_iso

TOKEN_PATH  = get_project_root() / "state" / "google_token.json"
CREDS_PATH  = get_project_root() / "state" / "google_credentials.json"
SCOPES      = ["https://www.googleapis.com/auth/calendar.readonly"]


def get_calendar_service():
    try:
        from google.oauth2.credentials import Credentials
        from google.auth.transport.requests import Request
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("[calendar] ERROR: Missing packages.", file=sys.stderr)
        print("Run: pip install google-auth google-auth-oauthlib google-api-python-client", file=sys.stderr)
        sys.exit(1)

    if not CREDS_PATH.exists():
        print(f"[calendar] ERROR: {CREDS_PATH} not found.", file=sys.stderr)
        print("Run: python scripts/setup_google.py", file=sys.stderr)
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

    return build("calendar", "v3", credentials=creds)


def fetch_events(service, days_ahead: int = 1) -> list[dict]:
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=days_ahead)

    result = service.events().list(
        calendarId="primary",
        timeMin=now.isoformat(),
        timeMax=end.isoformat(),
        maxResults=20,
        singleEvents=True,
        orderBy="startTime"
    ).execute()

    events = []
    for ev in result.get("items", []):
        start = ev.get("start", {})
        end_t = ev.get("end", {})

        # All-day events have "date", timed events have "dateTime"
        if "dateTime" in start:
            start_dt = datetime.fromisoformat(start["dateTime"])
            end_dt   = datetime.fromisoformat(end_t["dateTime"])
            duration_min = int((end_dt - start_dt).total_seconds() / 60)
            time_str  = start_dt.strftime("%I:%M %p")
            is_allday = False
        else:
            time_str     = "All day"
            duration_min = 0
            is_allday    = True

        attendees = ev.get("attendees", [])
        attendee_names = [
            a.get("displayName") or a.get("email", "")
            for a in attendees
            if not a.get("self", False)
        ]

        events.append({
            "title":        ev.get("summary", "Untitled Event"),
            "time":         time_str,
            "duration_min": duration_min,
            "location":     ev.get("location", ""),
            "description":  (ev.get("description", "") or "")[:200],
            "attendees":    attendee_names[:5],
            "is_allday":    is_allday,
            "meet_link":    ev.get("hangoutLink", ""),
            "status":       ev.get("status", "confirmed")
        })

    return events


def format_for_briefing(events: list[dict]) -> str:
    if not events:
        return "📅 *Calendar* — No meetings today. Free day! 🎉"

    lines = [f"📅 *Today's Calendar — {len(events)} event(s)*\n"]
    for ev in events:
        icon = "🕐" if not ev["is_allday"] else "📌"
        line = f"{icon} *{ev['time']}* — {ev['title']}"
        if ev["duration_min"]:
            h, m = divmod(ev["duration_min"], 60)
            dur = f"{h}h {m}m" if h else f"{m}m"
            line += f" _{dur}_"
        if ev["location"]:
            line += f"\n   📍 {ev['location']}"
        if ev["meet_link"]:
            line += f"\n   🔗 [Join Meet]({ev['meet_link']})"
        if ev["attendees"]:
            line += f"\n   👥 {', '.join(ev['attendees'][:3])}"
            if len(ev["attendees"]) > 3:
                line += f" +{len(ev['attendees'])-3} more"
        lines.append(line)

    return "\n\n".join(lines)


def run(days_ahead: int = 1, dry_run: bool = False) -> list[dict]:
    print("[calendar] Fetching today's events...")
    try:
        service = get_calendar_service()
        events = fetch_events(service, days_ahead)
        print(f"[calendar] Found {len(events)} events")

        if dry_run:
            print(format_for_briefing(events))
            return events

        out_path = get_project_root() / "data" / "sod" / "calendar.json"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(json.dumps({
            "fetched_at": now_iso(),
            "events": events
        }, indent=2))
        print(f"[calendar] ✅ Saved to {out_path}")
        update_last_run("fetch-calendar", "success", f"{len(events)} events")
        return events

    except SystemExit:
        raise
    except Exception as e:
        print(f"[calendar] ERROR: {e}", file=sys.stderr)
        update_last_run("fetch-calendar", "failure", str(e))
        return []


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    run(days_ahead=args.days, dry_run=args.dry_run)
