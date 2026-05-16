"""
Ranker — Step 3 pre-filter.

Before classification and pipeline execution, this module:
  1. Removes near-duplicate headlines (Jaccard word-set similarity)
  2. Scores each item (source tier + recency + breaking signals + club mention)
  3. Returns the top N items by score
  4. Caps the final batch sent to the pipeline (breaking news first)

This reduces ~300 raw articles down to 2–3 high-quality pipeline runs per cycle.
"""
import logging
import re
from datetime import datetime, timezone

from config import settings
from core.constants import BREAKING_SIGNALS, SOURCE_TIERS, DEFAULT_SOURCE_SCORE, STOP_WORDS
from core.types import NewsItem

logger = logging.getLogger(__name__)


# ── Scoring ───────────────────────────────────────────────────────────────────

def _source_score(item: NewsItem) -> int:
    return SOURCE_TIERS.get(item.source, DEFAULT_SOURCE_SCORE)


def _recency_score(item: NewsItem) -> int:
    try:
        ts = item.timestamp
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age_min = (datetime.now(timezone.utc) - ts).total_seconds() / 60
    except Exception:
        return 0
    if age_min < 30:  return 30
    if age_min < 60:  return 20
    if age_min < 180: return 10
    if age_min < 360: return 5
    return 0


def _breaking_score(item: NewsItem) -> int:
    text = (item.headline + " " + item.body[:150]).lower()
    return 30 if any(s in text for s in BREAKING_SIGNALS) else 0


def _club_score(item: NewsItem) -> int:
    text = (item.headline + " " + item.body[:200]).lower()
    for club in settings.CLUB_COLOURS:
        if club != "default" and club in text:
            return 20
    return 0


def score_item(item: NewsItem) -> int:
    """0–160 quality score. Higher = more likely to become a video."""
    return _source_score(item) + _recency_score(item) + _breaking_score(item) + _club_score(item)


# ── Fuzzy deduplication (Jaccard similarity) ──────────────────────────────────

def _words(text: str) -> set[str]:
    tokens = re.sub(r"[^a-z0-9\s]", "", text.lower()).split()
    return {w for w in tokens if w not in STOP_WORDS and len(w) > 2}


def _jaccard(a: str, b: str) -> float:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return 0.0
    return len(wa & wb) / len(wa | wb)


def deduplicate_fuzzy(items: list[NewsItem], threshold: float = 0.65) -> list[NewsItem]:
    """
    Remove near-duplicate headlines.
    Items are pre-sorted by score so the best version of each story is kept.
    """
    scored = sorted(items, key=score_item, reverse=True)
    kept: list[NewsItem] = []
    for candidate in scored:
        if not any(_jaccard(candidate.headline, k.headline) >= threshold for k in kept):
            kept.append(candidate)

    removed = len(items) - len(kept)
    if removed:
        logger.info("Fuzzy dedup removed %d near-duplicates", removed)
    return kept


# ── Public API ────────────────────────────────────────────────────────────────

def rank_and_filter(items: list[NewsItem], top_n: int = 20) -> list[NewsItem]:
    """
    Full pre-pipeline filter:
      1. Fuzzy deduplicate near-identical stories
      2. Score and return top N items
    """
    unique = deduplicate_fuzzy(items)
    ranked = sorted(unique, key=score_item, reverse=True)[:top_n]
    logger.info("rank_and_filter: %d in → %d unique → %d selected", len(items), len(unique), len(ranked))
    return ranked


def _is_breaking(item: NewsItem) -> bool:
    text = (item.headline + " " + item.body[:150]).lower()
    return any(s in text for s in BREAKING_SIGNALS)


def get_batch_for_pipeline(items: list[NewsItem], max_per_run: int = 3) -> list[NewsItem]:
    """
    Final gate before production pipeline.
    Returns at most max_per_run items with breaking news first.
    """
    breaking = [i for i in items if _is_breaking(i)]
    others   = [i for i in items if not _is_breaking(i)]
    batch    = (breaking + others)[:max_per_run]
    logger.info("Pipeline batch: %d/%d items (max=%d)", len(batch), len(items), max_per_run)
    return batch
