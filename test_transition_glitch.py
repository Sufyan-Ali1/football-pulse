"""
Transition preview — Option A: Glitch Effect
RGB channels split apart then snap back over ~0.6s.
Output: storage/Videos/Raw/transition_glitch.mp4

Run: venv\Scripts\python.exe test_transition_glitch.py
"""
from pathlib import Path
import numpy as np
from moviepy.editor import VideoClip, concatenate_videoclips

W, H, FPS = 1920, 1080, 24
GLITCH_DUR = 0.6
STORY_DUR  = 2.0
OUT_PATH   = Path("storage/Videos/Raw/transition_glitch.mp4")
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def _story_clip(color: tuple, dur: float) -> VideoClip:
    frame = np.full((H, W, 3), color, dtype=np.uint8)
    return VideoClip(lambda t: frame, duration=dur)


def _glitch_clip(dur: float = GLITCH_DUR) -> VideoClip:
    """
    RGB channel split — red shifts left, blue shifts right, green stays.
    Shift amount grows then shrinks (ping-pong), giving a glitch snap effect.
    """
    def _make_frame(t: float) -> np.ndarray:
        # Progress: 0→1→0 (peaks at midpoint)
        progress = 1.0 - abs((t / dur) * 2 - 1)
        max_shift = int(80 * progress)   # max 80px channel offset at peak

        frame = np.zeros((H, W, 3), dtype=np.uint8)

        # Red channel — shift left
        if max_shift > 0:
            frame[:, max_shift:, 0] = 200   # red fills shifted region
        else:
            frame[:, :, 0] = 200

        # Green channel — center (white-ish base)
        frame[:, :, 1] = 200

        # Blue channel — shift right
        if max_shift > 0:
            frame[:, :W - max_shift, 2] = 200
        else:
            frame[:, :, 2] = 200

        # Add scanline noise at peak
        if progress > 0.4:
            noise_rows = np.random.choice(H, size=int(H * 0.08 * progress), replace=False)
            shift = np.random.randint(-max_shift, max_shift + 1, size=len(noise_rows))
            for row, s in zip(noise_rows, shift):
                if s > 0:
                    frame[row, s:, :] = frame[row, :W - s, :]
                elif s < 0:
                    frame[row, :W + s, :] = frame[row, -s:, :]

        return frame

    return VideoClip(_make_frame, duration=dur)


clips = [
    _story_clip((20, 40, 80), STORY_DUR),
    _glitch_clip(),
    _story_clip((20, 80, 40), STORY_DUR),
]

final = concatenate_videoclips(clips, method="compose")
print(f"Rendering {final.duration:.1f}s glitch preview -> {OUT_PATH.name} ...")
final.write_videofile(
    str(OUT_PATH), fps=FPS, codec="libx264",
    audio=False, verbose=False, logger=None,
)
print(f"Done -> {OUT_PATH}")
