from __future__ import annotations
"""
setup_google.py — One-time Google OAuth2 setup for Calendar and Gmail access.

Run this ONCE on your machine. It will open a browser window, ask you to
sign in to Google, and save a token file. After that, fetch_calendar.py
and fetch_gmail.py work automatically.

Steps:
  1. Go to https://console.cloud.google.com
  2. Create a new project (e.g. "SmartDigest")
  3. Enable APIs:
       - Google Calendar API
       - Gmail API
  4. Go to APIs & Services → Credentials → Create Credentials → OAuth 2.0 Client ID
  5. Application type: Desktop app
  6. Download the JSON and save it as:  SmartDigest/state/google_credentials.json
  7. Run: python scripts/setup_google.py

Usage:
    python scripts/setup_google.py
    python scripts/setup_google.py --revoke   # clear saved token (re-authenticate)
"""

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from utils import get_project_root

TOKEN_PATH = get_project_root() / "state" / "google_token.json"
CREDS_PATH = get_project_root() / "state" / "google_credentials.json"

SCOPES = [
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/gmail.readonly",
]


def setup():
    try:
        from google_auth_oauthlib.flow import InstalledAppFlow
        from googleapiclient.discovery import build
    except ImportError:
        print("❌ Missing packages. Run:")
        print("   pip install google-auth google-auth-oauthlib google-api-python-client")
        sys.exit(1)

    if not CREDS_PATH.exists():
        print(f"❌ Credentials file not found: {CREDS_PATH}")
        print()
        print("Steps to create it:")
        print("  1. Go to https://console.cloud.google.com")
        print("  2. Create project → Enable Calendar API + Gmail API")
        print("  3. Create OAuth 2.0 Client ID (Desktop app)")
        print("  4. Download JSON → save as SmartDigest/state/google_credentials.json")
        sys.exit(1)

    print("🔐 Starting Google OAuth2 flow...")
    print("   A browser window will open. Sign in and grant permissions.")
    print()

    flow = InstalledAppFlow.from_client_secrets_file(str(CREDS_PATH), SCOPES)
    creds = flow.run_local_server(port=0)

    TOKEN_PATH.write_text(creds.to_json())
    print(f"✅ Token saved to: {TOKEN_PATH}")

    # Quick verification
    print()
    print("🔍 Verifying Calendar access...")
    svc = build("calendar", "v3", credentials=creds)
    cal_list = svc.calendarList().list(maxResults=3).execute()
    cals = cal_list.get("items", [])
    print(f"   Found {len(cals)} calendar(s):")
    for c in cals:
        print(f"   - {c.get('summary', '(unnamed)')}")

    print()
    print("🔍 Verifying Gmail access...")
    gmail_svc = build("gmail", "v1", credentials=creds)
    profile = gmail_svc.users().getProfile(userId="me").execute()
    print(f"   Gmail account: {profile.get('emailAddress')}")
    print(f"   Total messages: {profile.get('messagesTotal', '?')}")

    print()
    print("✅ Google setup complete! fetch_calendar.py and fetch_gmail.py are ready.")


def revoke():
    if TOKEN_PATH.exists():
        TOKEN_PATH.unlink()
        print(f"✅ Token revoked. Deleted: {TOKEN_PATH}")
        print("   Run setup_google.py again to re-authenticate.")
    else:
        print("No token found — nothing to revoke.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Google OAuth2 setup for SmartDigest")
    parser.add_argument("--revoke", action="store_true", help="Clear saved token")
    args = parser.parse_args()

    if args.revoke:
        revoke()
    else:
        setup()
