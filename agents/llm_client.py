"""
Shared LLM client used by classifier_agent and extractor_agent.

Nebius AI Studio exposes an OpenAI-compatible chat completions API, so we
reuse the `openai` SDK and just point it at Nebius's base_url. This keeps
each agent's code focused on its prompt/parsing logic instead of HTTP details.
"""

import json
import os
from concurrent.futures import ThreadPoolExecutor

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

_client = OpenAI(
    api_key=os.environ["NEBIUS_API_KEY"],
    base_url=os.environ.get("NEBIUS_BASE_URL", "https://api.studio.nebius.ai/v1"),
)
_MODEL = os.environ.get("NEBIUS_MODEL", "meta-llama/Meta-Llama-3.1-70B-Instruct")

# Each agent stage calls ask_json() once per email, and those calls are
# independent of each other within a stage (classifying email A doesn't
# depend on email B). A thread pool parallelizes them -- these are
# I/O-bound network calls, so threads help despite the GIL. Capped modestly
# to avoid tripping Nebius's rate limits.
MAX_WORKERS = 5


def ask_json(system_prompt: str, user_prompt: str) -> dict:
    """Send a prompt to the LLM and parse its reply as a JSON object.

    Every agent in this pipeline wants a small structured answer (a label,
    or a few extracted fields), so this is the one place that talks to the
    network and enforces "the model must return valid JSON."
    """
    response = _client.chat.completions.create(
        model=_MODEL,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    return json.loads(content)


def run_concurrently(fn, items: list) -> list:
    """Run fn(item) for each item in items in parallel, preserving order."""
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, len(items))) as executor:
        return list(executor.map(fn, items))
