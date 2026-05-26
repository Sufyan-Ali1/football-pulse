"""
Transition preview — Option B: Multi-Stripe Sweep
4 brand-red stripes sweep left-to-right with staggered timing.
Output: storage/Videos/Raw/transition_stripes.mp4

Run: venv\Scripts\python.exe test_transition_stripes.py
"""
from pathlib import Path
import numpy as np
from moviepy.editor import VideoClip, concatenate_videoclips

W, H, FPS   = 1920, 1080, 24
SWEEP_DUR   = 1.0
STORY_DUR   = 2.0
WIPE_COLOR  = (200, 0, 0)      # brand red
N_STRIPES   = 4                # number of stripes
STRIPE_W    = 600              # width of each stripe in pixels
STAGGER     = 0.12             # seconds between each stripe's start
OUT_PATH    = Path("storage/Videos/Raw/transition_stripes.mp4")
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def _story_clip(color: tuple, dur: float) -> VideoClip:
    frame = np.full((H, W, 3), color, dtype=np.uint8)
    return VideoClip(lambda t: frame, duration=dur)


def _stripes_clip(dur: float = SWEEP_DUR) -> VideoClip:
    """
    N_STRIPES horizontal bands sweep left-to-right with STAGGER delay between each.
    Each band is H/N_STRIPES pixels tall and STRIPE_W pixels wide.
    """
    band_h    = H // N_STRIPES
    # Each stripe travels W + STRIPE_W pixels in (dur - stagger*(N-1)) seconds
    stripe_dur = dur - STAGGER * (N_STRIPES - 1)
    speed      = (W + STRIPE_W) / stripe_dur   # pixels per second

    # Row masks for each stripe
    row_masks = [
        (slice(i * band_h, (i + 1) * band_h if i < N_STRIPES - 1 else H), )
        for i in range(N_STRIPES)
    ]

    def _make_frame(t: float) -> np.ndarray:
        frame = np.zeros((H, W, 3), dtype=np.uint8)
        for i, (rows,) in enumerate(row_masks):
            t_start = i * STAGGER
            if t < t_start:
                continue
            elapsed  = t - t_start
            x_lead   = int(elapsed * speed) - STRIPE_W   # right edge of stripe
            x_trail  = x_lead + STRIPE_W                 # left edge moves right
            x0 = max(0, x_lead)
            x1 = min(W, x_trail)
            if x0 < x1:
                frame[rows, x0:x1] = WIPE_COLOR
        return frame

    return VideoClip(_make_frame, duration=dur)


clips = [
    _story_clip((20, 40, 80), STORY_DUR),
    _stripes_clip(),
    _story_clip((20, 80, 40), STORY_DUR),
]

final = concatenate_videoclips(clips, method="compose")
print(f"Rendering {final.duration:.1f}s stripes preview -> {OUT_PATH.name} ...")
final.write_videofile(
    str(OUT_PATH), fps=FPS, codec="libx264",
    audio=False, verbose=False, logger=None,
)
print(f"Done -> {OUT_PATH}")
