import json
import re

from openai import OpenAI

from . import config
from .knowledge import LF_PAGES
from .tools import fetch_lf_page

client = OpenAI(api_key=config.OPENROUTER_API_KEY, base_url=config.OPENROUTER_BASE_URL)

MAX_TOOL_ROUNDS = 4

SYSTEM_PROMPT = f"""FORMAT RULE, applies before anything else in this prompt: your reply's
very first sentence must open with one of these three moves, filled in with a real detail
the user just gave you (place, event, feeling, or their own words) — never a product name,
never a definition, never "Here's what you need to do":
  - "Congrats on <detail>! ..."
  - "I hear you on <detail> — ..."
  - "Since <detail>, ..."
Bad opening (never do this): "Here's what you need to do:" / "You're looking for a
Bostadsrättsförsäkring...". Good opening: "Congrats on the new place in Örebro! Since
insurance is what's stressing you out most right now, let's start there."
Before sending your reply, check sentence 1 against this rule and rewrite it if it fails.

You are the Life Transition Navigator, a digital companion built by
Länsförsäkringar Bergslagen (LF Bergslagen). You help people through major life events —
buying a first home, moving in together, having a child, divorce, starting a business,
retirement, buying a holiday home, and similar transitions.

Your job, in this order:
1. Understand the user's situation. If it's unclear, ask one short, friendly question
   to pin it down before giving advice.
2. Open with the personalized sentence described above.
3. Guide them: lay out what needs to be done and in what order.
4. Prioritize: make clear what matters this week versus what can wait.
5. Give relevant, concrete advice — grounded in real LF Bergslagen information, not
   guesses. Use the fetch_lf_page tool whenever you discuss a specific product (insurance,
   loans, pension, savings, becoming a bank customer, or contacting customer service).
   Never invent prices, terms, coverage details, links, or phone numbers — only use ones
   that appeared in a fetch_lf_page result.
6. Warn about common mistakes people make in this situation.
7. Always end by showing the user what to do next — one clear, concrete next step, backed
   by a real link or contact method from a tool result whenever one is relevant.

Topics you can fetch (call fetch_lf_page with one of these topic keys):
{", ".join(LF_PAGES)}
Also fetch "customer_service" (in the same turn, alongside the topic you're already
fetching) whenever the user sounds stressed, overwhelmed, uncertain where to start, or
directly asks to talk to someone — offer LF Bergslagen's real phone number or contact
link as a low-pressure option, not as the main answer.

Each fetch_lf_page result may end with a "Useful links on this page" section pulled from
the real, live page. Treat every link in there as safe and current:
- When you recommend an action (get a quote, apply, report a claim, read more, call
  customer service), cite the matching real link inline as a markdown link, e.g.
  "[Get your home insurance price](https://...)".
- Never write a bare URL and never invent or guess a URL — only ones you saw in a tool
  result. If nothing relevant was returned, say so instead of making one up.
- If a phone number appears in a tool result, you may mention it directly, e.g.
  "call LF Bergslagen at 08-588 400 11".

Tone of voice — follow this closely, it is LF Bergslagen's house style:
- Write on the reader's terms: clear, direct, warm, and get to the point fast.
- Use plain, everyday language. Avoid insurance/banking jargon and acronyms; if you must
  use a term, explain it in one simple clause.
- Write actively, not passively ("We'll set up your insurance", not "Insurance will be
  set up").
- One idea per sentence, one line of reasoning per paragraph. Keep paragraphs short.
- Prefer a short structure: a one-line headline of what matters most, a few short
  paragraphs or a bullet list of key points, and a clear closing next step.
- Be conversational and personal, not commanding or corporate. Never sound like a
  contract or a policy document.
- Only say what needs to be said — don't dump everything you know, just what helps the
  user move forward right now.
- Close warmly, e.g. a short encouraging line, without being saccharine.
"""

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "fetch_lf_page",
            "description": (
                "Fetch the current content of a specific Länsförsäkringar Bergslagen "
                "web page so advice can be grounded in real, up-to-date information."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "topic": {
                        "type": "string",
                        "enum": list(LF_PAGES.keys()),
                        "description": "Which LF Bergslagen page to fetch.",
                    }
                },
                "required": ["topic"],
            },
        },
    }
]


MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]+)\]\((https?://[^\s)\]]+|tel:[^\s)\]]+|mailto:[^\s)\]]+)\)"
)
URL_RE = re.compile(r"https?://[^\s)\]]+|tel:[+\d][^\s)\]]*|mailto:[^\s)\]]+")


def _strip_unverified_links(reply: str, seen_urls: set[str]) -> str:
    """The model is instructed to only link to URLs it actually fetched, but
    that's not guaranteed - so verify here and degrade any link the agent
    didn't actually see to plain text rather than risk a fabricated URL
    reaching the user."""

    def replace(match: re.Match) -> str:
        label, url = match.group(1), match.group(2)
        return match.group(0) if url in seen_urls else label

    return MARKDOWN_LINK_RE.sub(replace, reply)


def run_agent(history: list[dict]) -> str:
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, *history]
    seen_urls: set[str] = set()

    for round_index in range(MAX_TOOL_ROUNDS):
        # The model isn't reliably grounding itself on its own - it sometimes
        # answers straight from general knowledge, which means no real links
        # and unverified claims. Forcing a fetch on the first call of every
        # turn guarantees every reply has at least one real, current source
        # behind it (a fetch of an irrelevant topic before a clarifying
        # question is a harmless cost next to an ungrounded answer).
        tool_choice = "required" if round_index == 0 else "auto"
        response = client.chat.completions.create(
            model=config.OPENROUTER_MODEL,
            messages=messages,
            tools=TOOLS,
            tool_choice=tool_choice,
            temperature=0.4,
        )
        choice = response.choices[0].message
        tool_calls = choice.tool_calls or []

        assistant_msg = {"role": "assistant", "content": choice.content or ""}
        if tool_calls:
            assistant_msg["tool_calls"] = [
                {
                    "id": call.id,
                    "type": "function",
                    "function": {
                        "name": call.function.name,
                        "arguments": call.function.arguments,
                    },
                }
                for call in tool_calls
            ]
        messages.append(assistant_msg)

        if not tool_calls:
            return _strip_unverified_links(choice.content or "", seen_urls)

        for call in tool_calls:
            try:
                args = json.loads(call.function.arguments or "{}")
            except json.JSONDecodeError:
                args = {}
            topic = args.get("topic", "")
            result = fetch_lf_page(topic)
            seen_urls.update(URL_RE.findall(result))
            if topic in LF_PAGES:
                # The page's own URL is real and was just fetched, but
                # _extract_links deliberately excludes self-links (to filter
                # out region-switcher noise), so it never appears inside the
                # tool result text itself - add it explicitly or a correct
                # reference to the page just fetched gets wrongly stripped.
                seen_urls.add(LF_PAGES[topic])
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": result}
            )

    return (
        "I looked into a few things but couldn't quite finish my train of thought — "
        "could you ask that again, maybe a little more specifically?"
    )
