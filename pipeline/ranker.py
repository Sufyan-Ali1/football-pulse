"""
Ranker: scores, deduplicates, and prioritises NewsItems before
they enter the production pipeline.

Optimisations implemented here:
  1. Football relevance already applied in news_monitor.py at fetch time
  2. Fuzzy duplicate deduplication  (Jaccard word-set similarity)
  3. Quality / priority scoring     (source tier + recency + signals + clubs)
  4. Top-N filter                   (only best 20 items reach classification)
  5. Per-run cap                    (max 3 items per pipeline run, breaking first)
"""
import logging
import re
from datetime import datetime, timezone

from config import settings
from modules.news_monitor import NewsItem

logger = logging.getLogger(__name__)

# ── Source tier scores (0–100) ────────────────────────────────────────────────

_SOURCE_TIERS: dict[str, int] = {
    "Sky Sports Football":    90,
    "BBC Sport Football":     85,
    "The Guardian Football":  80,
    "ESPN FC":                75,
    "Google Alerts":          70,
    "TalkSport":              65,
    "90min":                  60,
    "Football Italia":        55,
}
_DEFAULT_SOURCE_SCORE = 40

# ── Breaking signals (same list as content_classifier for consistency) ────────

_BREAKING_SIGNALS = [
    "here we go", "confirmed", "done deal", "official", "breaking",
    "agreement reached", "deal signed", "medicals", "contract signed",
    "announced", "unveiled", "sacked", "appointed",
]

# ── Stop-words stripped before Jaccard similarity ─────────────────────────────

_STOP_WORDS = {
    "the", "a", "an", "is", "in", "on", "at", "to", "for", "of",
    "and", "or", "but", "it", "he", "she", "we", "are", "was", "has",
    "have", "be", "been", "that", "this", "with", "from", "as",
}


# ── Scoring helpers ───────────────────────────────────────────────────────────

def _source_score(item: NewsItem) -> int:
    return _SOURCE_TIERS.get(item.source, _DEFAULT_SOURCE_SCORE)


def _recency_score(item: NewsItem) -> int:
    try:
        ts = item.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
    except Exception:
        return 0
    if age_min < 30:
        return 30
    if age_min < 60:
        return 20
    if age_min < 180:
        return 10
    if age_min < 360:
        return 5
    return 0


def _breaking_score(item: NewsItem) -> int:
    text = (item.headline + " " + item.body[:150]).lower()
    return 30 if any(sig in text for sig in _BREAKING_SIGNALS) else 0


def _club_score(item: NewsItem) -> int:
    text = (item.headline + " " + item.body[:200]).lower()
    for club in settings.CLUB_COLOURS:
        if club != "default" and club in text:
            return 20
    return 0


def score_item(item: NewsItem) -> int:
    """Returns a 0–160 quality score for an item."""
    return (
        _source_score(item)
        + _recency_score(item)
        + _breaking_score(item)
        + _club_score(item)
    )


# ── Fuzzy duplicate deduplication (Jaccard word-set similarity) ───────────────

def _normalise(text: str) -> set[str]:
    words = re.sub(r"[^a-z0-9\s]", "", text.lower()).split()
    return {w for w in words if w not in _STOP_WORDS and len(w) > 2}


def _jaccard(a: str, b: str) -> float:
    wa, wb = _normalise(a), _normalise(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def deduplicate_fuzzy(
    items: list[NewsItem],
    threshold: float = 0.65,
) -> list[NewsItem]:
    """
    Remove near-duplicate headlines.
    When two items share ≥65% of their words, keep only the higher-scored one.
    Items are pre-sorted by score so the first survivor in each cluster is best.
    """
    scored = sorted(items, key=score_item, reverse=True)
    kept: list[NewsItem] = []

    for candidate in scored:
        duplicate = any(
            _jaccard(candidate.headline, existing.headline) >= threshold
            for existing in kept
        )
        if not duplicate:
            kept.append(candidate)

    removed = len(items) - len(kept)
    if removed:
        logger.info("Fuzzy dedup removed %d near-duplicate items", removed)
    return kept


# ── Main public API ───────────────────────────────────────────────────────────

def rank_and_filter(items: list[NewsItem], top_n: int = 20) -> list[NewsItem]:
    """
    Full pre-pipeline filter:
      1. Fuzzy deduplicate
      2. Score and keep top N
    Returns items sorted best-first.
    """
    unique = deduplicate_fuzzy(items)
    ranked = sorted(unique, key=score_item, reverse=True)
    top = ranked[:top_n]

    logger.info(
        "Ranker: %d items in → %d unique → %d selected (top %d)",
        len(items), len(unique), len(top), top_n,
    )
    return top


def _is_breaking(item: NewsItem) -> bool:
    text = (item.headline + " " + item.body[:150]).lower()
    return any(sig in text for sig in _BREAKING_SIGNALS)


def prioritize(items: list[NewsItem]) -> list[NewsItem]:
    """
    Sort items so breaking news comes first, then by quality score.
    Call this after rank_and_filter and before run_pipeline.
    """
    breaking = [i for i in items if _is_breaking(i)]
    others   = [i for i in items if not _is_breaking(i)]
    return breaking + others


def get_batch_for_pipeline(
    items: list[NewsItem],
    max_per_run: int = 3,
) -> list[NewsItem]:
    """
    Returns at most max_per_run items, breaking news at the front of the list.
    This is the final gate before the production pipeline.
    """
    prioritized = prioritize(items)
    batch = prioritized[:max_per_run]
    logger.info(
        "Pipeline batch: %d/%d items selected (max_per_run=%d)",
        len(batch), len(items), max_per_run,
    )
    return batch
