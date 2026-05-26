"""
Resource loading with module-level caching.
Expensive operations (morphological mask, video decode) run once per unique path.
"""
import numpy as np
from PIL import Image, ImageFilter
from moviepy.editor import VideoFileClip

from . import constants as C

_BG_CACHE:    dict[str, VideoFileClip]              = {}
_FRAME_CACHE: dict[str, tuple[Image.Image, Image.Image]] = {}
_CLIP_CACHE:  dict[str, VideoFileClip]              = {}


def load_background(path: str) -> VideoFileClip:
    if path not in _BG_CACHE:
        _BG_CACHE[path] = VideoFileClip(path)
    return _BG_CACHE[path]


def load_frame_and_mask(path: str) -> tuple[Image.Image, Image.Image]:
    """Load frame PNG and compute the left-window clipping mask (cached)."""
    if path not in _FRAME_CACHE:
        frame       = Image.open(path).convert("RGBA")
        frame_alpha = np.array(frame)[:, :, 3]

        win_mask = np.zeros((C.H, C.W), dtype=np.uint8)
        win_mask[C.VID_Y1:C.VID_Y2, C.VID_X1:C.VID_X2] = 255
        win_mask = np.minimum(win_mask, 255 - frame_alpha)

        m = Image.fromarray(win_mask, mode="L")
        m = m.filter(ImageFilter.MinFilter(size=19))  # erode corner artifacts
        m = m.filter(ImageFilter.MaxFilter(size=19))  # dilate back
        _FRAME_CACHE[path] = (frame, m)

    return _FRAME_CACHE[path]


def load_video_clip(path: str) -> VideoFileClip:
    if path not in _CLIP_CACHE:
        _CLIP_CACHE[path] = VideoFileClip(path)
    return _CLIP_CACHE[path]
