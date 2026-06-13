from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.render_dummy_two_news import render_dummy_two_news


class DummyTwoNewsRenderTest(unittest.TestCase):
    def test_render_creates_non_empty_mp4(self) -> None:
        output_name = "dummy_two_news_render_test"
        output_path = render_dummy_two_news(
            output_name=output_name,
            include_intro_outro=False,
        )

        try:
            self.assertTrue(output_path.exists(), f"Missing output file: {output_path}")
            self.assertGreater(output_path.stat().st_size, 0, "Rendered file is empty")
        finally:
            if output_path.exists():
                output_path.unlink()


if __name__ == "__main__":
    unittest.main()
