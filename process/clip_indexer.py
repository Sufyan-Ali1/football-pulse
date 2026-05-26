"""
Clip indexer — runs after every Pexels download.

Extracts a frame from the middle of the video, sends it to
Groq vision for a plain-text description, and saves the result
to the video_clips DB table so future stories can reuse it
without hitting the Pexels API again.
"""
import logging
from pathlib import Path

import numpy as np
from PIL import Image

from clients.groq_vision import describe_frame
from core.database import clip_exists, insert_video_clip

logger = logging.getLogger(__name__)


def index_clip(
    video_path: Path,
    source_url: str | None = None,
    width: int | None = None,
    height: int | None = None,
) -> bool:
    """Describe and register a downloaded clip in the DB.

    Returns True if newly indexed, False if already exists or failed.
    """
    path_str = str(video_path)

    if clip_exists(path_str):
        logger.debug("Already indexed: %s", video_path.name)
        return False

    frames, duration = _load_clip_info(video_path)
    if not frames:
        logger.warning("Frame extraction failed — skipping index for %s", video_path.name)
        return False

    print(f"    [Indexer] Describing {video_path.name} ...")
    desc, kws = describe_frame(frames)

    if not desc:
        desc = video_path.stem
        logger.warning("Vision returned empty description — using filename as fallback")

    insert_video_clip(
        file_path=path_str,
        description=desc,
        keywords=kws,
        source="pexels",
        source_url=source_url,
        duration=duration,
        width=width,
        height=height,
    )
    print(f"    [Indexer] Saved: {desc!r}  |  keywords: {kws!r}")
    logger.info("Indexed: %s", video_path.name)
    return True


def _load_clip_info(video_path: Path) -> tuple[list[Image.Image] | None, float | None]:
    """Extract frames at 25%, 50%, and 75% of the clip duration."""
    try:
        from moviepy.editor import VideoFileClip
        clip = VideoFileClip(str(video_path))
        duration = clip.duration
        frames = [
            Image.fromarray(clip.get_frame(duration * t).astype(np.uint8))
            for t in (0.25, 0.50, 0.75)
        ]
        clip.close()
        return frames, duration
    except Exception as exc:
        logger.warning("Could not load clip %s: %s", video_path.name, exc)
        return None, None
