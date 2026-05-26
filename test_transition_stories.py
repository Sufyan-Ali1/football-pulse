"""
Transition test with real news frames and voiceovers.

Renders exactly: [story 1 + voice] -> [wipe animation] -> [story 2 + voice]
No intro, no outro — just the two stories and the transition between them.

Output: storage/Videos/Raw/transition_stories_raw.mp4
Run:    venv\Scripts\python.exe test_transition_stories.py
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
from process.script_gen import generate_segment_script
from process.voiceover import generate_voiceover
from process.video_maker import create_multi_story_video


def main() -> None:
    # Pick articles
    articles = get_breaking_articles()
    if not articles:
        articles = get_pending_articles(limit=10)
    if not articles:
        logger.error("No articles in DB. Run: python main.py --once  first.")
        return

    # Take exactly 2
    selected = articles[:2]
    if len(selected) < 2:
        logger.error("Need at least 2 articles in DB.")
        return

    logger.info("Using articles:")
    for a in selected:
        logger.info("  - %s", a["headline"])

    # Build script + voiceover for each
    clip_library = get_all_clips()
    stories: list[tuple] = []
    for article in selected:
        item   = row_to_news_item(article)
        script = generate_segment_script(item, "breaking_news", clips=clip_library)
        logger.info("Script: %d words (~%.0fs) — %s", script.word_count, script.estimated_duration_seconds, item.headline[:60])
        vo_path = generate_voiceover(script, "english")
        stories.append((script, item, vo_path))

    # Render: 2 stories only, no intro/outro
    video_path = create_multi_story_video(
        stories,
        output_name="transition_stories",
        include_intro_outro=False,
    )

    size_mb = Path(video_path).stat().st_size / (1024 * 1024)
    logger.info("Done: %.1f MB -> %s", size_mb, video_path)


if __name__ == "__main__":
    main()
