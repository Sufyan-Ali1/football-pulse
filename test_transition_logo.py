"""
Transition preview — matches the exact implementation in process/video_maker.py.

Old story (right side) freezes on its last frame.
New story (left side) shows its empty broadcast slate.
Logo + red stripes sweep diagonally from bottom-left -> top-right.

Output: storage/Videos/Raw/transition_logo.mp4
Run:    venv\Scripts\python.exe test_transition_logo.py
"""
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from moviepy.editor import VideoClip, AudioFileClip, concatenate_videoclips

W, H, FPS  = 1920, 1080, 24
SWEEP_DUR  = 3.2
STORY_DUR  = 2.0
LOGO_H     = 520
LOGO_PATH  = Path("config/images/logo.png")
SFX_PATH   = Path("config/audio/transition.mp3")
OUT_PATH   = Path("storage/Videos/Raw/transition_logo.mp4")
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)

STRIPES = [
    (  0,  90, (130,  0,  0), 1.00),
    ( 80,  55, (195,  0,  0), 1.00),
    (140,  22, (225, 25, 25), 1.00),
    (163,   6, (255, 90, 90), 1.00),
]
TILT = 0.55
PAD  = 600

# ── Logo ──────────────────────────────────────────────────────────────────────

def _load_logo(target_h: int) -> Image.Image | None:
    if not LOGO_PATH.exists():
        print(f"WARNING: logo not found at {LOGO_PATH}")
        return None
    logo  = Image.open(LOGO_PATH).convert("RGBA")
    scale = target_h / logo.height
    return logo.resize((int(logo.width * scale), target_h), Image.LANCZOS)

_LOGO = _load_logo(LOGO_H)
if _LOGO:
    print(f"Logo loaded: {_LOGO.size[0]}x{_LOGO.size[1]}px")

# ── Story placeholder frames ──────────────────────────────────────────────────
# Simulate a broadcast frame: dark background + ticker bar + headline text.

def _make_story_frame(bg_color: tuple, label: str) -> np.ndarray:
    img = Image.new("RGB", (W, H), bg_color)
    draw = ImageDraw.Draw(img)
    # Ticker bar at bottom
    draw.rectangle([(0, H - 60), (W, H)], fill=(180, 0, 0))
    draw.text((20, H - 48), f"  BREAKING NEWS  |  {label}  |  LIVE", fill=(255, 255, 255))
    # Headline area
    draw.rectangle([(60, 160), (900, 320)], fill=(20, 20, 40))
    draw.text((80, 180), label, fill=(255, 255, 255))
    return np.array(img)

_OLD_FRAME = _make_story_frame((15, 30, 60),  "Story 1: Man Utd confirm Carrick deal")
_NEW_FRAME = _make_story_frame((15, 50, 30),  "Story 2: Guardiola exits Man City")

def _story_clip(frame: np.ndarray, dur: float) -> VideoClip:
    return VideoClip(lambda t: frame, duration=dur)

# ── Wipe transition (identical logic to video_maker.py) ──────────────────────

def _logo_sweep_clip(
    old_get_frame,     # callable: t -> np.ndarray
    new_get_frame,     # callable: t -> np.ndarray
    old_start_t: float,
    dur: float = SWEEP_DUR,
) -> VideoClip:
    _y_g, _x_g = np.mgrid[0:H, 0:W]
    _diag = _x_g.astype(np.float32) - _y_g.astype(np.float32) * TILT
    lw = _LOGO.width  if _LOGO else 0
    lh = _LOGO.height if _LOGO else 0

    def _make_frame(t: float) -> np.ndarray:
        old_f = old_get_frame(old_start_t + t).astype(np.float32)
        new_f = new_get_frame(t).astype(np.float32)

        p  = t / dur
        cx = -PAD + p * (W + 2 * PAD)
        cy = H + PAD - p * (H + 2 * PAD)
        d_center = cx - cy * TILT

        left_mask = (_diag < d_center)[:, :, np.newaxis]
        canvas    = np.where(left_mask, new_f, old_f)

        for d_off, hw, color, opacity in STRIPES:
            dist = np.abs(_diag - (d_center + d_off))
            mask = (dist <= hw)[:, :, np.newaxis]
            col  = np.array(color, dtype=np.float32)
            canvas = np.where(mask, canvas * (1.0 - opacity) + col * opacity, canvas)

        out = canvas.clip(0, 255).astype(np.uint8)

        if _LOGO is None:
            return out

        px = int(cx) - lw // 2
        py = int(cy) - lh // 2
        fade = min(1.0, min(p, 1.0 - p) / 0.12)
        if fade <= 0.0:
            return out

        logo_rgba = _LOGO.copy()
        if fade < 1.0:
            r, g, b, a = logo_rgba.split()
            logo_rgba = Image.merge("RGBA", (r, g, b, a.point(lambda v: int(v * fade))))

        pil_out = Image.fromarray(out)
        sx0 = max(0, -px);        sy0 = max(0, -py)
        sx1 = min(lw, W - px);    sy1 = min(lh, H - py)
        dx  = max(0, px);         dy  = max(0, py)
        if sx1 > sx0 and sy1 > sy0:
            crop = logo_rgba.crop((sx0, sy0, sx1, sy1))
            pil_out.paste(crop, (dx, dy), crop)
        return np.array(pil_out)

    return VideoClip(_make_frame, duration=dur)

# ── Assemble and render ───────────────────────────────────────────────────────

old_clip = _story_clip(_OLD_FRAME, STORY_DUR)
new_clip = _story_clip(_NEW_FRAME, STORY_DUR)

clips = [
    old_clip,
    _logo_sweep_clip(old_clip.get_frame, new_clip.get_frame, old_start_t=STORY_DUR),
    new_clip.subclip(SWEEP_DUR),   # skip the part shown during wipe
]

final = concatenate_videoclips(clips, method="compose")

# Add transition SFX if available
if SFX_PATH.exists():
    sfx = AudioFileClip(str(SFX_PATH))
    if sfx.duration > SWEEP_DUR:
        sfx = sfx.subclip(0, SWEEP_DUR)
    final = final.set_audio(sfx.set_start(STORY_DUR))
    print(f"SFX loaded: {SFX_PATH.name}")
else:
    print(f"No SFX ({SFX_PATH} not found) — silent preview")

print(f"\nRendering {final.duration:.1f}s -> {OUT_PATH.name} ...")
final.write_videofile(
    str(OUT_PATH), fps=FPS, codec="libx264",
    audio=bool(SFX_PATH.exists()), audio_codec="aac",
    verbose=False, logger=None,
)
print(f"Done -> {OUT_PATH}")
