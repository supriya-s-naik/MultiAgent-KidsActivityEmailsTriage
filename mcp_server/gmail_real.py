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

Design note: this paginates through Gmail's own list results (via
nextPageToken) until either the query runs out of matches or
MAX_TOTAL_RESULTS is hit, rather than stopping at one page. That matters
for a bounded query like `newer_than:2d`: a noisy inbox can easily have
more than one page's worth of messages in that window, and a relevant
email (e.g. from a teacher) can sort well behind a burst of newsletters/
marketing -- stopping at the first page silently drops it before the
classifier ever sees it. MAX_TOTAL_RESULTS is still a safety cap, not
true unlimited pagination, to keep a single run's Gmail + LLM calls bounded.

GMAIL_QUERY uses Gmail's own search syntax (the same operators as the
Gmail search box: newer_than:, from:, subject:, label:, plain keywords,
combined with OR/AND/parentheses) rather than a custom sender/keyword
filter -- Gmail already does this well, so there's no reason to
reimplement it. Set it in .env, e.g.:
    GMAIL_QUERY=newer_than:2d (from:coach.miller@northsideyouthsoccer.org OR from:*@lincolnelementary.edu OR subject:permission OR subject:RSVP)
"""

import base64
import os
import threading
from concurrent.futures import ThreadPoolExecutor
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

# Safety cap across all pages for a single list_emails() call (not true
# unlimited pagination -- see the module docstring).
MAX_TOTAL_RESULTS = 150
# Gmail's own page size cap is 500; 100 keeps each individual list() call modest.
PAGE_SIZE = 100
# Fetching each message's full content is a separate blocking API call;
# a thread pool overlaps them instead of doing up to MAX_TOTAL_RESULTS of
# them one at a time (same reasoning as agents/llm_client.run_concurrently).
FETCH_WORKERS = 10

GMAIL_QUERY = os.environ.get("GMAIL_QUERY", "newer_than:1d")

# A real inbox includes marketing/HTML-only emails whose body can run past
# 100K characters (raw HTML, no text/plain part). Truncating keeps each
# classifier/extractor LLM call fast and cheap; the first few thousand
# characters are enough to tell what an email is about.
MAX_BODY_CHARS = 4000

mcp = MCPServer("gmail-real")

_thread_local = threading.local()


def _get_credentials() -> Credentials:
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

    return creds


def _get_thread_service(creds: Credentials):
    """google-api-python-client Resource objects aren't safe to share across
    threads, so each worker thread in the fetch pool gets (and reuses) its
    own, built from the same already-validated credentials."""
    if not hasattr(_thread_local, "service"):
        _thread_local.service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    return _thread_local.service


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


def _list_message_refs(service, effective_query: str) -> list[dict]:
    """Page through Gmail's list results for effective_query, up to MAX_TOTAL_RESULTS."""
    message_refs = []
    page_token = None
    while len(message_refs) < MAX_TOTAL_RESULTS:
        page = (
            service.users()
            .messages()
            .list(
                userId="me",
                labelIds=["INBOX"],
                q=effective_query,
                maxResults=min(PAGE_SIZE, MAX_TOTAL_RESULTS - len(message_refs)),
                pageToken=page_token,
            )
            .execute()
        )
        message_refs.extend(page.get("messages", []))
        page_token = page.get("nextPageToken")
        if not page_token:
            break
    return message_refs


def _fetch_email(creds: Credentials, msg_ref: dict) -> dict:
    service = _get_thread_service(creds)
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

    return {
        "id": message["id"],
        "from": _header(headers, "From"),
        "subject": _header(headers, "Subject"),
        "body": _extract_body(message["payload"])[:MAX_BODY_CHARS],
        "date": date_iso,
    }


@mcp.tool()
def list_emails(query: str | None = None) -> list[dict]:
    """Return up to MAX_TOTAL_RESULTS inbox emails matching the query, each with id, from, subject, body, date.

    `query` uses Gmail's search syntax (from:, subject:, newer_than:, after:,
    before:, plain keywords, ...) and overrides GMAIL_QUERY for this one call
    -- lets a caller (e.g. bot.py's slash command) filter a single run
    without changing the .env default used by main.py's scheduled/manual run.
    """
    creds = _get_credentials()
    service = build("gmail", "v1", credentials=creds, cache_discovery=False)
    effective_query = query or GMAIL_QUERY

    message_refs = _list_message_refs(service, effective_query)
    if not message_refs:
        return []

    with ThreadPoolExecutor(max_workers=min(FETCH_WORKERS, len(message_refs))) as executor:
        emails = list(executor.map(lambda ref: _fetch_email(creds, ref), message_refs))

    return emails


if __name__ == "__main__":
    mcp.run(transport="stdio")
