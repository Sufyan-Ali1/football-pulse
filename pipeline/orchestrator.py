"""
Pipeline orchestrator.

Chains all processing steps for a single NewsItem:
  classify → scripts → voiceover → presenter video
  → branding → thumbnail → YouTube upload → social post → livestream

Each step retries up to MAX_RETRIES times with exponential backoff.
A step failure does not stop other items from being processed.

run_batch() is the main entry point called by main.py on each poll cycle.
"""
import logging
import time

from config import settings
from core.types import NewsItem, PipelineResult
from pipeline import deduplication
from process import (
    classifier,
    ranker,
    script_gen,
    voiceover,
    thumbnail,
)
from process.presenter   import create_presenter_video
from process.video_editor import apply_branding
from publish.youtube     import upload_video
from publish.social      import post_short_to_socials
from publish.livestream  import add_video_to_rotation, rebuild_concat_list

logger = logging.getLogger(__name__)


# ── Retry helper ──────────────────────────────────────────────────────────────

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


# ── Single item pipeline ──────────────────────────────────────────────────────

def run_pipeline(item: NewsItem) -> PipelineResult:
    """Run the full production pipeline for one NewsItem."""
    logger.info("=== Pipeline START: %s ===", item.headline[:80])
    deduplication.mark_pipeline_started(item.id)

    try:
        # 1. Classify
        content_type = classifier.classify(item)
        logger.info("[1/9] Classified: %s", content_type)

        # 2. Generate scripts
        main_script, short_script = _retry(script_gen.generate_all_scripts, item, content_type)
        logger.info("[2/9] Scripts: %dw main, %dw short", main_script.word_count, short_script.word_count)

        # 3. Voiceovers
        main_voice  = _retry(voiceover.generate_voiceover, main_script,  "english")
        short_voice = _retry(voiceover.generate_voiceover, short_script, "english")
        logger.info("[3/9] Voiceovers done")

        # 4. Presenter videos
        main_raw  = _retry(create_presenter_video, main_script,  main_voice)
        short_raw = _retry(create_presenter_video, short_script, short_voice)
        logger.info("[4/9] Presenter videos done")

        # 5. Branding
        main_final  = _retry(apply_branding, main_raw,  item, main_script)
        short_final = _retry(apply_branding, short_raw, item, short_script)
        logger.info("[5/9] Branding done")

        # 6. Thumbnail
        thumb = _retry(thumbnail.generate_thumbnail, item, main_script)
        logger.info("[6/9] Thumbnail done")

        # 7. YouTube upload
        yt_id = _retry(upload_video, main_final, thumb, item, main_script, schedule=True)
        logger.info("[7/9] YouTube: %s", yt_id)

        # 8. Social post
        _retry(post_short_to_socials, short_final, item, short_script)
        logger.info("[8/9] Social post done")

        # 9. Livestream
        _retry(add_video_to_rotation, yt_id)
        rebuild_concat_list()
        logger.info("[9/9] Livestream updated")

        deduplication.mark_seen(item)
        deduplication.mark_pipeline_finished(item.id)
        logger.info("=== Pipeline COMPLETE: %s | yt=%s ===", item.headline[:80], yt_id)
        return PipelineResult(news_id=item.id, success=True, youtube_video_id=yt_id)

    except Exception as e:
        msg = f"{type(e).__name__}: {e}"
        logger.error("=== Pipeline FAILED: %s | %s ===", item.headline[:80], msg)
        deduplication.mark_pipeline_finished(item.id, error=msg)
        deduplication.mark_seen(item)
        return PipelineResult(news_id=item.id, success=False, error=msg)


# ── Batch pipeline (called every poll cycle) ──────────────────────────────────

def run_batch(
    items: list[NewsItem],
    top_n: int = 20,
    max_per_run: int = 3,
) -> list[PipelineResult]:
    """
    Full optimised batch:
      1. Filter already-seen items
      2. Fuzzy dedup + quality scoring → top N
      3. Cap at max_per_run, breaking news first
      4. Run pipeline for each selected item
    """
    new_items = deduplication.filter_unseen(items)
    logger.info("Batch: %d total, %d unseen", len(items), len(new_items))
    if not new_items:
        return []

    top   = ranker.rank_and_filter(new_items, top_n=top_n)
    batch = ranker.get_batch_for_pipeline(top, max_per_run=max_per_run)

    results = [run_pipeline(item) for item in batch]
    ok      = sum(1 for r in results if r.success)
    logger.info("Batch complete: %d/%d succeeded", ok, len(results))
    return results
