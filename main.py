"""
main.py: orchestrates the full pipeline.

    MCP client -> classifier_agent -> extractor_agent -> handoff_agent -> notifier_agent

Run with:  python main.py

Each stage is a separate agent module under agents/ so it can be explained
and tested independently. This file just wires them together in order and
prints progress so the run is easy to follow.
"""

import asyncio
import os
import sys
from pathlib import Path

# Windows terminals default to a codepage that can't print the digest's
# emoji; force UTF-8 so `print(digest)` below doesn't crash.
sys.stdout.reconfigure(encoding="utf-8")

from dotenv import load_dotenv
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from agents import classifier_agent, extractor_agent, handoff_agent, notifier_agent

load_dotenv()

# GMAIL_SOURCE=mock (default) uses the sample-data MCP server, good for demos
# and development; GMAIL_SOURCE=real uses the live Gmail MCP server, which
# needs mcp_server/token.json (see mcp_server/gmail_auth_setup.py) already in place.
GMAIL_SOURCE = os.environ.get("GMAIL_SOURCE", "mock")
_SERVER_FILENAME = "gmail_real.py" if GMAIL_SOURCE == "real" else "gmail_mock.py"
MCP_SERVER_SCRIPT = str(Path(__file__).resolve().parent / "mcp_server" / _SERVER_FILENAME)


async def fetch_emails(query: str | None = None) -> list[dict]:
    """Fetch the inbox from the Gmail MCP server (mock or real, per GMAIL_SOURCE) via a real MCP client session.

    `query` (Gmail search syntax) overrides the .env GMAIL_QUERY default for
    this one call, e.g. filters built by bot.py's slash command options.
    """
    params = StdioServerParameters(command=sys.executable, args=[MCP_SERVER_SCRIPT])
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            arguments = {"query": query} if query else {}
            result = await session.call_tool("list_emails", arguments)
            return result.structured_content["result"]


def build_digest(emails: list[dict], verbose: bool = True) -> str:
    """Run classifier -> extractor -> handoff and return the formatted digest text.

    Shared by the CLI entry point below and bot.py's slash command, so the
    pipeline logic lives in exactly one place.
    """
    log = print if verbose else (lambda *a, **k: None)
    log(f"Fetched {len(emails)} emails from MCP server (source: {GMAIL_SOURCE}).\n")

    # Stage 1: classify
    log("Running classifier_agent...")
    is_activity_by_id = classifier_agent.classify_all(emails)
    activity_emails = [e for e in emails if is_activity_by_id[e["id"]]]
    log(f"  -> {len(activity_emails)}/{len(emails)} emails flagged as activity-related.\n")

    # Stage 2: extract details (activity emails only)
    log("Running extractor_agent...")
    extracted_by_id = extractor_agent.extract_all(activity_emails)
    log(f"  -> extracted details for {len(extracted_by_id)} emails.\n")

    # Stage 3: flag which ones need the parent's direct action
    log("Running handoff_agent...")
    needs_action_by_id = handoff_agent.decide_all(activity_emails, extracted_by_id)
    action_count = sum(needs_action_by_id.values())
    log(f"  -> {action_count}/{len(activity_emails)} emails need direct action.\n")

    # Stage 4: format digest (posting is left to the caller)
    log("Running notifier_agent (format only)...")
    return notifier_agent.format_digest(activity_emails, extracted_by_id, needs_action_by_id)


def main() -> None:
    emails = asyncio.run(fetch_emails())
    digest = build_digest(emails)
    print("\n--- Digest preview ---")
    print(digest)
    print("--- end preview ---\n")

    notifier_agent.post_to_discord(digest)
    print("Posted digest to Discord.")


if __name__ == "__main__":
    main()
