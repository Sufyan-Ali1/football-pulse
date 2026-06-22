import base64
import io
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from config import settings
from core.types import NewsItem, Script
from publish.thumbnail import (
    _cover_resize,
    _extract_image_from_gemini_response,
    create_roundup_thumbnail,
)


def _sample_news_item() -> NewsItem:
    return NewsItem(
        id="news-2",
        headline="World Cup squad update sparks debate",
        body="A major squad selection discussion has taken over the World Cup build-up.",
        url="https://example.com/story-2",
        source="ESPN",
        source_type="rss",
        timestamp=datetime.utcnow(),
    )


def _sample_script() -> Script:
    return Script(
        news_id="news-2",
        script_type="breaking_news",
        format="segment",
        text="One of the biggest World Cup selection twists of the week is now official.",
        word_count=14,
        estimated_duration_seconds=9,
    )


class ThumbnailGenerationTests(unittest.TestCase):
    def test_extract_gemini_response_image(self) -> None:
        image = Image.new("RGB", (8, 4), (12, 100, 44))
        buf = io.BytesIO()
        image.save(buf, format="PNG")
        payload = {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {
                                "inlineData": {
                                    "mimeType": "image/png",
                                    "data": base64.b64encode(buf.getvalue()).decode("utf-8"),
                                }
                            }
                        ]
                    }
                }
            ]
        }

        extracted = _extract_image_from_gemini_response(payload)

        self.assertIsNotNone(extracted)
        self.assertEqual(extracted.size, (8, 4))

    def test_cover_resize_returns_canvas_size(self) -> None:
        source = Image.new("RGB", (1400, 800), (12, 100, 44))

        resized = _cover_resize(source, (1280, 720))

        self.assertEqual(resized.size, (1280, 720))

    def test_returns_none_without_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            original_enabled = settings.THUMBNAIL_ENABLED
            original_project = settings.GOOGLE_CLOUD_PROJECT
            original_dir = settings.THUMBNAILS_DIR
            try:
                settings.THUMBNAIL_ENABLED = True
                settings.GOOGLE_CLOUD_PROJECT = ""
                settings.THUMBNAILS_DIR = Path(tmpdir)

                with patch(
                    "publish.thumbnail._build_thumbnail_prompt_via_groq",
                    return_value="Create a Football Pulse thumbnail.",
                ):
                    output = create_roundup_thumbnail(
                        [_sample_news_item()],
                        [_sample_script()],
                        "vertex_no_project_test",
                        focus_mode="world_cup",
                    )

                self.assertIsNone(output)
            finally:
                settings.THUMBNAIL_ENABLED = original_enabled
                settings.GOOGLE_CLOUD_PROJECT = original_project
                settings.THUMBNAILS_DIR = original_dir

    def test_roundup_thumbnail_uses_generated_image_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            original_enabled = settings.THUMBNAIL_ENABLED
            original_dir = settings.THUMBNAILS_DIR
            original_project = settings.GOOGLE_CLOUD_PROJECT
            try:
                settings.THUMBNAIL_ENABLED = True
                settings.THUMBNAILS_DIR = Path(tmpdir)
                settings.GOOGLE_CLOUD_PROJECT = "demo-project"

                generated_image = Image.new("RGB", (1400, 800), (12, 100, 44))

                with patch(
                    "publish.thumbnail._build_thumbnail_prompt_via_groq",
                    return_value="Complete thumbnail prompt.",
                ), patch(
                    "publish.thumbnail._generate_gemini_image",
                    return_value=generated_image,
                ):
                    output = create_roundup_thumbnail(
                        [_sample_news_item()],
                        [_sample_script()],
                        "planned_thumb_test",
                        focus_mode="world_cup",
                    )

                self.assertIsNotNone(output)
                assert output is not None
                self.assertTrue(output.exists())
                self.assertEqual(output.suffix.lower(), ".png")

                with Image.open(output) as generated:
                    self.assertEqual(generated.size, (1280, 720))
            finally:
                settings.THUMBNAIL_ENABLED = original_enabled
                settings.THUMBNAILS_DIR = original_dir
                settings.GOOGLE_CLOUD_PROJECT = original_project

    def test_roundup_thumbnail_returns_none_when_generation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            original_enabled = settings.THUMBNAIL_ENABLED
            original_dir = settings.THUMBNAILS_DIR
            original_project = settings.GOOGLE_CLOUD_PROJECT
            try:
                settings.THUMBNAIL_ENABLED = True
                settings.THUMBNAILS_DIR = Path(tmpdir)
                settings.GOOGLE_CLOUD_PROJECT = "demo-project"

                with patch(
                    "publish.thumbnail._build_thumbnail_prompt_via_groq",
                    return_value="Create a premium Football Pulse World Cup thumbnail.",
                ), patch("publish.thumbnail._generate_gemini_image", return_value=None):
                    output = create_roundup_thumbnail(
                        [_sample_news_item()],
                        [_sample_script()],
                        "prompt_thumb_test",
                        focus_mode="world_cup",
                    )

                self.assertIsNone(output)
            finally:
                settings.THUMBNAIL_ENABLED = original_enabled
                settings.THUMBNAILS_DIR = original_dir
                settings.GOOGLE_CLOUD_PROJECT = original_project


if __name__ == "__main__":
    unittest.main()
