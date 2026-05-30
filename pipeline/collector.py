"""
Collector — Job 1 (every 5 minutes).

Fetch RSS + Google Alerts → classify → rank → save to articles DB.
No scripts, no voiceovers. Just accumulate articles.

Breaking news exception: if an article is classified as breaking_news
AND has a rank score ≥ BREAKING_SCORE_THRESHOLD, flag it for immediate
processing and generate a standalone video right away.
"""
import logging
import time

from config import settings
from core.constants import BREAKING_CONTENT_TYPES
from core.database import (
    article_exists,
    demote_stale_breaking_articles,
    get_breaking_articles,
    insert_article,
    mark_article_status,
    row_to_news_item,
)
from fetch.alerts import fetch_google_alerts
from fetch.rss import fetch_all_rss
from process.item_runner import run_pipeline
from process.ranker import deduplicate_fuzzy, score_item
from process.classifier import batch_classify
from process.verifier import verify_and_reclassify

logger = logging.getLogger(__name__)


def run_collector() -> None:
    """Fetch articles, classify, score, and save to DB. Process breaking news immediately."""
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
        score                      = score_item(item)
        content_type, classified_by = classifications.get(item.id, ("tactical", "keyword"))
        is_breaking                = content_type in BREAKING_CONTENT_TYPES and score >= settings.BREAKING_SCORE_THRESHOLD
        status                     = "breaking" if is_breaking else "pending"

        try:
            insert_article(item, content_type, score, status, classified_by)
            saved += 1
            counts[content_type] = counts.get(content_type, 0) + 1
            if is_breaking:
                logger.info("BREAKING flagged [%s, score=%d]: %s", classified_by, score, item.headline[:80])
        except Exception as e:
            logger.error("DB insert failed for '%s': %s", item.headline[:60], e)

    breakdown = "  ".join(f"{k}:{v}" for k, v in sorted(counts.items()) if v)
    logger.info("Saved %d articles — %s", saved, breakdown or "none")

    # ── Breaking news: verify then generate immediate video ───────────────────
    stale = demote_stale_breaking_articles()
    if stale:
        logger.info("Demoted %d stale breaking article(s) to pending", stale)
    breaking = get_breaking_articles()
    if not breaking:
        logger.info("No breaking news in queue")
    else:
        article = breaking[0]
        logger.info("Verifying breaking news [%d queued]: %s", len(breaking), article["headline"][:80])

        # 2nd-pass Groq check before committing to video generation
        verified = verify_and_reclassify([article])
        if not verified:
            logger.warning("Verifier returned no results — demoting breaking article: %s", article["headline"][:70])
            mark_article_status(article["id"], "pending")
        else:
            fresh = verified[0]

            if fresh["content_type"] not in BREAKING_CONTENT_TYPES:
                logger.info(
                    "Breaking news downgraded to [%s] after verification - skipping: %s",
                    fresh["content_type"], fresh["headline"][:70],
                )
                mark_article_status(fresh["id"], "pending")

            elif fresh["relevance_score"] is None or fresh["relevance_score"] < 7:
                logger.info(
                    "Breaking news low relevance [score=%d] - skipping pipeline: %s",
                    fresh["relevance_score"], fresh["headline"][:70],
                )
                mark_article_status(fresh["id"], "pending")

            else:
                item   = row_to_news_item(fresh)
                logger.info(
                    "Processing breaking news [relevance=%d]: %s",
                    fresh["relevance_score"], item.headline[:80],
                )
                result = run_pipeline(item, content_type=fresh["content_type"])
                if result.success:
                    mark_article_status(fresh["id"], "used")
                    logger.info("Breaking news video COMPLETE: %s", item.headline[:60])
                else:
                    logger.error("Breaking news pipeline FAILED: %s", result.error)

    logger.info("=== Collector DONE (%.1fs) ==========================================", time.monotonic() - t0)
