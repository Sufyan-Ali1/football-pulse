"""
Single-item pipeline runner.

Chains all processing steps for one NewsItem:
  classify → script → voiceover → video

Used by pipeline/collector.py for immediate breaking news processing.
Each step retries up to MAX_RETRIES times with exponential backoff.
"""
import logging
import shutil
import time
from pathlib import Path

from config import settings
from core.types import NewsItem, PipelineResult, Script
from process import classifier, voiceover
from process.script_gen import generate_segment_script
from core.database import get_all_clips
from process.video_maker import create_multi_story_video

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


def _promote_moviepy_output(raw_video_path: Path, script: Script) -> Path:
    output_path = settings.VIDEOS_FINAL_DIR / f"{script.news_id}_final_branded.mp4"

    if output_path.exists():
        logger.info("Final video already exists, skipping copy: %s", output_path.name)
        return output_path

    settings.VIDEOS_FINAL_DIR.mkdir(parents=True, exist_ok=True)
    shutil.copy2(raw_video_path, output_path)
    logger.info("Final video saved: %s", output_path.name)
    return output_path


def run_pipeline(item: NewsItem) -> PipelineResult:
    """Run classify → script → voiceover → video for a single NewsItem."""
    logger.info("=== Pipeline START: %s ===", item.headline[:80])

    try:
        content_type = classifier.classify(item)
        logger.info("[1/3] Classified: %s", content_type)

        script = _retry(generate_segment_script, item, content_type, get_all_clips())
        logger.info("[2/3] Script: %dw", script.word_count)

        vo_path = _retry(voiceover.generate_voiceover, script, "english")
        logger.info("[3/3] Voiceover done")

        raw_path  = create_multi_story_video(
            [(script, item, vo_path)],
            output_name=script.news_id,
        )
        final_path = _promote_moviepy_output(raw_path, script)
        logger.info("=== Pipeline COMPLETE: %s ===", final_path.name)

        return PipelineResult(news_id=item.id, success=True)

    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        logger.error("=== Pipeline FAILED: %s | %s ===", item.headline[:80], msg)
        return PipelineResult(news_id=item.id, success=False, error=msg)
