"""
Daily Runner — Job 2 (once per day, default 8 PM UTC).

Picks the top 3-5 highest-ranked pending articles from the DB,
verifies their classification via a 2nd Groq pass (skipping articles
already marked groq_verified), then generates a script + voiceover
per story and stitches them into one multi-story video.

Verification loop:
  Pull 10 articles -> verify unverified ones in batches of 5 -> collect
  -> repeat (up to MAX_VERIFY_ROUNDS) until we have MIN_STORIES_FOR_DAILY.
  This avoids sending all DB articles to Groq at once.

Minimum 3 stories required; if not enough accumulate, the job exits.
"""
import logging
import sqlite3
from datetime import date
from pathlib import Path

from config import settings
from core.database import (
    create_daily_video_record,
    daily_video_exists,
    get_all_clips,
    get_pending_articles,
    mark_articles_rejected,
    mark_articles_used,
    row_to_news_item,
    update_daily_video,
)
from core.types import NewsItem, Script, VideoMetadata
from process.script_gen import generate_segment_script
from process.verifier import verify_and_reclassify
from process.video_maker import create_multi_story_video
from process.voiceover import generate_voiceover
from publish.youtube import upload_video
from clients.gdrive import sync_storage_to_drive

logger = logging.getLogger(__name__)

_BATCH_SIZE      = 10   # articles pulled from DB per round
_MAX_ROUNDS      = 3    # max verification rounds (checks up to 30 articles total)


def _select_stories() -> list[sqlite3.Row]:
    """
    Pull and verify articles until we have MAX_STORIES_FOR_DAILY candidates.
    Articles with relevance_score < 5 are marked 'rejected' immediately so they
    never clog future rounds. Returns up to MAX_STORIES_FOR_DAILY verified
    articles sorted by rank_score.
    """
    verified: list[sqlite3.Row] = []
    needed = settings.MAX_STORIES_FOR_DAILY

    for round_num in range(_MAX_ROUNDS):
        if len(verified) >= needed:
            break

        offset = round_num * _BATCH_SIZE
        batch = get_pending_articles(limit=_BATCH_SIZE, offset=offset)
        if not batch:
            logger.info("No more pending articles at offset %d", offset)
            break

        unverified_count = sum(1 for a in batch if a["classified_by"] != "groq_verified")
        logger.info(
            "Verify round %d: %d articles (%d need Groq check)",
            round_num + 1, len(batch), unverified_count,
        )

        fresh = verify_and_reclassify(batch)

        # Filter right here — reject low-relevance articles so they never appear again
        passing, rejected = [], []
        for a in fresh:
            score = a["relevance_score"]
            if score is not None and score < 5:
                rejected.append(a)
            else:
                passing.append(a)

        if rejected:
            mark_articles_rejected([a["id"] for a in rejected])
            logger.info(
                "Round %d: rejected %d low-relevance articles (score < 5), kept %d",
                round_num + 1, len(rejected), len(passing),
            )

        verified.extend(passing)

    # Sort by rank_score and return top N
    return sorted(verified, key=lambda a: a["rank_score"] or 0, reverse=True)[:needed]


def run_daily_video() -> None:
    """Generate today's daily multi-story video from top verified pending articles."""
    today = date.today().isoformat()

    if daily_video_exists(today):
        logger.info("Daily video already generated for %s - skipping", today)
        return

    logger.info("=== Daily Runner START (%s) ===================================", today)

    articles = _select_stories()

    if len(articles) < settings.MIN_STORIES_FOR_DAILY:
        logger.warning(
            "Only %d verified articles available - need at least %d. Skipping daily video for %s",
            len(articles), settings.MIN_STORIES_FOR_DAILY, today,
        )
        return

    article_ids = [a["id"] for a in articles]
    create_daily_video_record(today, article_ids)
    update_daily_video(today, "generating")

    logger.info("Building %d-story video for %s ...", len(articles), today)

    clip_library = get_all_clips()
    logger.info("Clip library: %d clips loaded", len(clip_library))

    stories: list[tuple[Script, NewsItem, Path | None]] = []
    try:
        for i, article in enumerate(articles, start=1):
            item         = row_to_news_item(article)
            content_type = article["content_type"]

            logger.info("[%d/%d] Script [%s]: %s", i, len(articles), content_type, item.headline[:70])
            script = generate_segment_script(item, content_type, clips=clip_library)

            logger.info("[%d/%d] Voiceover ...", i, len(articles))
            vo_path = generate_voiceover(script, "english")

            stories.append((script, item, vo_path))

        video_output = create_multi_story_video(stories, output_name=f"daily_{today}")

        headlines = [row_to_news_item(a).headline for a in articles]
        title = f"Football News Today | {len(articles)} Stories | {today} | {settings.BRAND_NAME}"[:95]
        description = (
            f"Today's top football stories on {settings.BRAND_NAME}.\n\n"
            + "\n".join(f"• {h}" for h in headlines)
            + f"\n\n{settings.BRAND_NAME} – {settings.BRAND_TAGLINE}"
        )
        metadata = VideoMetadata(
            title=title,
            description=description,
            tags=["football", "football news", "transfer news", "football today", settings.BRAND_NAME.lower()],
            privacy_status="public",
        )
        video_id = upload_video(video_output, None, metadata)
        logger.info("YouTube upload: %s", video_id)

        sync_storage_to_drive()

        mark_articles_used(article_ids, today)
        update_daily_video(today, "done", video_path=f"youtube:{video_id}")

        video_output.unlink(missing_ok=True)
        for _, _, vo_path in stories:
            if vo_path:
                Path(vo_path).unlink(missing_ok=True)
        logger.info("Local files cleaned up")

        logger.info("=== Daily Runner DONE: %s (%d stories) ===", video_output.name, len(stories))

    except Exception as e:
        update_daily_video(today, "failed", error=f"{type(e).__name__}: {e}")
        logger.error("=== Daily Runner FAILED for %s: %s ===", today, e)
        raise
