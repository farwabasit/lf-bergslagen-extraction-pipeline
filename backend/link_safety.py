"""Shared link-verification helpers, used by every agent that's allowed to
cite a fetch_lf_page result inline (Sara and the Mortgage Agent). Split out
so both agents apply the exact same discipline: an agent may only cite a
URL it actually saw in a tool result - anything else gets degraded rather
than risk a fabricated link reaching the user.

Handles both markdown links ([label](url)) and bare URLs written directly
in the text - a bare unverified URL used to slip through untouched (the
model is instructed not to write one, but that's not guaranteed), so both
forms go through the same single pass here."""

import re

MARKDOWN_LINK_RE = re.compile(
    r"\[([^\]]+)\]\((https?://[^\s)\]]+|tel:[^\s)\]]+|mailto:[^\s)\]]+)\)"
)
URL_RE = re.compile(r"https?://[^\s)\]]+|tel:[+\d][^\s)\]]*|mailto:[^\s)\]]+")

# One combined pattern, scanned left-to-right, so a URL is only ever visited
# once: either as part of a markdown link (group 1/2) or as a bare URL
# (group 3) - never both, which is what made a two-pass approach fiddly
# (a second bare-URL pass would also match the URL sitting inside an
# already-verified markdown link).
_COMBINED_RE = re.compile(
    r"\[([^\]]+)\]\((https?://[^\s)\]]+|tel:[^\s)\]]+|mailto:[^\s)\]]+)\)"
    r"|(https?://[^\s)\]]+|tel:[+\d][^\s)\]]*|mailto:[^\s)\]]+)"
)


def strip_unverified_links(reply: str, seen_urls: set[str]) -> str:
    def replace(match: re.Match) -> str:
        if match.group(1) is not None:
            label, url = match.group(1), match.group(2)
            return match.group(0) if url in seen_urls else label
        bare_url = match.group(3)
        return bare_url if bare_url in seen_urls else ""

    return _COMBINED_RE.sub(replace, reply)
