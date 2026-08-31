"""
notifier_agent: formats the digest and posts it to Discord.

Last stage of the pipeline. Takes the per-email results from the other
three agents and turns them into one readable message. `format_digest` is
shared by both delivery paths: post_to_discord() below pushes it to a
fixed webhook channel (used by main.py's scheduled/manual run), while
bot.py sends the same text back through a slash-command reply instead.
"""

import os

import requests
from dotenv import load_dotenv

load_dotenv()

DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL", "")


def format_digest(emails: list[dict], extracted_by_id: dict[str, dict], needs_action_by_id: dict[str, bool]) -> str:
    """Build a Discord message summarizing the activity emails.

    `emails` should already be filtered down to is_activity=True emails.
    Action-needed items are called out first so they're impossible to miss.
    """
    action_items = [e for e in emails if needs_action_by_id.get(e["id"])]
    fyi_items = [e for e in emails if not needs_action_by_id.get(e["id"])]

    lines = [f"**📬 Kid Activity Digest — {len(emails)} email(s)**", ""]

    if action_items:
        lines.append("**⚠️ Needs your action:**")
        for email in action_items:
            info = extracted_by_id[email["id"]]
            lines.append(_format_item(email, info))
        lines.append("")

    if fyi_items:
        lines.append("**ℹ️ FYI only:**")
        for email in fyi_items:
            info = extracted_by_id[email["id"]]
            lines.append(_format_item(email, info))

    return "\n".join(lines)


def _format_item(email: dict, info: dict) -> str:
    what = info.get("what") or email["subject"]
    when = info.get("when")
    deadline = info.get("deadline")
    action = info.get("action_needed")

    parts = [f"- **{what}** (from {email['from']})"]
    if when:
        parts.append(f"  when: {when}")
    if deadline:
        parts.append(f"  deadline: {deadline}")
    if action:
        parts.append(f"  action: {action}")
    return "\n".join(parts)


def post_to_discord(message: str) -> None:
    """POST the digest text to the configured Discord webhook."""
    if not DISCORD_WEBHOOK_URL:
        raise RuntimeError(
            "DISCORD_WEBHOOK_URL is not set. Add it to .env (see .env.example)."
        )

    # Discord caps a single message at 2000 characters; split into chunks if needed.
    for chunk in chunk_message(message, 2000):
        response = requests.post(DISCORD_WEBHOOK_URL, json={"content": chunk}, timeout=10)
        response.raise_for_status()


def chunk_message(message: str, limit: int) -> list[str]:
    lines = message.split("\n")
    chunks, current = [], ""
    for line in lines:
        if len(current) + len(line) + 1 > limit:
            chunks.append(current)
            current = line
        else:
            current = f"{current}\n{line}" if current else line
    if current:
        chunks.append(current)
    return chunks
