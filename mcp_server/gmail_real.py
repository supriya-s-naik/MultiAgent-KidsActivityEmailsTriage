"""
Real Gmail MCP server.

Same tool, same shape, as mcp_server/gmail_mock.py: one tool, list_emails(),
returning a list of {id, from, subject, body, date}. Only the data source
differs -- this one calls the live Gmail API instead of reading
data/sample_emails.json. Every agent downstream of the MCP client is
unchanged; main.py just points at this script instead of gmail_mock.py.

Requires mcp_server/token.json, produced once by running:
    python mcp_server/gmail_auth_setup.py
(see that file's docstring, and README.md, for the OAuth setup steps).

Design note: this fetches up to MAX_RESULTS messages matching GMAIL_QUERY
rather than paginating the whole mailbox -- fine for a personal digest
tool, but a mailbox with more matches than MAX_RESULTS would need real
pagination via nextPageToken.

GMAIL_QUERY uses Gmail's own search syntax (the same operators as the
Gmail search box: newer_than:, from:, subject:, label:, plain keywords,
combined with OR/AND/parentheses) rather than a custom sender/keyword
filter -- Gmail already does this well, so there's no reason to
reimplement it. Set it in .env, e.g.:
    GMAIL_QUERY=newer_than:2d (from:coach.miller@northsideyouthsoccer.org OR from:*@lincolnelementary.edu OR subject:permission OR subject:RSVP)
"""

import base64
import os
from email.utils import parsedate_to_datetime
from pathlib import Path

from dotenv import load_dotenv
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from mcp.server.mcpserver import MCPServer

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
MCP_SERVER_DIR = Path(__file__).resolve().parent
TOKEN_PATH = MCP_SERVER_DIR / "token.json"
MAX_RESULTS = 20
GMAIL_QUERY = os.environ.get("GMAIL_QUERY", "newer_than:1d")

# A real inbox includes marketing/HTML-only emails whose body can run past
# 100K characters (raw HTML, no text/plain part). Truncating keeps each
# classifier/extractor LLM call fast and cheap; the first few thousand
# characters are enough to tell what an email is about.
MAX_BODY_CHARS = 4000

mcp = MCPServer("gmail-real")


def _get_service():
    if not TOKEN_PATH.exists():
        raise RuntimeError(
            f"Missing {TOKEN_PATH}. Run `python mcp_server/gmail_auth_setup.py` "
            "once to authorize this app before starting the server."
        )

    creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)
    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            TOKEN_PATH.write_text(creds.to_json(), encoding="utf-8")
        else:
            raise RuntimeError(
                "Stored Gmail token is invalid and has no refresh token. "
                "Delete mcp_server/token.json and re-run gmail_auth_setup.py."
            )

    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _header(headers: list[dict], name: str) -> str:
    for header in headers:
        if header["name"].lower() == name.lower():
            return header["value"]
    return ""


def _extract_body(payload: dict) -> str:
    """Walk a (possibly multipart) message payload and return the plain-text body."""
    if payload.get("mimeType") == "text/plain" and payload.get("body", {}).get("data"):
        return base64.urlsafe_b64decode(payload["body"]["data"]).decode("utf-8", errors="replace")

    for part in payload.get("parts", []):
        text = _extract_body(part)
        if text:
            return text

    # Fall back to whatever body data is present (e.g. text/html) if no
    # text/plain part was found.
    data = payload.get("body", {}).get("data")
    if data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    return ""


@mcp.tool()
def list_emails(query: str | None = None) -> list[dict]:
    """Return up to MAX_RESULTS inbox emails, each with id, from, subject, body, date.

    `query` uses Gmail's search syntax (from:, subject:, newer_than:, after:,
    before:, plain keywords, ...) and overrides GMAIL_QUERY for this one call
    -- lets a caller (e.g. bot.py's slash command) filter a single run
    without changing the .env default used by main.py's scheduled/manual run.
    """
    service = _get_service()
    effective_query = query or GMAIL_QUERY

    message_ids = (
        service.users()
        .messages()
        .list(userId="me", labelIds=["INBOX"], q=effective_query, maxResults=MAX_RESULTS)
        .execute()
        .get("messages", [])
    )

    emails = []
    for msg_ref in message_ids:
        message = (
            service.users()
            .messages()
            .get(userId="me", id=msg_ref["id"], format="full")
            .execute()
        )
        headers = message["payload"].get("headers", [])
        date_header = _header(headers, "Date")
        try:
            date_iso = parsedate_to_datetime(date_header).isoformat()
        except (TypeError, ValueError):
            date_iso = date_header

        emails.append(
            {
                "id": message["id"],
                "from": _header(headers, "From"),
                "subject": _header(headers, "Subject"),
                "body": _extract_body(message["payload"])[:MAX_BODY_CHARS],
                "date": date_iso,
            }
        )

    return emails


if __name__ == "__main__":
    mcp.run(transport="stdio")
