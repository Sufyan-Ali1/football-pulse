import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from PIL import Image

from config import settings
from core.types import NewsItem, Script
from publish.thumbnail import (
    _build_google_image_payload,
    _extract_image_bytes,
    create_roundup_thumbnail,
    create_test_thumbnail_from_prompt,
)


class ThumbnailGenerationTests(unittest.TestCase):
    def test_imagen_payload_uses_predict_shape(self) -> None:
        payload = _build_google_image_payload("test prompt")
        self.assertIn("instances", payload)
        self.assertIn("parameters", payload)
        self.assertNotIn("contents", payload)

    def test_imagen_response_bytes_extraction(self) -> None:
        data = {"predictions": [{"bytesBase64Encoded": "aGVsbG8="}]}
        self.assertEqual(_extract_image_bytes(data), b"hello")

    def test_returns_none_without_project(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            original_enabled = settings.THUMBNAIL_ENABLED
            original_project = settings.GOOGLE_CLOUD_PROJECT
            original_dir = settings.THUMBNAILS_DIR
            try:
                settings.THUMBNAIL_ENABLED = True
                settings.GOOGLE_CLOUD_PROJECT = ""
                settings.THUMBNAILS_DIR = Path(tmpdir)
                output = create_test_thumbnail_from_prompt(
                    prompt="Create a Football Pulse thumbnail.",
                    output_stem="vertex_no_project_test",
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

                item = NewsItem(
                    id="news-2",
                    headline="World Cup squad update sparks debate",
                    body="A major squad selection discussion has taken over the World Cup build-up.",
                    url="https://example.com/story-2",
                    source="ESPN",
                    source_type="rss",
                    timestamp=datetime.utcnow(),
                )
                script = Script(
                    news_id="news-2",
                    script_type="breaking_news",
                    format="segment",
                    text="One of the biggest World Cup selection twists of the week is now official.",
                    word_count=14,
                    estimated_duration_seconds=9,
                )

                generated_dir = Path(tmpdir) / "generated"
                generated_dir.mkdir(parents=True, exist_ok=True)
                generated_path = generated_dir / "candidate.png"
                Image.new("RGB", (1400, 800), (12, 100, 44)).save(generated_path, format="PNG")

                with patch(
                    "publish.thumbnail._build_thumbnail_plan",
                    return_value={"image_prompt": "Complete thumbnail prompt."},
                ), patch(
                    "publish.thumbnail._generate_vertex_imagen_image",
                    return_value=generated_path,
                ):
                    output = create_roundup_thumbnail([item], [script], "planned_thumb_test", focus_mode="world_cup")

                self.assertIsNotNone(output)
                self.assertTrue(output.exists())
                self.assertEqual(output.suffix.lower(), ".png")

                with Image.open(output) as generated:
                    self.assertEqual(generated.size, (1280, 720))
            finally:
                settings.THUMBNAIL_ENABLED = original_enabled
                settings.THUMBNAILS_DIR = original_dir
                settings.GOOGLE_CLOUD_PROJECT = original_project

    def test_prompt_thumbnail_returns_none_when_generation_fails(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            original_enabled = settings.THUMBNAIL_ENABLED
            original_dir = settings.THUMBNAILS_DIR
            original_project = settings.GOOGLE_CLOUD_PROJECT
            try:
                settings.THUMBNAIL_ENABLED = True
                settings.THUMBNAILS_DIR = Path(tmpdir)
                settings.GOOGLE_CLOUD_PROJECT = "demo-project"

                with patch("publish.thumbnail._generate_vertex_imagen_image", return_value=None):
                    output = create_test_thumbnail_from_prompt(
                        prompt="Create a premium Football Pulse World Cup thumbnail.",
                        output_stem="prompt_thumb_test",
                    )

                self.assertIsNone(output)
            finally:
                settings.THUMBNAIL_ENABLED = original_enabled
                settings.THUMBNAILS_DIR = original_dir
                settings.GOOGLE_CLOUD_PROJECT = original_project


if __name__ == "__main__":
    unittest.main()
