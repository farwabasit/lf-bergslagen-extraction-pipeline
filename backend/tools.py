from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from .knowledge import LF_PAGES

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.8",
}
MAX_CHARS = 6000
MAX_LINKS = 6
TIMEOUT_SECONDS = 10
CACHE_DIR = Path(__file__).resolve().parent / "cache"

# Keywords that mark a link as worth surfacing to the agent (get-a-price /
# buy / contact-a-human actions), so it can give concrete next steps instead
# of vague ones. Split into text vs. href keywords because every href on
# this site contains "lansforsakringar.se", which itself contains "ring" -
# matching hrefs on a bare substring like that would let almost any link through.
USEFUL_TEXT_KEYWORDS = (
    "kontakt", "kundservice", "kundtj", "ring oss", "chatt",
    "pris", "köp", "teckna", "ansök", "ansok", "skadeanmal",
)
USEFUL_HREF_KEYWORDS = (
    "tel:", "mailto:", "/kundservice", "/kundtjanst", "/kontakt",
    "/skadeanmalan", "/kop/",
)
# Transactional links (call us, get a price, apply) matter more than generic
# footer nav ("Kundservice", "Bank & pension") that repeats on every page.
PRIORITY_HREF_PREFIXES = ("tel:", "mailto:")
PRIORITY_TEXT_KEYWORDS = ("pris", "köp", "teckna", "ansök", "ansok")
MAX_LINK_TEXT_CHARS = 60

# Overview page primes the "bolagskod" region cookie so pages that don't
# carry /bergslagen/ in their path (e.g. the shared customer-service page)
# still resolve to LF Bergslagen content instead of a random default region.
_PRIMING_URL = LF_PAGES["overview"]

_session = requests.Session()
_session.headers.update(BROWSER_HEADERS)
_primed = False


def _ensure_primed() -> None:
    global _primed
    if _primed:
        return
    try:
        _session.get(_PRIMING_URL, timeout=TIMEOUT_SECONDS)
    except requests.RequestException:
        pass
    _primed = True


def _cache_path(topic: str) -> Path:
    return CACHE_DIR / f"{topic}.txt"


def _read_cache(topic: str) -> str | None:
    path = _cache_path(topic)
    return path.read_text(encoding="utf-8") if path.exists() else None


def _write_cache(topic: str, text: str) -> None:
    CACHE_DIR.mkdir(exist_ok=True)
    _cache_path(topic).write_text(text, encoding="utf-8")


def _looks_blocked(html: str) -> bool:
    # LF's WAF serves a tiny "Stopp!" interstitial instead of the real page
    # when a request looks bot-like. Treat that as a failed fetch.
    return len(html) < 2000 or "support-ID" in html or ">Stopp!<" in html


def _link_priority(text_lower: str, href_lower: str) -> int:
    if href_lower.startswith(PRIORITY_HREF_PREFIXES):
        return 0
    if any(kw in text_lower for kw in PRIORITY_TEXT_KEYWORDS):
        return 0
    return 1


def _extract_links(soup: BeautifulSoup, page_url: str) -> list[tuple[str, str]]:
    seen: set[str] = set()
    candidates: list[tuple[int, str, str]] = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        text = " ".join(a.get_text(separator=" ").split())
        if not text or href.lower().startswith("mailto:?"):
            continue  # "share this page by email" links, not a real contact address
        absolute = urljoin(page_url, href)
        text_lower, href_lower = text.lower(), href.lower()
        matches = any(kw in text_lower for kw in USEFUL_TEXT_KEYWORDS) or any(
            kw in href_lower for kw in USEFUL_HREF_KEYWORDS
        )
        if not matches:
            continue
        if absolute == page_url or absolute in seen:
            continue
        seen.add(absolute)
        if len(text) > MAX_LINK_TEXT_CHARS:
            text = text[: MAX_LINK_TEXT_CHARS - 1].rstrip() + "…"
        candidates.append((_link_priority(text_lower, href_lower), text, absolute))

    candidates.sort(key=lambda c: c[0])
    return [(text, url) for _, text, url in candidates[:MAX_LINKS]]


def _extract_text(soup: BeautifulSoup) -> str:
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return " ".join(soup.get_text(separator=" ").split())[:MAX_CHARS]


def _format_result(text: str, links: list[tuple[str, str]]) -> str:
    if not links:
        return text
    link_lines = "\n".join(f"- {label}: {url}" for label, url in links)
    return f"{text}\n\nUseful links on this page:\n{link_lines}"


def fetch_lf_page(topic: str) -> str:
    url = LF_PAGES.get(topic)
    if not url:
        return f"Unknown topic '{topic}'. Valid topics: {', '.join(LF_PAGES)}"

    _ensure_primed()

    try:
        response = _session.get(url, timeout=TIMEOUT_SECONDS)
        response.raise_for_status()
        response.encoding = response.apparent_encoding
        if _looks_blocked(response.text):
            raise requests.RequestException("blocked by anti-bot page")

        soup = BeautifulSoup(response.text, "html.parser")
        links = _extract_links(soup, response.url)
        text = _extract_text(soup)
        result = _format_result(text, links)
    except requests.RequestException:
        cached = _read_cache(topic)
        if cached:
            return f"[Live fetch failed, using last saved copy of this page]\n{cached}"
        return (
            f"Could not fetch {url} right now, and no cached copy is available. "
            "Answer from general knowledge and suggest the user check the page directly."
        )

    _write_cache(topic, result)
    return result
