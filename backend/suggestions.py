"""Shared quick-reply suggestion generator, used by both Sara and the
Mortgage Agent so the two don't drift into different quality bars. Grounds
suggestions in the actual conversation (both the customer's last message
and the assistant's reply) rather than the reply alone, and pushes hard
against generic filler - the earlier version tended to produce vague
options like "Tell me more" that don't reflect what was actually said."""

import json
import re

from . import config
from .llm_client import client

SUGGESTIONS_JSON_RE = re.compile(r"\[.*\]", re.DOTALL)

PROMPT_TEMPLATE = """You generate quick-reply suggestion chips for a chat UI.
Below is the customer's last message and the assistant's reply to it.
Suggest exactly 3 short follow-up messages (max 6 words each) the CUSTOMER
could tap to continue the conversation, written in the same language as the
reply, from the customer's point of view.

Ground every suggestion in something SPECIFIC the reply actually said - a
number, a named document, a specific option offered, a question it asked, a
case ID, a named choice. Never fall back to generic filler like "Tell me
more" or "What's next?" unless the reply truly gives nothing concrete to
react to.

If the reply explicitly offers the customer a choice between named options
(e.g. call vs. chat, which transaction, a numbered list of items), your 3
suggestions should mostly BE those exact choices, phrased as the customer
would tap them - not vague reactions to having been given a choice.

Customer's last message:
{last_user_message}

Assistant's reply:
{reply}

Return ONLY a JSON array of 3 strings, nothing else - no markdown, no
explanation.
"""


def generate_suggestions(last_user_message: str, reply: str) -> list[str]:
    prompt = PROMPT_TEMPLATE.format(
        last_user_message=(last_user_message or "").strip() or "(none - this is the first message)",
        reply=reply,
    )
    try:
        response = client.chat.completions.create(
            model=config.OPENROUTER_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.5,
            max_tokens=150,
        )
        content = response.choices[0].message.content or "[]"
        match = SUGGESTIONS_JSON_RE.search(content)
        data = json.loads(match.group(0) if match else content)
        return [str(item).strip() for item in data if str(item).strip()][:3]
    except Exception:
        return []
