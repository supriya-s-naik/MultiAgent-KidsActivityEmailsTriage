"""
bot.py: Discord bot that runs the activity-email pipeline on demand.

Complements main.py, which does a single fetch-and-post run (meant to be
triggered on a schedule, e.g. via Windows Task Scheduler). This bot instead
stays connected and listens for a slash command, so you can ask for a check
whenever you want. It reuses main.py's fetch_emails()/build_digest() and
agents/notifier_agent.py's format_digest() rather than duplicating any of
the classify/extract/handoff logic -- the pipeline itself is unchanged,
this just adds a second way to trigger it.

Setup (see README.md for the full Discord Developer Portal steps):
  1. Create a Discord Application + Bot, copy its token into .env as
     DISCORD_BOT_TOKEN.
  2. Invite the bot to your server via OAuth2 URL Generator with the
     `bot` + `applications.commands` scopes and Send Messages permission.
  3. (Optional) set DISCORD_GUILD_ID in .env to your server's ID so the
     slash command appears instantly there, instead of waiting up to an
     hour for Discord's global command sync.

Run with:  python bot.py
Then in Discord, type /activity-check in a channel the bot can see.
"""

import asyncio
import os
from typing import Optional

import discord
from discord import app_commands
from dotenv import load_dotenv

from agents.notifier_agent import chunk_message
from main import build_digest, fetch_emails

load_dotenv()

DISCORD_BOT_TOKEN = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_GUILD_ID = os.environ.get("DISCORD_GUILD_ID")

client = discord.Client(intents=discord.Intents.default())
tree = app_commands.CommandTree(client)


@client.event
async def on_ready():
    if DISCORD_GUILD_ID:
        guild = discord.Object(id=int(DISCORD_GUILD_ID))
        tree.copy_global_to(guild=guild)
        await tree.sync(guild=guild)
    else:
        await tree.sync()
    print(f"Logged in as {client.user}. /activity-check is ready.")


def _build_gmail_query(
    days: Optional[int],
    since: Optional[str],
    until: Optional[str],
    sender: Optional[str],
    keyword: Optional[str],
) -> Optional[str]:
    """Turn the slash command's structured filter options into a Gmail search query.

    Each option maps directly to a Gmail search operator -- no LLM call
    needed, so this adds no latency before the pipeline starts. Returns
    None (meaning: fall back to the .env GMAIL_QUERY default) if no filters
    were given.
    """
    parts = []
    if days:
        parts.append(f"newer_than:{days}d")
    if since:
        parts.append(f"after:{since.replace('-', '/')}")
    if until:
        parts.append(f"before:{until.replace('-', '/')}")
    if sender:
        parts.append(f"from:{sender}")
    if keyword:
        parts.append(keyword)
    return " ".join(parts) if parts else None


@tree.command(name="activity-check", description="Check for new kid-activity emails and post a digest here")
@app_commands.describe(
    days="Look back this many days, e.g. 3 (overrides the default lookback window)",
    since="Only emails on/after this date, format YYYY-MM-DD",
    until="Only emails on/before this date, format YYYY-MM-DD",
    sender="Only emails from this address, e.g. coach.miller@northsideyouthsoccer.org",
    keyword="Only emails containing this word/phrase",
)
async def activity_check(
    interaction: discord.Interaction,
    days: Optional[int] = None,
    since: Optional[str] = None,
    until: Optional[str] = None,
    sender: Optional[str] = None,
    keyword: Optional[str] = None,
):
    # Fetching + running all three LLM agents takes a while (one blocking
    # HTTP call per email per agent), so defer the reply immediately or
    # Discord will time out the interaction (3s limit). build_digest() is
    # synchronous, so it must run in a worker thread -- calling it directly
    # would block the event loop and stall the gateway heartbeat, risking a
    # disconnect (this is exactly what happened before this fix).
    await interaction.response.defer(thinking=True)

    query = _build_gmail_query(days, since, until, sender, keyword)
    emails = await fetch_emails(query=query)
    digest = await asyncio.to_thread(build_digest, emails, False)

    chunks = chunk_message(digest, 2000)
    await interaction.followup.send(chunks[0])
    for chunk in chunks[1:]:
        await interaction.channel.send(chunk)


if __name__ == "__main__":
    client.run(DISCORD_BOT_TOKEN)
