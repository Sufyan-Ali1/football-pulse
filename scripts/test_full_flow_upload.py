from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings
from core.types import VideoMetadata
from core.database import get_all_clips, row_to_news_item
from pipeline.collector import run_collector
from pipeline.daily_runner import _select_stories
from process.script_gen import generate_segment_script
from process.video_maker import create_multi_story_video
from process.voiceover import generate_voiceover
from publish.youtube import upload_video


def main() -> None:
    print("\n=== Full Flow Smoke Test START ===")
    print("1. Collecting live articles ...")
    run_collector()

    print("2. Selecting 2 stories ...")
    articles = _select_stories(max_age_hours=14)[:2]
    if len(articles) < 2:
        raise RuntimeError(f"Need at least 2 candidate stories, got {len(articles)}")

    clip_library = get_all_clips()
    stories = []
    for idx, article in enumerate(articles, start=1):
        item = row_to_news_item(article)
        print(f"   [{idx}/2] Script: {item.headline[:80]}")
        script = generate_segment_script(item, article["content_type"], clips=clip_library)

        print(f"   [{idx}/2] Voiceover ...")
        vo_path = generate_voiceover(script, "english")
        stories.append((script, item, vo_path))

    now = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_name = f"smoke_full_flow_{now}"

    print("3. Rendering 2-story test video ...")
    video_path = create_multi_story_video(
        stories,
        output_name=output_name,
        include_intro_outro=False,
    )

    title = f"TEST Upload | 2 Stories | {settings.BRAND_NAME} | {now}"[:95]
    description = (
        "Smoke test upload from live article collection through script, voiceover, "
        "render, and YouTube upload.\n\n"
        + "\n".join(f"- {row_to_news_item(a).headline}" for a in articles)
    )
    metadata = VideoMetadata(
        title=title,
        description=description,
        tags=["football", "test upload", settings.BRAND_NAME.lower()],
        privacy_status="private",
    )

    print("4. Uploading to YouTube ...")
    video_id = upload_video(video_path, None, metadata)

    print("\n=== Full Flow Smoke Test DONE ===")
    print(f"Video ID: {video_id}")
    print(f"Local file: {video_path}")


if __name__ == "__main__":
    main()
