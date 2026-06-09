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
import re
import sqlite3
from datetime import date, datetime, timezone
from pathlib import Path

from clients.groq_client import get_groq_client
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
from process.quality_gate import assess_article_row_quality
from process.script_gen import generate_segment_script
from process.verifier import verify_and_reclassify
from process.video_maker import create_multi_story_video
from process.voiceover import generate_voiceover
from publish.youtube import upload_video
from clients.gdrive import sync_storage_to_drive

logger = logging.getLogger(__name__)

_BATCH_SIZE      = 10   # articles pulled from DB per round
_MAX_ROUNDS      = 3    # max verification rounds (checks up to 30 articles total)
_CANDIDATE_COUNT = 7    # fetch extra stories before LLM dedup, then trim to MAX_STORIES_FOR_DAILY
_MIN_RELEVANCE_SCORE = 6
_MIN_GOOGLE_ALERTS_RELEVANCE_SCORE = 7


def _daily_rejection_reason(article: sqlite3.Row) -> str | None:
    quality = assess_article_row_quality(article)
    if not quality.allowed:
        return quality.reason

    score = article["relevance_score"]
    if score is None:
        return "missing_relevance_score"
    if score < _MIN_RELEVANCE_SCORE:
        return f"low_relevance_{score}"
    if article["source"] == "Google Alerts" and score < _MIN_GOOGLE_ALERTS_RELEVANCE_SCORE:
        return f"low_google_alerts_relevance_{score}"
    return None


def _dedup_stories(articles: list[sqlite3.Row]) -> list[sqlite3.Row]:
    """
    Send headlines to Groq and ask it to identify duplicate/same-story articles.
    Returns the deduplicated list — duplicates removed, originals kept.
    """
    if len(articles) <= 1:
        return articles

    numbered = "\n".join(
        f"{i+1}. {a['headline'][:120]}" for i, a in enumerate(articles)
    )
    prompt = (
        "You are reviewing football news headlines for a YouTube channel.\n"
        "Your job is to find headlines that report the EXACT SAME piece of news "
        "(e.g. two sources both saying 'Player X signs for Club Y').\n\n"
        "IMPORTANT rules:\n"
        "- Different moments or angles of the same match ARE different stories "
        "(e.g. 'Havertz scores opener' vs 'Dembele equalises' vs 'PSG win on penalties' "
        "are ALL different stories — do NOT remove any of them).\n"
        "- Only remove a headline if it conveys the exact same news as another headline "
        "already in the list, just worded differently or from a different source.\n"
        "- When in doubt, keep the article (do NOT remove it).\n\n"
        f"Headlines:\n{numbered}\n\n"
        "Reply with ONLY a comma-separated list of numbers to remove, or 'NONE'.\n"
        "Example: 3,5  or  NONE"
    )

    try:
        groq = get_groq_client()
        resp = groq.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
            temperature=0.0,
        )
        reply = resp.choices[0].message.content.strip()
        logger.info("Dedup LLM reply: %r", reply)

        if reply.upper() == "NONE" or not reply:
            return articles

        to_remove = set()
        for part in reply.split(","):
            part = part.strip()
            if part.isdigit():
                idx = int(part) - 1
                if 0 <= idx < len(articles):
                    to_remove.add(idx)

        if to_remove:
            removed_headlines = [articles[i]["headline"][:80] for i in to_remove]
            logger.info("Dedup removed %d duplicate(s): %s", len(to_remove), removed_headlines)

        return [a for i, a in enumerate(articles) if i not in to_remove]

    except Exception as e:
        logger.warning("Dedup LLM call failed — skipping dedup: %s", e)
        return articles


def _select_stories(max_age_hours: int = 12) -> list[sqlite3.Row]:
    """
    Pull and verify articles until we have _CANDIDATE_COUNT candidates.
    Runs an LLM dedup pass to remove same-story duplicates, then
    trims to MAX_STORIES_FOR_DAILY. Minimum MIN_STORIES_FOR_DAILY required.
    """
    verified: list[sqlite3.Row] = []
    needed = _CANDIDATE_COUNT
    offset = 0

    for round_num in range(_MAX_ROUNDS):
        if len(verified) >= needed:
            break

        batch = get_pending_articles(limit=_BATCH_SIZE, offset=offset, max_age_hours=max_age_hours)
        if not batch:
            logger.info("No more pending articles at offset %d", offset)
            break

        unverified_count = sum(1 for a in batch if a["classified_by"] != "groq_verified")
        logger.info(
            "Verify round %d: %d articles (%d need Groq check)",
            round_num + 1, len(batch), unverified_count,
        )

        fresh = verify_and_reclassify(batch)

        # Filter right here so weak formats never appear again.
        passing, rejected = [], []
        reject_counts: dict[str, int] = {}
        for a in fresh:
            reason = _daily_rejection_reason(a)
            if reason:
                rejected.append(a)
                reject_counts[reason] = reject_counts.get(reason, 0) + 1
            else:
                passing.append(a)

        if rejected:
            mark_articles_rejected([a["id"] for a in rejected])
            breakdown = "  ".join(f"{k}:{v}" for k, v in sorted(reject_counts.items()))
            logger.info(
                "Round %d: rejected %d quality/relevance articles (%s), kept %d",
                round_num + 1, len(rejected), breakdown, len(passing),
            )

        verified.extend(passing)
        offset += len(passing)

    # Sort by rank_score, take top _CANDIDATE_COUNT
    candidates = sorted(verified, key=lambda a: a["rank_score"] or 0, reverse=True)[:needed]

    # LLM dedup pass — remove same-story duplicates
    logger.info("Running LLM dedup on %d candidates ...", len(candidates))
    candidates = _dedup_stories(candidates)

    # Trim to final target
    return candidates[:settings.MAX_STORIES_FOR_DAILY]


