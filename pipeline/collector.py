"""
Collector — Job 1 (every hour).

Fetch RSS + Google Alerts → classify → rank → save to articles DB.
No scripts, no voiceovers. Just accumulate articles.
All video generation happens in the daily runner at 8 PM UTC.
"""
import logging
import time

from config import settings
from core.database import (
    article_exists,
    insert_article,
)
from fetch.alerts import fetch_google_alerts
from fetch.rss import fetch_all_rss
from process.quality_gate import assess_item_quality
from process.ranker import deduplicate_fuzzy, score_item
from process.classifier import batch_classify

logger = logging.getLogger(__name__)


def run_collector() -> None:
    """Fetch articles, classify, score, and save to DB."""
    t0 = time.monotonic()
    logger.info("=== Collector START =============================================")

    # ── Fetch ─────────────────────────────────────────────────────────────────
    rss_items   = fetch_all_rss()
    alert_items = fetch_google_alerts()
    items = rss_items + alert_items

    logger.info(
        "Fetched: %d RSS + %d alerts = %d total",
        len(rss_items), len(alert_items), len(items),
    )

    if not items:
        logger.warning("No items fetched - check feed sources and network connection")
        logger.info("=== Collector DONE (%.1fs) - no items ===", time.monotonic() - t0)
        return

    # ── DB dedup ──────────────────────────────────────────────────────────────
    new_items   = [i for i in items if not article_exists(i.id)]
    already_in_db = len(items) - len(new_items)
    logger.info("DB check: %d new, %d already stored", len(new_items), already_in_db)

    if not new_items:
        logger.info("=== Collector DONE (%.1fs) - nothing new ===", time.monotonic() - t0)
        return

    # ── Quality gate + fuzzy dedup ────────────────────────────────────────────
    quality_counts: dict[str, int] = {}
    quality_kept = []
    for item in new_items:
        quality = assess_item_quality(item)
        if quality.allowed:
            quality_kept.append(item)
            continue
        quality_counts[quality.reason] = quality_counts.get(quality.reason, 0) + 1
        logger.info("Quality rejected [%s]: %s", quality.reason, item.headline[:100])

    if quality_counts:
        breakdown = "  ".join(f"{k}:{v}" for k, v in sorted(quality_counts.items()))
        logger.info(
            "Quality gate: %d -> %d kept (%s)",
            len(new_items), len(quality_kept), breakdown,
        )

    if not quality_kept:
        logger.info("=== Collector DONE (%.1fs) - no quality items ===", time.monotonic() - t0)
        return

    unique = deduplicate_fuzzy(quality_kept)
    logger.info("Dedup: %d -> %d unique (removed %d near-duplicates)", len(quality_kept), len(unique), len(quality_kept) - len(unique))

    # ── Classify ──────────────────────────────────────────────────────────────
    logger.info("Classifying %d articles ...", len(unique))
    classifications = batch_classify(unique)

    # ── Score + save ──────────────────────────────────────────────────────────
    counts: dict[str, int] = {}
    saved = 0

    for item in unique:
        score                       = score_item(item)
        content_type, classified_by = classifications.get(item.id, ("tactical", "keyword"))

        try:
            insert_article(item, content_type, score, "pending", classified_by)
            saved += 1
            counts[content_type] = counts.get(content_type, 0) + 1
        except Exception as e:
            logger.error("DB insert failed for '%s': %s", item.headline[:60], e)

    breakdown = "  ".join(f"{k}:{v}" for k, v in sorted(counts.items()) if v)
    logger.info("Saved %d articles — %s", saved, breakdown or "none")

    logger.info("=== Collector DONE (%.1fs) ==========================================", time.monotonic() - t0)
