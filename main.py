"""
Football AutoNews Engine — main entry point.

Start the full system:
    python main.py

What this does:
  1. Runs an immediate collector poll on startup
  2. Schedules collector (RSS + Google Alerts → DB) every 5 minutes
  3. Schedules daily video generation once per day (default 8 PM UTC)
  4. Starts the 24/7 FFmpeg livestream (if final videos exist)

To run just one collector poll manually (useful for testing):
    python main.py --once
"""
import logging
import sys
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from pipeline.collector    import run_collector
from pipeline.daily_runner import run_daily_video

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
        logger.info("Running a single collector poll (--once mode).")
        run_collector()
        return

    scheduler = BlockingScheduler(timezone="UTC")

    # Job 1: collect articles every 5 minutes
    scheduler.add_job(
        run_collector,
        trigger=IntervalTrigger(seconds=settings.POLL_INTERVAL_RSS),
        id="rss_poll",
        name="RSS + Google Alerts Collector",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=60,
    )

    # Job 2: generate daily multi-story video once per day
    scheduler.add_job(
        run_daily_video,
        trigger=CronTrigger(hour=settings.DAILY_VIDEO_HOUR_UTC, minute=0, timezone="UTC"),
        id="daily_video",
        name="Daily Video Generator",
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    logger.info(
        "Football AutoNews Engine started. Collector every %ds, daily video at %02d:00 UTC. "
        "Press Ctrl+C to stop.",
        settings.POLL_INTERVAL_RSS,
        settings.DAILY_VIDEO_HOUR_UTC,
    )

    try:
        run_collector()         # Run immediately on startup
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopped.")


if __name__ == "__main__":
    main()