def run_daily_video() -> None:
    """Generate a daily multi-story video from top verified pending articles.
    Runs twice per day — slot is determined from current UTC hour:
      00:00–11:59 UTC → 'am'  (key: 2026-06-01_am)
      12:00–23:59 UTC → 'pm'  (key: 2026-06-01_pm)
    """
    now   = datetime.now(timezone.utc)
    slot  = "am" if now.hour < 12 else "pm"
    today = date.today().isoformat()
    video_date = f"{today}_{slot}"

    if daily_video_exists(video_date):
        logger.info("Daily video already generated for %s - skipping", video_date)
        return

    logger.info("=== Daily Runner START (%s) ===================================", video_date)

    max_age_hours = 14 if slot == "am" else 10
    articles = _select_stories(max_age_hours=max_age_hours)

    final_articles, final_rejected = [], []
    final_reject_counts: dict[str, int] = {}
    for article in articles:
        reason = _daily_rejection_reason(article)
        if reason:
            final_rejected.append(article)
            final_reject_counts[reason] = final_reject_counts.get(reason, 0) + 1
        else:
            final_articles.append(article)

    if final_rejected:
        mark_articles_rejected([a["id"] for a in final_rejected])
        breakdown = "  ".join(f"{k}:{v}" for k, v in sorted(final_reject_counts.items()))
        logger.info(
            "Final quality gate rejected %d article(s) before video build (%s)",
            len(final_rejected), breakdown,
        )
        articles = final_articles

    if len(articles) < settings.MIN_STORIES_FOR_DAILY:
        logger.warning(
            "Only %d verified articles available - need at least %d. Skipping daily video for %s",
            len(articles), settings.MIN_STORIES_FOR_DAILY, video_date,
        )
        return

    article_ids = [a["id"] for a in articles]
    create_daily_video_record(video_date, article_ids)
    update_daily_video(video_date, "generating")

    logger.info("Building %d-story video for %s ...", len(articles), video_date)

    clip_library = get_all_clips()
    logger.info("Clip library: %d clips loaded", len(clip_library))

    def _clean(text: str) -> str:
        text = re.sub(r"<[^>]+>", "", text)
        text = " ".join(text.split())
        return text

    # Build stories — skip any article whose script or voiceover fails
    stories: list[tuple[Script, NewsItem, Path | None]] = []
    for i, article in enumerate(articles, start=1):
        item         = row_to_news_item(article)
        content_type = article["content_type"]

        logger.info("[%d/%d] Script [%s]: %s", i, len(articles), content_type, item.headline[:70])
        try:
            script = generate_segment_script(item, content_type, clips=clip_library)
        except Exception as e:
            logger.warning("[%d/%d] Script failed, skipping story: %s", i, len(articles), e)
            continue

        logger.info("[%d/%d] Voiceover ...", i, len(articles))
        try:
            vo_path = generate_voiceover(script, "english")
        except Exception as e:
            logger.warning("[%d/%d] Voiceover failed, skipping story: %s", i, len(articles), e)
            continue

        stories.append((script, item, vo_path))

    if len(stories) < settings.MIN_STORIES_FOR_DAILY:
        logger.warning(
            "Only %d/%d stories succeeded (need %d) — aborting %s",
            len(stories), len(articles), settings.MIN_STORIES_FOR_DAILY, video_date,
        )
        update_daily_video(video_date, "failed", error=f"Only {len(stories)} stories succeeded")
        return

    try:
        video_output = create_multi_story_video(stories, output_name=f"daily_{video_date}")

        headlines = [_clean(row_to_news_item(a).headline) for a in articles]
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

        sync_storage_to_drive(delete_local=True)

        mark_articles_used(article_ids, video_date)
        update_daily_video(video_date, "done", video_path=f"youtube:{video_id}")

        video_output.unlink(missing_ok=True)
        for _, _, vo_path in stories:
            if vo_path:
                Path(vo_path).unlink(missing_ok=True)
        logger.info("Local files cleaned up")

        logger.info("=== Daily Runner DONE: %s (%d stories, slot=%s) ===", video_output.name, len(stories), slot)

    except Exception as e:
        update_daily_video(video_date, "failed", error=f"{type(e).__name__}: {e}")
        logger.error("=== Daily Runner FAILED for %s: %s ===", video_date, e)
