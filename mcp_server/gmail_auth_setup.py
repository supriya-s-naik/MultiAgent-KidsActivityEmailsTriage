"""
One-time OAuth setup for real Gmail access.

Run this manually once (not part of the MCP server, and not started
automatically by main.py):

    python mcp_server/gmail_auth_setup.py

It opens a browser for the Google consent screen using the Desktop-app
OAuth client at mcp_server/credentials.json (downloaded from Google Cloud
Console -> APIs & Services -> Credentials), then saves the resulting
refresh token to mcp_server/token.json. gmail_real.py reads that token file
and refreshes it automatically on later runs -- this script only needs to
be re-run if token.json is deleted or the refresh token is revoked.

Scope: gmail.readonly is enough since this pipeline never writes to Gmail.
"""

from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]

MCP_SERVER_DIR = Path(__file__).resolve().parent
CREDENTIALS_PATH = MCP_SERVER_DIR / "credentials.json"
TOKEN_PATH = MCP_SERVER_DIR / "token.json"


def main() -> None:
    if not CREDENTIALS_PATH.exists():
        raise SystemExit(
            f"Missing {CREDENTIALS_PATH}. Download the OAuth client JSON from "
            "Google Cloud Console (APIs & Services > Credentials > your Desktop "
            "client) and save it there first."
        )

    creds = None
    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")

    print(f"Auth OK. Token saved to {TOKEN_PATH}")


if __name__ == "__main__":
    main()
