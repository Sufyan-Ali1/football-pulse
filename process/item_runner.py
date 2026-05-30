"""
Single-item pipeline runner.

Chains all processing steps for one NewsItem:
  classify → script → voiceover → video

Used by pipeline/collector.py for immediate breaking news processing.
Each step retries up to MAX_RETRIES times with exponential backoff.
"""
import logging
import time
from pathlib import Path

from config import settings
from core.types import NewsItem, PipelineResult, Script
from process import classifier, voiceover
from process.script_gen import generate_segment_script
from core.database import get_all_clips
from process.video_maker import create_multi_story_video
from publish.youtube import generate_metadata, upload_video
from clients.gdrive import sync_storage_to_drive

logger = logging.getLogger(__name__)


def _retry(fn, *args, **kwargs):
    last: Exception | None = None
    for attempt in range(1, settings.MAX_RETRIES + 1):
        try:
            return fn(*args, **kwargs)
        except Exception as e:
            last = e
            wait = settings.RETRY_BACKOFF ** attempt
            logger.warning("Attempt %d/%d failed for %s: %s — retrying in %ds",
                           attempt, settings.MAX_RETRIES, fn.__name__, e, wait)
            time.sleep(wait)
    raise last


def run_pipeline(item: NewsItem, content_type: str | None = None) -> PipelineResult:
    """Run script → voiceover → video for a single NewsItem.

    Pass content_type from the DB (already groq_verified) to skip re-classification.
    If omitted, falls back to a fresh classify() call.
    """
    logger.info("=== Pipeline START: %s ===", item.headline[:80])

    try:
        if content_type is None:
            content_type = classifier.classify(item)
        logger.info("[1/3] content_type: %s", content_type)

        script = _retry(generate_segment_script, item, content_type, get_all_clips())
        logger.info("[2/3] Script: %dw", script.word_count)

        vo_path = _retry(voiceover.generate_voiceover, script, "english")
        logger.info("[3/3] Voiceover done")

        video_path = create_multi_story_video(
            [(script, item, vo_path)],
            output_name=script.news_id,
        )

        metadata = generate_metadata(item, script)
        video_id = upload_video(video_path, None, metadata)
        logger.info("[4/4] YouTube upload: %s", video_id)

        sync_storage_to_drive()

        video_path.unlink(missing_ok=True)
        vo_path.unlink(missing_ok=True)
        logger.info("Local files cleaned up")

        logger.info("=== Pipeline COMPLETE: %s ===", video_path.name)
        return PipelineResult(news_id=item.id, success=True, youtube_video_id=video_id)

    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        logger.error("=== Pipeline FAILED: %s | %s ===", item.headline[:80], msg)
        return PipelineResult(news_id=item.id, success=False, error=msg)
