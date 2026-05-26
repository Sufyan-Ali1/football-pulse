"""
End-to-end breaking news test.

Picks the top breaking/pending articles from DB, runs Groq 2nd-pass
verification, generates scripts + ElevenLabs voiceovers, then stitches
them into one multi-story video with intro and outro.

Usage:
    python run_breaking_test.py
"""
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

from core.database import get_breaking_articles, get_pending_articles, get_all_clips, row_to_news_item
from process.verifier import verify_and_reclassify
from process.script_gen import generate_segment_script
from process.voiceover import generate_voiceover
from process.video_maker import create_multi_story_video

_MAX_STORIES = 3   # how many stories to include in the video


def main() -> None:
    # 1 -- Pick articles: prefer breaking queue, fall back to top pending
    articles = get_breaking_articles()
    source   = "breaking queue"
    if not articles:
        articles = get_pending_articles(limit=10)
        source   = "pending pool"

    if not articles:
        logger.error("No articles in DB. Run: python main.py --once  first.")
        return

    logger.info("Found %d articles in %s", len(articles), source)

    # 2 -- Groq 2nd-pass verification on top candidates
    candidates = articles[:5]
    logger.info("Running 2nd-pass Groq verification on %d articles ...", len(candidates))
    verified = verify_and_reclassify(candidates)

    selected = verified[:_MAX_STORIES]
    if not selected:
        logger.error("No articles passed verification.")
        return

    logger.info("Selected %d articles for multi-story video", len(selected))

    # 3 -- Generate script + voiceover for each article
    clip_library = get_all_clips()
    stories: list[tuple] = []
    for article in selected:
        item = row_to_news_item(article)

        logger.info("Script for: %s", article["headline"])
        script = generate_segment_script(item, "breaking_news", clips=clip_library)
        logger.info(
            "  %d words (~%.0fs)",
            script.word_count,
            script.estimated_duration_seconds,
        )

        logger.info("Voiceover for: %s", article["headline"])
        vo_path = generate_voiceover(script, "english")

        stories.append((script, item, vo_path))

    # 4 -- Stitch into one multi-story video (intro + stories + outro)
    logger.info("Generating multi-story video (%d stories) ...", len(stories))
    video_path = create_multi_story_video(stories, output_name="breaking_test")

    size_mb = Path(video_path).stat().st_size / (1024 * 1024)
    logger.info("=== DONE === %.1f MB -> %s", size_mb, video_path)


if __name__ == "__main__":
    main()
