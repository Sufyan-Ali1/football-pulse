from __future__ import annotations

import argparse
import sys
from datetime import datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.types import NewsItem, Script
from process.video_maker import create_multi_story_video


def _dummy_news_item(
    headline: str,
    body: str,
    source: str,
    minutes_ago: int,
) -> NewsItem:
    return NewsItem(
        id=NewsItem.make_id(headline),
        headline=headline,
        body=body,
        url="https://example.com/dummy-story",
        source=source,
        source_type="rss",
        timestamp=datetime.now() - timedelta(minutes=minutes_ago),
    )


def build_dummy_stories() -> list[tuple[Script, NewsItem, Path | None]]:
    item_one = _dummy_news_item(
        headline="Manchester United confirm summer defensive rebuild plans",
        body=(
            "Dummy story for render testing. The club is evaluating multiple "
            "centre-back options before pre-season."
        ),
        source="Sky Sports",
        minutes_ago=18,
    )
    script_one = Script(
        news_id=item_one.id,
        script_type="breaking_news",
        format="segment",
        text=(
            "Manchester United are pushing ahead with a summer defensive rebuild "
            "as internal planning accelerates."
        ),
        word_count=15,
        estimated_duration_seconds=10,
        selected_clip_ids=[],
        display_headline="Manchester United confirm summer defensive rebuild plans",
        display_points=[
            "Club priorities set before pre-season camp",
            "Recruitment team reviewing centre-back shortlist",
            "Final decisions expected during the next window phase",
        ],
        panel_label="TRANSFER LATEST",
    )

    item_two = _dummy_news_item(
        headline="Chelsea step up talks after midfielder injury setback",
        body=(
            "Dummy story for render testing. Recruitment activity is expected "
            "to increase after the latest injury concern."
        ),
        source="BBC Sport",
        minutes_ago=7,
    )
    script_two = Script(
        news_id=item_two.id,
        script_type="breaking_news",
        format="segment",
        text=(
            "Chelsea are stepping up talks in the market after a fresh "
            "midfield injury setback disrupted planning."
        ),
        word_count=17,
        estimated_duration_seconds=10,
        selected_clip_ids=[],
        display_headline="Chelsea step up talks after midfielder injury setback",
        display_points=[
            "Medical staff assessing the full timeline",
            "Shortlist updated to cover immediate depth",
            "Negotiations could move quickly if terms align",
        ],
        panel_label="BREAKING UPDATE",
    )

    return [
        (script_one, item_one, None),
        (script_two, item_two, None),
    ]


def render_dummy_two_news(
    output_name: str = "dummy_two_news_render",
    include_intro_outro: bool = False,
) -> Path:
    return create_multi_story_video(
        build_dummy_stories(),
        output_name=output_name,
        include_intro_outro=include_intro_outro,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Render a two-story dummy broadcast without calling any APIs."
    )
    parser.add_argument(
        "--output-name",
        default="dummy_two_news_render",
        help="Output filename without extension.",
    )
    parser.add_argument(
        "--with-intro-outro",
        action="store_true",
        help="Include intro/outro assets in the render.",
    )
    args = parser.parse_args()

    output_path = render_dummy_two_news(
        output_name=args.output_name,
        include_intro_outro=args.with_intro_outro,
    )
    print(output_path)


if __name__ == "__main__":
    main()
