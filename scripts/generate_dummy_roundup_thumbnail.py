"""
Generate a dummy 5-story roundup thumbnail through the full thumbnail pipeline.

Usage:
    venv\Scripts\python scripts\generate_dummy_roundup_thumbnail.py
"""
from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.types import NewsItem, Script
from publish.thumbnail import create_roundup_thumbnail


def _dummy_story(idx: int, headline: str, body: str, script_text: str) -> tuple[NewsItem, Script]:
    item = NewsItem(
        id=f"dummy-news-{idx}",
        headline=headline,
        body=body,
        url=f"https://example.com/dummy-{idx}",
        source="Football Pulse",
        source_type="rss",
        timestamp=datetime.now(timezone.utc),
    )
    script = Script(
        news_id=item.id,
        script_type="breaking_news",
        format="segment",
        text=script_text,
        word_count=len(script_text.split()),
        estimated_duration_seconds=12,
    )
    return item, script


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    stories = [
        _dummy_story(
            1,
            "Mbappe World Cup injury update sparks major France concern",
            "France face a nervous wait after a major injury concern around Kylian Mbappe ahead of a key World Cup fixture.",
            "France are sweating over Kylian Mbappe after a fresh injury concern ahead of a huge World Cup match.",
        ),
        _dummy_story(
            2,
            "Brazil final squad call creates huge reaction before World Cup clash",
            "Brazil's final squad decision has created debate after a surprise inclusion and one notable omission.",
            "Brazil have made a major squad call and fans are split over the final World Cup selection.",
        ),
        _dummy_story(
            3,
            "Argentina get massive boost as star returns to training before showdown",
            "Argentina have received a timely boost with a major player returning to full training before a decisive fixture.",
            "Argentina may have just received the boost they needed with a star player back in full training.",
        ),
        _dummy_story(
            4,
            "England coach faces pressure after shock tactical hint before quarter-final",
            "England's latest tactical direction has raised questions before a high-stakes World Cup quarter-final.",
            "A surprise tactical hint from England's coach has completely changed the mood before the quarter-final.",
        ),
        _dummy_story(
            5,
            "Portugal vs Spain rivalry set for explosive World Cup night",
            "A blockbuster rivalry match between Portugal and Spain is building major tension with stars on both sides.",
            "Portugal against Spain now has all the ingredients for a massive World Cup headline moment.",
        ),
    ]

    items = [item for item, _ in stories]
    scripts = [script for _, script in stories]
    output = create_roundup_thumbnail(
        items,
        scripts,
        output_stem="dummy_roundup_thumbnail",
        focus_mode="world_cup",
    )
    if not output:
        print("Dummy roundup thumbnail generation failed.")
        return 1

    print(f"Dummy roundup thumbnail generated: {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
