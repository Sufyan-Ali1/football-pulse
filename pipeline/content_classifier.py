"""
Classifies a NewsItem into a content type that maps to the correct script format
and pipeline path.

Content types:
  breaking_news   → 60-second script  (urgent, just-confirmed news)
  transfer_rumour → 2-3 min analysis  (unconfirmed transfers, rumours)
  club_update     → 2-3 min analysis  (club-specific news, injuries, managerial)
  tactical        → 2-3 min analysis  (match reports, tactical breakdowns)
  short_form      → always generated alongside whichever main type is chosen

Optimisation: batch_classify() groups up to 10 headlines per Groq call,
reducing API usage by ~10x compared to classify() called per item.
"""
import json
import logging
import re
from typing import Literal

from openai import OpenAI

from config import settings
from modules.news_monitor import NewsItem

# Groq is OpenAI-compatible — same client, different base URL and model
_groq_client = OpenAI(
    api_key=settings.GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)

logger = logging.getLogger(__name__)

ContentType = Literal["breaking_news", "transfer_rumour", "club_update", "tactical"]

# ── Keyword-based fast classifier (no API cost) ───────────────────────────────

_BREAKING_SIGNALS = [
    "here we go", "confirmed", "done deal", "official", "breaking",
    "agreement reached", "deal signed", "medicals", "contract signed",
    "announced", "unveiled", "sacked", "appointed",
]

_TRANSFER_SIGNALS = [
    "transfer", "signing", "loan", "bid", "fee", "move", "linked",
    "interest", "talks", "negotiations", "wanted", "target",
    "deal", "offer", "approach", "bid rejected", "clause",
]

_TACTICAL_SIGNALS = [
    "match report", "tactical", "formation", "press conference",
    "lineup", "starting eleven", "substitution", "tactics",
    "analysis", "performance", "rating",
]


def _keyword_classify(text: str) -> ContentType | None:
    t = text.lower()
    if any(sig in t for sig in _BREAKING_SIGNALS):
        return "breaking_news"
    if any(sig in t for sig in _TRANSFER_SIGNALS):
        return "transfer_rumour"
    if any(sig in t for sig in _TACTICAL_SIGNALS):
        return "tactical"
    return None


# ── Groq fallback classifier (used when keywords are inconclusive) ────────────

_CLASSIFY_PROMPT = """Classify the following football news headline into EXACTLY one of these categories:
- breaking_news   (confirmed, official, just-announced news)
- transfer_rumour (unconfirmed transfers, links, rumours, negotiations)
- club_update     (injuries, suspensions, managerial changes, club announcements)
- tactical        (match reports, formations, tactical analysis)

Headline: {headline}

Respond with ONLY the category name. Nothing else."""


def _gpt_classify(headline: str) -> ContentType:
    try:
        response = _groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": _CLASSIFY_PROMPT.format(headline=headline)}],
            max_tokens=10,
            temperature=0,
        )
        result = response.choices[0].message.content.strip().lower()
        valid: list[ContentType] = ["breaking_news", "transfer_rumour", "club_update", "tactical"]
        if result in valid:
            return result  # type: ignore[return-value]
    except Exception as e:
        logger.warning("Groq classify failed: %s", e)
    return "club_update"  # safe default


def classify(item: NewsItem) -> ContentType:
    text = item.headline + " " + item.body[:300]
    result = _keyword_classify(text)
    if result:
        logger.debug("Keyword classified '%s' as %s", item.headline[:60], result)
        return result
    result = _gpt_classify(item.headline)
    logger.debug("GPT classified '%s' as %s", item.headline[:60], result)
    return result


def get_club_from_item(item: NewsItem) -> str | None:
    """Extract the primary club name mentioned in the news item."""
    text = (item.headline + " " + item.body[:200]).lower()
    for club in settings.CLUB_COLOURS:
        if club != "default" and club in text:
            return club
    return None


# ── Batch classifier (Optimisation 4) ────────────────────────────────────────

_BATCH_PROMPT = """Classify each football news headline into exactly one category:
- breaking_news   (confirmed, official, or just-announced news)
- transfer_rumour (unconfirmed transfers, links, rumours, negotiations)
- club_update     (injuries, suspensions, managerial changes, club announcements)
- tactical        (match reports, formations, tactical analysis)

Headlines:
{lines}

Respond with ONLY a JSON object mapping number to category.
Example: {{"1": "breaking_news", "2": "transfer_rumour"}}
No explanation. No extra text."""

_VALID_TYPES: list[ContentType] = [
    "breaking_news", "transfer_rumour", "club_update", "tactical"
]


def _groq_batch_classify(
    indexed_items: list[tuple[int, NewsItem]],
) -> dict[str, ContentType]:
    """Single Groq call for a batch of up to 10 headlines."""
    lines = "\n".join(f"{idx}. {item.headline}" for idx, item in indexed_items)
    prompt = _BATCH_PROMPT.format(lines=lines)

    result: dict[str, ContentType] = {}
    try:
        response = _groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=120,
            temperature=0,
        )
        raw = response.choices[0].message.content.strip()
        parsed: dict = json.loads(raw)

        for idx_str, category in parsed.items():
            cat = category.lower().strip()
            for orig_idx, item in indexed_items:
                if orig_idx == int(idx_str):
                    result[item.id] = cat if cat in _VALID_TYPES else "club_update"  # type: ignore[assignment]
                    break
    except Exception as e:
        logger.warning("Batch Groq classify failed: %s — defaulting all to club_update", e)
        for _, item in indexed_items:
            result[item.id] = "club_update"

    return result


def batch_classify(items: list[NewsItem]) -> dict[str, ContentType]:
    """
    Classify a list of items efficiently:
      - Keyword matching first (free, instant)
      - Groq called only for items keywords couldn't resolve, in batches of 10

    Returns: {news_id: ContentType}
    """
    if not items:
        return {}

    result: dict[str, ContentType] = {}
    needs_groq: list[tuple[int, NewsItem]] = []

    for i, item in enumerate(items, start=1):
        text = item.headline + " " + item.body[:300]
        kw = _keyword_classify(text)
        if kw:
            result[item.id] = kw
            logger.debug("Keyword classified '%s' as %s", item.headline[:60], kw)
        else:
            needs_groq.append((i, item))

    # Batch the Groq calls — 10 headlines per call
    for batch_start in range(0, len(needs_groq), 10):
        batch = needs_groq[batch_start:batch_start + 10]
        batch_result = _groq_batch_classify(batch)
        result.update(batch_result)
        logger.debug(
            "Groq batch classified %d items (%d–%d)",
            len(batch), batch_start + 1, batch_start + len(batch),
        )

    groq_calls = max(1, (len(needs_groq) + 9) // 10) if needs_groq else 0
    logger.info(
        "batch_classify: %d items → %d keyword, %d via Groq (%d API call(s))",
        len(items),
        len(items) - len(needs_groq),
        len(needs_groq),
        groq_calls,
    )
    return result
