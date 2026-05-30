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

    # ── Fuzzy dedup ───────────────────────────────────────────────────────────
    unique = deduplicate_fuzzy(new_items)
    logger.info("Dedup: %d -> %d unique (removed %d near-duplicates)", len(new_items), len(unique), len(new_items) - len(unique))

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
