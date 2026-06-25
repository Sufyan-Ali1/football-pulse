"""
Football AutoNews Engine — main entry point.

Start the full system:
    python main.py

What this does:
  1. Runs an immediate collector poll on startup
  2. Schedules collector (RSS + Google Alerts → DB) every hour
  3. Schedules daily video generation once per day (default 8 PM UTC)

To run just one collector poll manually (useful for testing):
    python main.py --once
"""
import logging
import sys
import threading
from pathlib import Path

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from pipeline.collector    import run_collector
from pipeline.daily_runner import run_daily_video
from pipeline.post_match_runner import run_post_match_videos, run_post_match_watcher

# ── Logging ───────────────────────────────────────────────────────────────────

_LOG_DIR = Path(__file__).resolve().parent / "logs"
_LOG_DIR.mkdir(exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.StreamHandler(open(sys.stdout.fileno(), mode='w', encoding='utf-8', closefd=False)),
        logging.FileHandler(_LOG_DIR / "pipeline.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger(__name__)


def _supervise_post_match_watcher(stop_event: threading.Event) -> None:
    while not stop_event.is_set():
        try:
            run_post_match_watcher(stop_event=stop_event)
        except Exception:
            logger.exception("Post-match watcher crashed; restarting after backoff.")
            stop_event.wait(60)
            continue

        if not stop_event.is_set():
            logger.warning("Post-match watcher exited unexpectedly; restarting after backoff.")
            stop_event.wait(60)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    run_once = "--once" in sys.argv
    post_match_once = "--post-match-once" in sys.argv

    if run_once:
        logger.info("Running a single collector poll (--once mode).")
        run_collector()
        return

    if post_match_once:
        logger.info("Running a single post-match video pass (--post-match-once mode).")
        run_post_match_videos(bypass_enabled=True)
        return

    scheduler = BlockingScheduler(timezone="UTC")
    post_match_stop = threading.Event()
    post_match_thread: threading.Thread | None = None

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

    # Job 2: generate daily multi-story video twice per day (7 AM + 7 PM UTC)
    for hour in settings.DAILY_VIDEO_HOURS_UTC:
        slot = "am" if hour < 12 else "pm"
        scheduler.add_job(
            run_daily_video,
            trigger=CronTrigger(hour=hour, minute=0, timezone="UTC"),
            id=f"daily_video_{slot}",
            name=f"Daily Video Generator ({slot.upper()})",
            max_instances=1,
            coalesce=True,
            misfire_grace_time=3600,
        )

    logger.info(
        "Football AutoNews Engine started. Collector every %ds, "
        "daily video at %s UTC, post-match watcher %s. Press Ctrl+C to stop.",
        settings.POLL_INTERVAL_RSS,
        " and ".join(f"{h:02d}:00" for h in settings.DAILY_VIDEO_HOURS_UTC),
        "enabled" if settings.POST_MATCH_ENABLED else "disabled",
    )

    try:
        run_collector()         # Run immediately on startup
        if settings.POST_MATCH_ENABLED:
            post_match_thread = threading.Thread(
                target=_supervise_post_match_watcher,
                args=(post_match_stop,),
                name="post-match-watcher",
                daemon=False,
            )
            post_match_thread.start()
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("Stopped.")
    finally:
        post_match_stop.set()
        if post_match_thread and post_match_thread.is_alive():
            post_match_thread.join(timeout=10)


if __name__ == "__main__":
    main()
