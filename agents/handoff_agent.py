"""
handoff_agent: decides which activity emails need the parent's direct action.

Not every activity email requires anything from the parent -- a schedule
change you just need to know about is different from a permission slip
you must sign or a party you must RSVP to. This agent looks at the
extracted details alongside the original email and flags only the emails
where the parent must actually do something: RSVP, pay, sign, or reply.
"""

from agents.llm_client import ask_json, run_concurrently

SYSTEM_PROMPT = """You decide whether a parent must take direct action on
an email about their child's activity.

needs_action = true ONLY if the parent must do one of:
- RSVP or sign up for something
- make a payment
- sign/return a form
- reply to a specific question

needs_action = false if the email is purely informational (a schedule
change to be aware of, a cancellation with no action required, a
congratulatory note, an FYI), even if it mentions a date or event.

Respond with a JSON object: {"needs_action": true or false}
"""


def decide(email: dict, extracted: dict) -> bool:
    """Return True if `email` requires the parent to RSVP, pay, sign, or reply."""
    user_prompt = (
        f"Subject: {email['subject']}\n"
        f"Body: {email['body']}\n\n"
        f"Extracted action_needed field: {extracted.get('action_needed')}\n"
        f"Extracted deadline field: {extracted.get('deadline')}"
    )
    result = ask_json(SYSTEM_PROMPT, user_prompt)
    return bool(result.get("needs_action", False))


def decide_all(emails: list[dict], extracted_by_id: dict[str, dict]) -> dict[str, bool]:
    """Decide needs_action for a batch of (already-extracted) emails (in parallel), keyed by id."""
    results = run_concurrently(lambda e: decide(e, extracted_by_id[e["id"]]), emails)
    return {email["id"]: result for email, result in zip(emails, results)}
