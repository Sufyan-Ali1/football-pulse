"""
Transition preview — Option C: Flash Burst
A bright white flash blooms from the center and fades over ~0.5s.
Output: storage/Videos/Raw/transition_flash.mp4

Run: venv\Scripts\python.exe test_transition_flash.py
"""
from pathlib import Path
import numpy as np
from moviepy.editor import VideoClip, concatenate_videoclips

W, H, FPS  = 1920, 1080, 24
FLASH_DUR  = 0.5
STORY_DUR  = 2.0
OUT_PATH   = Path("storage/Videos/Raw/transition_flash.mp4")
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def _story_clip(color: tuple, dur: float) -> VideoClip:
    frame = np.full((H, W, 3), color, dtype=np.uint8)
    return VideoClip(lambda t: frame, duration=dur)


def _flash_clip(dur: float = FLASH_DUR) -> VideoClip:
    """
    Brightness peaks instantly at t=0 then decays exponentially.
    Creates a camera-flash / lens-flare feel.
    """
    def _make_frame(t: float) -> np.ndarray:
        # Decay curve: starts at 1.0, drops fast
        brightness = max(0.0, 1.0 - (t / dur) ** 0.4)
        value = int(255 * brightness)
        return np.full((H, W, 3), value, dtype=np.uint8)

    return VideoClip(_make_frame, duration=dur)


clips = [
    _story_clip((20, 40, 80), STORY_DUR),
    _flash_clip(),
    _story_clip((20, 80, 40), STORY_DUR),
]

final = concatenate_videoclips(clips, method="compose")
print(f"Rendering {final.duration:.1f}s flash preview -> {OUT_PATH.name} ...")
final.write_videofile(
    str(OUT_PATH), fps=FPS, codec="libx264",
    audio=False, verbose=False, logger=None,
)
print(f"Done -> {OUT_PATH}")
