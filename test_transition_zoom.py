"""
Transition preview — Option D: Zoom Flash
Outgoing story zooms in + white flash, then new story zooms out to normal.
Output: storage/Videos/Raw/transition_zoom.mp4

Run: venv\Scripts\python.exe test_transition_zoom.py
"""
from pathlib import Path
import numpy as np
from moviepy.editor import VideoClip, concatenate_videoclips
from PIL import Image

W, H, FPS  = 1920, 1080, 24
ZOOM_DUR   = 0.7
STORY_DUR  = 2.0
OUT_PATH   = Path("storage/Videos/Raw/transition_zoom.mp4")
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

CX, CY = W // 2, H // 2   # zoom center


def _story_clip(color: tuple, dur: float) -> VideoClip:
    frame = np.full((H, W, 3), color, dtype=np.uint8)
    return VideoClip(lambda t: frame, duration=dur)


def _zoomed_frame(base_frame: np.ndarray, scale: float, flash: float) -> np.ndarray:
    """Scale base_frame around center, blend with white flash."""
    if scale <= 1.0:
        result = base_frame.copy()
    else:
        # Crop a smaller region from center and resize to full canvas
        crop_w = int(W / scale)
        crop_h = int(H / scale)
        x0 = max(0, CX - crop_w // 2)
        y0 = max(0, CY - crop_h // 2)
        x1 = min(W, x0 + crop_w)
        y1 = min(H, y0 + crop_h)
        crop = base_frame[y0:y1, x0:x1]
        pil  = Image.fromarray(crop).resize((W, H), Image.BILINEAR)
        result = np.array(pil)

    # Blend with white flash
    if flash > 0:
        white  = np.full((H, W, 3), 255, dtype=np.float32)
        result = (result.astype(np.float32) * (1 - flash) + white * flash).clip(0, 255).astype(np.uint8)
    return result


def _zoom_out_clip(color: tuple, dur: float = ZOOM_DUR) -> VideoClip:
    """Outgoing story: zoom in from scale=1 to scale=1.4 + white flash."""
    base = np.full((H, W, 3), color, dtype=np.uint8)

    def _make_frame(t: float) -> np.ndarray:
        p     = t / dur                          # 0 → 1
        scale = 1.0 + 0.4 * p                   # 1.0 → 1.4
        flash = p ** 0.5                         # 0 → 1 (brightens fast)
        return _zoomed_frame(base, scale, flash)

    return VideoClip(_make_frame, duration=dur)


def _zoom_in_clip(color: tuple, dur: float = ZOOM_DUR) -> VideoClip:
    """Incoming story: zoom out from scale=1.4 to scale=1 + flash fades."""
    base = np.full((H, W, 3), color, dtype=np.uint8)

    def _make_frame(t: float) -> np.ndarray:
        p     = t / dur                          # 0 → 1
        scale = 1.4 - 0.4 * p                   # 1.4 → 1.0
        flash = (1 - p) ** 0.5                  # 1 → 0 (fades fast)
        return _zoomed_frame(base, scale, flash)

    return VideoClip(_make_frame, duration=dur)


story1_color = (20, 40, 80)
story2_color = (20, 80, 40)

clips = [
    _story_clip(story1_color, STORY_DUR),
    _zoom_out_clip(story1_color),
    _zoom_in_clip(story2_color),
    _story_clip(story2_color, STORY_DUR),
]

final = concatenate_videoclips(clips, method="compose")
print(f"Rendering {final.duration:.1f}s zoom preview -> {OUT_PATH.name} ...")
final.write_videofile(
    str(OUT_PATH), fps=FPS, codec="libx264",
    audio=False, verbose=False, logger=None,
)
print(f"Done -> {OUT_PATH}")
