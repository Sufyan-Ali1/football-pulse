"""
Content classifier — Step 3.

Classifies a NewsItem into one of the following content types:
  deal_done          → confirmed signings, "here we go", medicals, unveiled
  transfer_rumour    → unconfirmed links, bids, interest, negotiations
  breaking_news      → general confirmed breaking football event
  manager_sacked     → manager sacked/dismissed/parted ways
  manager_appointed  → manager appointed/named/takes charge
  contract_extension → contract extensions / renewals
  injury_fitness     → injuries, fitness updates, returns
  club_statement     → official club statements / announcements
  tactical           → match results, reports, analysis, formations

Strategy:
  1. Rule-based keyword pass (free, instant) — handles ~70% of items
  2. Groq batch API (up to 10 headlines per call) — handles the rest
"""
import json
import logging

from clients.groq_client import get_groq_client
from config import settings
from core.constants import (
    BREAKING_SIGNALS,
    CLUB_STATEMENT_SIGNALS,
    CONTRACT_EXTENSION_SIGNALS,
    DEAL_DONE_SIGNALS,
    INJURY_FITNESS_SIGNALS,
    MANAGER_APPOINTED_SIGNALS,
    MANAGER_SACKED_SIGNALS,
    TACTICAL_SIGNALS,
    TRANSFER_SIGNALS,
    VALID_CONTENT_TYPES,
)
from core.types import ContentType, NewsItem

logger = logging.getLogger(__name__)

_groq = get_groq_client()

_VALID = VALID_CONTENT_TYPES


# ── Keyword classifier (no API cost) ─────────────────────────────────────────

def _keyword_classify(text: str) -> ContentType | None:
    t = text.lower()
    # Most specific types first to avoid false matches
    if any(s in t for s in DEAL_DONE_SIGNALS):
        return "deal_done"
    if any(s in t for s in MANAGER_SACKED_SIGNALS):
        return "manager_sacked"
    if any(s in t for s in MANAGER_APPOINTED_SIGNALS):
        return "manager_appointed"
    if any(s in t for s in CONTRACT_EXTENSION_SIGNALS):
        return "contract_extension"
    if any(s in t for s in INJURY_FITNESS_SIGNALS):
        return "injury_fitness"
    if any(s in t for s in CLUB_STATEMENT_SIGNALS):
        return "club_statement"
    if any(s in t for s in BREAKING_SIGNALS):
        return "breaking_news"
    if any(s in t for s in TRANSFER_SIGNALS):
        return "transfer_rumour"
    if any(s in t for s in TACTICAL_SIGNALS):
        return "tactical"
    return None


# ── Single-item Groq fallback ─────────────────────────────────────────────────

_SINGLE_PROMPT = """You are classifying football news headlines for a football YouTube channel.

IMPORTANT: Only classify genuine football news. If the headline is NOT about football, respond with "tactical" as a safe default — it will be filtered later by relevance scoring.

Categories:
- deal_done          → confirmed/completed transfer signing, "here we go", medicals done, player unveiled
- transfer_rumour    → unconfirmed: transfer links, bids, interest, negotiations, player "linked to" a club
- breaking_news      → confirmed breaking football event that doesn't fit other categories
- manager_sacked     → manager dismissed, sacked, parted ways, relieved of duties
- manager_appointed  → manager appointed, named, takes charge
- contract_extension → player or manager signs contract extension or renewal
- injury_fitness     → injury news, fitness updates, returns from injury, ruled out
- club_statement     → official club announcement, statement, or confirmation
- tactical           → match results, match reports, analysis, formations, post-match reaction

Key rules:
- A match result or cup final is NEVER deal_done or breaking_news — it is tactical
- "Confirmed" in a match or analysis context is NOT deal_done
- Kit releases, merchandise, commercial deals are club_statement
- If unsure between deal_done and any other category, choose the other category

Headline: {headline}

Respond with ONLY the category name. No explanation."""


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

    return "tactical"


# ── Batch Groq classifier (10 headlines per API call) ────────────────────────

_BATCH_PROMPT = """You are classifying football news headlines for a football YouTube channel.

IMPORTANT: Only classify genuine football news. If a headline is NOT about football, classify it as "tactical" — it will be filtered by relevance scoring later.

Categories:
- deal_done          → confirmed/completed transfer signing, "here we go", medicals done, player unveiled at new club
- transfer_rumour    → unconfirmed: transfer links, bids, interest, negotiations, player "linked to" a club, speculation
- breaking_news      → confirmed breaking football event that doesn't fit other specific categories
- manager_sacked     → manager dismissed, sacked, parted ways, relieved of duties
- manager_appointed  → manager appointed, named as head coach, takes charge
- contract_extension → player or manager signs contract extension or renewal
- injury_fitness     → injury news, fitness updates, player ruled out, returns from injury
- club_statement     → official club announcement, statement, or press release
- tactical           → match results, match reports, analysis, formations, post-match reaction, player ratings

Key rules:
- Match results and cup finals are ALWAYS tactical, never deal_done or breaking_news
- Kit releases, merchandise, commercial deals are club_statement
- Women's football results are tactical
- If unsure between deal_done and anything else, choose the other category

Headlines:
{lines}

Respond with ONLY a JSON object mapping number to category.
Example: {{"1": "deal_done", "2": "transfer_rumour", "3": "tactical"}}
No explanation. No other text."""


def _groq_batch(indexed: list[tuple[int, NewsItem]]) -> dict[str, ContentType]:
    lines  = "\n".join(f"{i}. {item.headline}" for i, item in indexed)
    prompt = _BATCH_PROMPT.format(lines=lines)
    result: dict[str, ContentType] = {}

    try:
        response = _groq.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=150,
            temperature=0,
        )
        parsed: dict = json.loads(response.choices[0].message.content.strip())
        for idx_str, category in parsed.items():
            cat = category.lower().strip()
            for orig_idx, item in indexed:
                if orig_idx == int(idx_str):
                    result[item.id] = cat if cat in _VALID else "tactical"  # type: ignore[assignment]
                    break
    except Exception as e:
        logger.warning("Groq batch classify failed: %s — defaulting to tactical", e)
        for _, item in indexed:
            result[item.id] = "tactical"

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
        "batch_classify: %d items — %d keyword, %d Groq (%d call(s))",
        len(items), len(items) - len(needs_groq), len(needs_groq), groq_calls,
    )
    return result
