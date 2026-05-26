"""
Test script for Job 2 - Step 2: Story Selection.

Runs _select_stories() with detailed per-step logging so you can see
exactly what happens at each round: what is fetched, what Groq returns,
what passes/gets rejected, and the final selection.

Usage:
    python test_story_selection.py
"""
import logging
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

from config import settings
from core.database import get_pending_articles, mark_articles_rejected
from process.verifier import verify_and_reclassify

_BATCH_SIZE = 10
_MAX_ROUNDS = 3


def select_stories():
    needed = settings.MAX_STORIES_FOR_DAILY
    verified = []

    logger.info("=== Step 2: Select Stories (target=%d) ===", needed)

    for round_num in range(_MAX_ROUNDS):
        if len(verified) >= needed:
            logger.info("[Round %d] Target reached (%d/%d) - stopping early",
                        round_num + 1, len(verified), needed)
            break

        offset = round_num * _BATCH_SIZE
        logger.info("[Round %d] Fetching articles (offset=%d, limit=%d) ...",
                    round_num + 1, offset, _BATCH_SIZE)

        batch = get_pending_articles(limit=_BATCH_SIZE, offset=offset)
        if not batch:
            logger.info("[Round %d] No more pending articles at offset %d - stopping",
                        round_num + 1, offset)
            break

        already_verified = [a for a in batch if a["classified_by"] == "groq_verified"]
        needs_groq       = [a for a in batch if a["classified_by"] != "groq_verified"]
        logger.info("[Round %d] Fetched %d articles: %d already groq_verified, %d need Groq",
                    round_num + 1, len(batch), len(already_verified), len(needs_groq))

        logger.info("[Round %d] Articles fetched:", round_num + 1)
        for a in batch:
            logger.info("  score=%-3d  %-14s  rel=%-4s  %s",
                        a["rank_score"],
                        a["classified_by"],
                        str(a["relevance_score"]) if a["relevance_score"] is not None else "NULL",
                        a["headline"][:70])

        logger.info("[Round %d] Running Groq verification ...", round_num + 1)
        fresh = verify_and_reclassify(batch)

        logger.info("[Round %d] Verification done - filtering by relevance score:", round_num + 1)
        passing, rejected = [], []
        for a in fresh:
            score = a["relevance_score"]
            if score is not None and score < 5:
                rejected.append(a)
                logger.info("  [REJECT] rel=%-2s  score=%-3d  %s",
                            score, a["rank_score"], a["headline"][:70])
            else:
                passing.append(a)
                logger.info("  [PASS  ] rel=%-2s  score=%-3d  %s",
                            score if score is not None else "NULL",
                            a["rank_score"], a["headline"][:70])

        if rejected:
            mark_articles_rejected([a["id"] for a in rejected])
            logger.info("[Round %d] Marked %d articles as rejected in DB",
                        round_num + 1, len(rejected))

        verified.extend(passing)
        logger.info("[Round %d] Done: %d passed, %d rejected | total verified: %d/%d",
                    round_num + 1, len(passing), len(rejected), len(verified), needed)

    final = sorted(verified, key=lambda a: a["rank_score"], reverse=True)[:needed]

    logger.info("=== Step 2 Complete: %d stories selected ===", len(final))
    for i, a in enumerate(final, 1):
        logger.info("  [%d] rel=%-2s  score=%-3d  type=%-16s  %s",
                    i,
                    a["relevance_score"] if a["relevance_score"] is not None else "NULL",
                    a["rank_score"],
                    a["content_type"],
                    a["headline"][:70])

    return final


if __name__ == "__main__":
    stories = select_stories()
    if not stories:
        logger.error("No stories selected.")
    else:
        logger.info("Ready to generate video with %d stories.", len(stories))
