"""
Quick transition preview.
Renders: fake story 1 (2s) → diagonal wipe (1s) → fake story 2 (2s)
Output: storage/Videos/Raw/transition_test.mp4  (~5 seconds, renders in ~10s)

Run:
    venv\Scripts\python.exe test_transition.py
"""
from pathlib import Path
import numpy as np
from moviepy.editor import VideoClip, concatenate_videoclips

W, H, FPS = 1920, 1080, 24
TRANSITION_DUR = 1.0
STORY_DUR      = 2.0
WIPE_COLOR     = (200, 0, 0)
BAND           = 400
OUT_PATH       = Path("storage/Videos/Raw/transition_test.mp4")
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

# Story frames — two solid colors so you can clearly see the cut
def _story_clip(color: tuple, dur: float) -> VideoClip:
    frame = np.full((H, W, 3), color, dtype=np.uint8)
    return VideoClip(lambda t: frame, duration=dur)

# Diagonal wipe
def _wipe_clip(dur: float = TRANSITION_DUR) -> VideoClip:
    _y_g, _x_g = np.mgrid[0:H, 0:W]
    _total_d = W + H

    def _make_frame(t: float) -> np.ndarray:
        d_lead  = (t / dur) * (_total_d + BAND)
        d_trail = d_lead - BAND
        diag    = _x_g + _y_g
        frame   = np.zeros((H, W, 3), dtype=np.uint8)
        frame[(diag >= d_trail) & (diag <= d_lead)] = WIPE_COLOR
        return frame

    return VideoClip(_make_frame, duration=dur)


clips = [
    _story_clip((20, 40, 80),  STORY_DUR),   # dark blue  — story 1
    _wipe_clip(),
    _story_clip((20, 80, 40),  STORY_DUR),   # dark green — story 2
]

final = concatenate_videoclips(clips, method="compose")
print(f"Rendering {final.duration:.1f}s preview -> {OUT_PATH.name} ...")
final.write_videofile(
    str(OUT_PATH), fps=FPS, codec="libx264",
    audio=False, verbose=False, logger=None,
)
print(f"Done -> {OUT_PATH}")
