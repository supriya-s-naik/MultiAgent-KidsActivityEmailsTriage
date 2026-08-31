"""
classifier_agent: decides which inbound emails are kid-activity related.

This is the first stage of the pipeline. It looks at every email and
answers one yes/no question: is this about a kid's activity (school,
sports, camp, lessons, etc.)? Everything else (marketing, unrelated work
email) gets filtered out here so later stages only spend effort on emails
that matter.
"""

from agents.llm_client import ask_json, run_concurrently

SYSTEM_PROMPT = """You are an email triage assistant for a busy parent.
Given one email, decide if it is related to a child's activity: school
notices, sports/clubs/lessons, permission slips, payments tied to a kid's
activity, or messages from a teacher/coach/activity organizer about a
specific child.

Marketing, newsletters, unrelated work email, and general account
notifications (subscriptions, receipts for non-kid services) are NOT
activity emails, even if a kid could theoretically be affected.

Respond with a JSON object: {"is_activity": true or false}
"""


def classify(email: dict) -> bool:
    """Return True if `email` is judged to be kid-activity related."""
    user_prompt = (
        f"From: {email['from']}\n"
        f"Subject: {email['subject']}\n"
        f"Body: {email['body']}"
    )
    result = ask_json(SYSTEM_PROMPT, user_prompt)
    return bool(result.get("is_activity", False))


def classify_all(emails: list[dict]) -> dict[str, bool]:
    """Classify a batch of emails (in parallel), keyed by email id."""
    results = run_concurrently(classify, emails)
    return {email["id"]: result for email, result in zip(emails, results)}
