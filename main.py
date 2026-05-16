"""
Football AutoNews Engine — main entry point.

Start the full system:
    python main.py

What this does:
  1. Runs an immediate first poll on startup
  2. Schedules RSS + Google Alerts every 5 minutes
  3. Starts the 24/7 FFmpeg livestream (if final videos exist)

To run just one poll manually (useful for testing):
    python main.py --once
"""
import logging
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from fetch.rss      import fetch_all_rss
from fetch.alerts   import fetch_google_alerts
from pipeline.orchestrator import run_batch

# ── Logging ───────────────────────────────────────────────────────────────────

_LOG_DIR = Path(__file__).resolve().parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler(_LOG_DIR / "pipeline.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


# ── Poll jobs ─────────────────────────────────────────────────────────────────

def poll_rss_and_alerts() -> None:
    logger.info("--- Poll started ---")
    items = fetch_all_rss() + fetch_google_alerts()
    if items:
        run_batch(items)
    logger.info("--- Poll done (%d items fetched) ---", len(items))


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    run_once = "--once" in sys.argv

    # Attempt to start the FFmpeg livestream (skipped if no videos yet)
    try:
        from publish.livestream import start_ffmpeg_stream
        start_ffmpeg_stream()
    except Exception as e:
        logger.warning("FFmpeg stream not started: %s", e)

    if run_once:
        logger.info("Running a single poll (--once mode).")
        poll_rss_and_alerts()
        return

    scheduler = BlockingScheduler(timezone="UTC")
    scheduler.add_job(
        poll_rss_and_alerts,
        trigger=IntervalTrigger(seconds=settings.POLL_INTERVAL_RSS),
        id="rss_poll",
        name="RSS + Google Alerts",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )

    logger.info(
        "Football AutoNews Engine started. Polling every %ds. Press Ctrl+C to stop.",
        settings.POLL_INTERVAL_RSS,
    )

    try:
        poll_rss_and_alerts()   # Run immediately on startup
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopped.")


if __name__ == "__main__":
    main()
