"""
Main scheduler entry point.
Uses APScheduler to poll news sources on cron intervals and
trigger the pipeline for any new items found.

Run this file to start the system:
    python scheduler.py
"""
import logging
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from modules.news_monitor import get_all_new_items
from pipeline.orchestrator import run_batch

# ── Logging setup ─────────────────────────────────────────────────────────────
LOG_DIR = Path(__file__).resolve().parent / "logs"
LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(LOG_DIR / "pipeline.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)

# Track the latest Twitter tweet ID to avoid re-fetching
_twitter_since_id: str | None = None


def poll_rss_and_alerts() -> None:
    """Polls RSS feeds and Google Alerts, runs pipeline on new items."""
    logger.info("--- RSS/Alerts poll started ---")
    from modules.news_monitor import fetch_all_rss, fetch_google_alerts
    items = fetch_all_rss() + fetch_google_alerts()
    if items:
        run_batch(items)
    logger.info("--- RSS/Alerts poll done (%d items) ---", len(items))


def poll_twitter() -> None:
    """Polls Twitter/X, runs pipeline on new items."""
    global _twitter_since_id
    logger.info("--- Twitter poll started ---")
    from modules.news_monitor import fetch_twitter_posts
    items = fetch_twitter_posts(since_id=_twitter_since_id)
    if items:
        # Update since_id to the most recent tweet seen
        # Tweet IDs are snowflake-sorted ascending; take the last raw id
        try:
            latest = max(
                (item for item in items if item.raw.get("tweet_id")),
                key=lambda i: int(i.raw["tweet_id"]),
                default=None,
            )
            if latest:
                _twitter_since_id = latest.raw["tweet_id"]
        except Exception:
            pass
        run_batch(items)
    logger.info("--- Twitter poll done (%d items) ---", len(items))


def main() -> None:
    scheduler = BlockingScheduler(timezone="UTC")

    # RSS + Google Alerts: every 5 minutes
    scheduler.add_job(
        poll_rss_and_alerts,
        trigger=IntervalTrigger(seconds=settings.POLL_INTERVAL_RSS),
        id="rss_poll",
        name="RSS + Google Alerts poll",
        max_instances=1,       # Prevent overlapping runs
        coalesce=True,
        misfire_grace_time=60,
    )

    # Twitter/X: every 15 minutes (Twitter rate-limit friendly)
    scheduler.add_job(
        poll_twitter,
        trigger=IntervalTrigger(seconds=settings.POLL_INTERVAL_TWITTER),
        id="twitter_poll",
        name="Twitter/X poll",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )

    logger.info(
        "Scheduler started. RSS every %ds, Twitter every %ds",
        settings.POLL_INTERVAL_RSS,
        settings.POLL_INTERVAL_TWITTER,
    )
    logger.info("Football AutoNews Engine is running. Press Ctrl+C to stop.")

    try:
        # Run an immediate first poll on startup
        poll_rss_and_alerts()
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Scheduler stopped.")


if __name__ == "__main__":
    main()
