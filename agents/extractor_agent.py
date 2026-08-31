"""
extractor_agent: pulls structured details out of activity emails.

Runs only on emails classifier_agent already flagged as is_activity=True.
Turns a free-text email into the four fields a parent actually needs to
scan quickly: what is this about, when does it happen, is there a
deadline, and is there something the parent must do.
"""

from agents.llm_client import ask_json, run_concurrently

SYSTEM_PROMPT = """You are extracting key details from a parent's
kid-activity email so they can be summarized in a digest.

Read the email and return a JSON object with exactly these fields:
{
  "what": "short phrase describing the event/topic",
  "when": "date/time mentioned, or null if none",
  "deadline": "any deadline mentioned (form due, payment due, RSVP by), or null if none",
  "action_needed": "short phrase describing what the parent must do, or null if nothing is required"
}

Be concise. Use the email's own wording for dates where possible.
"""


def extract(email: dict) -> dict:
    """Return the extracted {what, when, deadline, action_needed} for one email."""
    user_prompt = (
        f"From: {email['from']}\n"
        f"Subject: {email['subject']}\n"
        f"Body: {email['body']}"
    )
    return ask_json(SYSTEM_PROMPT, user_prompt)


def extract_all(emails: list[dict]) -> dict[str, dict]:
    """Extract details for a batch of (already-classified activity) emails (in parallel), keyed by id."""
    results = run_concurrently(extract, emails)
    return {email["id"]: result for email, result in zip(emails, results)}
