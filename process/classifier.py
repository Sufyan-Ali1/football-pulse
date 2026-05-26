"""
Content classifier — Step 3.

Classifies a NewsItem into one of four content types:
  breaking_news   → confirmed events (signings, sackings, contracts)
  transfer_rumour → unconfirmed links, bids, negotiations
  club_update     → injuries, squad news, club statements
  tactical        → match results, reports, tactical breakdowns

Strategy:
  1. Keyword matching (free, instant) — handles ~60% of items
  2. Groq batch API (up to 10 headlines per call) — handles the rest
     This is ~10x cheaper than calling Groq once per item.
"""
import json
import logging

from openai import OpenAI

from config import settings
from core.constants import BREAKING_SIGNALS, TRANSFER_SIGNALS, TACTICAL_SIGNALS
from core.types import ContentType, NewsItem

logger = logging.getLogger(__name__)

_groq = OpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

_VALID: list[ContentType] = ["breaking_news", "transfer_rumour", "club_update", "tactical"]


# ── Keyword classifier (no API cost) ─────────────────────────────────────────

def _keyword_classify(text: str) -> ContentType | None:
    t = text.lower()
    if any(s in t for s in BREAKING_SIGNALS):
        return "breaking_news"
    if any(s in t for s in TRANSFER_SIGNALS):
        return "transfer_rumour"
    if any(s in t for s in TACTICAL_SIGNALS):
        return "tactical"
    return None


# ── Single-item Groq fallback ─────────────────────────────────────────────────

_SINGLE_PROMPT = """Classify this football news headline into EXACTLY one category:

- breaking_news   → ONLY for confirmed/completed events: a transfer signing completed, a manager officially sacked or appointed, a contract extension signed. A match result is NEVER breaking_news.
- transfer_rumour → Unconfirmed: transfer links, rumours, interest, bids, negotiations, player "linked to" a club
- tactical        → Match results (including cup finals and major finals), match reports, post-match reaction or analysis, formations, tactical breakdowns, player ratings
- club_update     → Injuries, suspensions, squad news, kit releases, merchandise, press conferences, club statements

Key rule: if in doubt between breaking_news and any other category, choose the other category.

Headline: {headline}

Respond with ONLY the category name."""


def classify(item: NewsItem) -> ContentType:
    """Classify a single item. Use batch_classify() for multiple items."""
    text = item.headline + " " + item.body[:300]
    result = _keyword_classify(text)
    if result:
        logger.debug("Keyword classified '%s' as %s", item.headline[:60], result)
        return result

    try:
        response = _groq.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": _SINGLE_PROMPT.format(headline=item.headline)}],
            max_tokens=10,
            temperature=0,
        )
        cat = response.choices[0].message.content.strip().lower()
        if cat in _VALID:
            logger.debug("Groq classified '%s' as %s", item.headline[:60], cat)
            return cat  # type: ignore[return-value]
    except Exception as e:
        logger.warning("Groq single classify failed: %s", e)

    return "club_update"


# ── Batch Groq classifier (10 headlines per API call) ────────────────────────

_BATCH_PROMPT = """Classify each football news headline into exactly one category:

- breaking_news   → ONLY for confirmed/completed events: transfer signing completed, manager officially sacked or appointed, contract extension confirmed. A match result is NEVER breaking_news, even if it is a final or a championship win.
- transfer_rumour → Unconfirmed: transfer links, rumours, bids, interest, negotiations, player "linked to" a club, speculation
- tactical        → Match results, match reports, post-match reaction or analysis, team performance, formations, tactical breakdowns, player ratings, cup finals, tournament results
- club_update     → Injuries, suspensions, squad announcements, kit releases, merchandise, press conferences, club statements, general club news

Rules:
- "Confirmed" in a match or analysis context does NOT make it breaking_news
- Kit releases, merchandise, or commercial partnerships are always club_update
- Women's football results and analysis are tactical, not breaking_news
- If unsure between breaking_news and anything else, choose the other category

Headlines:
{lines}

Respond with ONLY a JSON object mapping number to category.
Example: {{"1": "breaking_news", "2": "transfer_rumour"}}
No explanation. No other text."""


def _groq_batch(indexed: list[tuple[int, NewsItem]]) -> dict[str, ContentType]:
    lines  = "\n".join(f"{i}. {item.headline}" for i, item in indexed)
    prompt = _BATCH_PROMPT.format(lines=lines)
    result: dict[str, ContentType] = {}

    try:
        response = _groq.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
            temperature=0,
        )
        parsed: dict = json.loads(response.choices[0].message.content.strip())
        for idx_str, category in parsed.items():
            cat = category.lower().strip()
            for orig_idx, item in indexed:
                if orig_idx == int(idx_str):
                    result[item.id] = cat if cat in _VALID else "club_update"  # type: ignore[assignment]
                    break
    except Exception as e:
        logger.warning("Groq batch classify failed: %s — defaulting to club_update", e)
        for _, item in indexed:
            result[item.id] = "club_update"

    return result


def batch_classify(items: list[NewsItem]) -> dict[str, tuple[ContentType, str]]:
    """
    Classify a list of items efficiently.
    Returns {news_id: (ContentType, classified_by)} for every item.
      classified_by is 'keyword' (free, instant) or 'groq_batch' (Groq API).

    - Keyword matching runs first (free, instant)
    - Remaining items are sent to Groq in batches of 10
    """
    if not items:
        return {}

    result: dict[str, tuple[ContentType, str]] = {}
    needs_groq: list[tuple[int, NewsItem]] = []

    for i, item in enumerate(items, start=1):
        kw = _keyword_classify(item.headline + " " + item.body[:300])
        if kw:
            result[item.id] = (kw, "keyword")
        else:
            needs_groq.append((i, item))

    for start in range(0, len(needs_groq), 10):
        batch = needs_groq[start:start + 10]
        groq_result = _groq_batch(batch)
        for news_id, content_type in groq_result.items():
            result[news_id] = (content_type, "groq_batch")

    groq_calls = (len(needs_groq) + 9) // 10 if needs_groq else 0
    logger.info(
        "batch_classify: %d items - %d keyword, %d Groq (%d call(s))",
        len(items), len(items) - len(needs_groq), len(needs_groq), groq_calls,
    )
    return result

