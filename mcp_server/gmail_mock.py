"""
Mock Gmail MCP server.

This is the offline/sample-data counterpart to mcp_server/gmail_real.py --
main.py and bot.py pick between them via GMAIL_SOURCE in .env. Useful for
demos, tests, and development without touching a real inbox or needing
Gmail OAuth set up.

Only the data source is mocked (sample_emails.json instead of the live
Gmail API). The tool boundary is a real MCP server: it speaks the same
protocol gmail_real.py does, exposes the same one tool (list_emails), and
returns the same shape (id, from, subject, body, date), so every agent
downstream of the MCP client works identically against either one.
"""

import json
from pathlib import Path

from mcp.server.mcpserver import MCPServer

DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "sample_emails.json"

mcp = MCPServer("gmail-mock")


@mcp.tool()
def list_emails(query: str | None = None) -> list[dict]:
    """Return the inbox: a list of emails, each with id, from, subject, body, date.

    In a real Gmail MCP server this would call users.messages.list + .get
    against the Gmail API. Here it just reads the sample dataset.

    `query` matches gmail_real.py's tool signature (a Gmail search-syntax
    string) but is a no-op here -- the fixed sample set isn't filterable,
    so it's accepted and ignored to keep the mock/real tool interfaces
    identical for callers.
    """
    with open(DATA_PATH, encoding="utf-8") as f:
        return json.load(f)


if __name__ == "__main__":
    mcp.run(transport="stdio")
