"""Generate a post-match video for one exact fixture ID.

Usage:
    python scripts/generate_post_match.py --fixture-id 123456
    python scripts/generate_post_match.py --fixture-id 123456 --force
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pipeline.post_match_runner import generate_post_match_video_for_fixture


def _configure_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a post-match video for one fixture ID.")
    parser.add_argument("--fixture-id", type=int, required=True, help="API-Football fixture ID")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Bypass settle-window and existing done-status checks",
    )
    args = parser.parse_args()

    _configure_logging()

    try:
        generated = generate_post_match_video_for_fixture(args.fixture_id, force=args.force)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}")
        return 1

    if generated:
        print(f"Post-match video processed for fixture {args.fixture_id}")
    else:
        print(f"No video generated for fixture {args.fixture_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
