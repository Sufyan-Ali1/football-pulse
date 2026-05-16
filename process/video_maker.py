"""
Animated broadcast-style news video generator — Step 6.

Layout (Sky Sports / BBC Sport style):
  ┌────────────────────────────────────────────────────────┐
  │ [accent bar] FOOTBALL CREDO HUB        ● LIVE  date   │  header
  │════════════════════════════════════════════════════════│  accent line
  │                                                        │
  │  [■ BREAKING]                                         │  badge slides in
  │                                                        │
  │  Manchester United Sign Striker                        │  headline
  │  in £80m Deal — Here We Go                            │  (staggered slide-in)
  │                                                        │
  │  ─────────────────────────────────                    │  divider
  │  Source: Sky Sports Football                           │  source fades in
  │                                                        │
  │════════════════════════════════════════════════════════│
  │[● BREAKING][ Man Utd sign £80m striker... →→→ ]       │  scrolling ticker
  └────────────────────────────────────────────────────────┘

Animations (all driven by time t):
  0.00 – 0.40s  Left accent bar grows top→bottom
  0.00 – 0.35s  Header bar slides down from top
  0.30 – 0.65s  BREAKING badge scales in (subtle pulse after)
  0.55 – 1.20s  Headline lines stagger slide-in from left
  1.20 – 1.60s  Divider line draws left→right
  1.30 – 1.70s  Source text fades in
  0.00 – end    News ticker scrolls left continuously
  0.30 – end    LIVE dot pulses

No ImageMagick. No external API. Requires: moviepy, numpy, Pillow.
"""
import logging
import math
import platform
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from config import settings
from core.constants import BADGE_LABELS
from core.types import NewsItem, Script

logger = logging.getLogger(__name__)

_LANDSCAPE = (1920, 1080)
_VERTICAL  = (1080, 1920)
_FPS       = 24


# ── Utilities ─────────────────────────────────────────────────────────────────

def _hex_to_rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _clamp(val: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, val))


def _ease_out(t: float) -> float:
    """Cubic ease-out: fast start, slow finish."""
    return 1 - (1 - t) ** 3


def _get_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    candidates: list[Path] = []
    if platform.system() == "Windows":
        fonts = Path("C:/Windows/Fonts")
        if bold:
            candidates += [fonts / "arialbd.ttf", fonts / "calibrib.ttf"]
        candidates += [fonts / "arial.ttf", fonts / "calibri.ttf"]
    deja = Path("/usr/share/fonts/truetype/dejavu")
    if bold:
        candidates.append(deja / "DejaVuSans-Bold.ttf")
    candidates += [deja / "DejaVuSans.ttf", Path("DejaVuSans.ttf")]
    for path in candidates:
        try:
            return ImageFont.truetype(str(path), size)
        except (OSError, IOError):
            continue
    return ImageFont.load_default()


def _wrap_text(text: str, max_chars: int) -> list[str]:
    words = text.split()
    lines, current = [], ""
    for word in words:
        candidate = (current + " " + word).strip()
        if len(candidate) <= max_chars:
            current = candidate
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def _draw_rounded_rect(
    draw: ImageDraw.ImageDraw,
    xy: tuple[int, int, int, int],
    radius: int,
    fill: tuple,
) -> None:
    x1, y1, x2, y2 = xy
    draw.rectangle([x1 + radius, y1, x2 - radius, y2], fill=fill)
    draw.rectangle([x1, y1 + radius, x2, y2 - radius], fill=fill)
    draw.ellipse([x1, y1, x1 + radius * 2, y1 + radius * 2], fill=fill)
    draw.ellipse([x2 - radius * 2, y1, x2, y1 + radius * 2], fill=fill)
    draw.ellipse([x1, y2 - radius * 2, x1 + radius * 2, y2], fill=fill)
    draw.ellipse([x2 - radius * 2, y2 - radius * 2, x2, y2], fill=fill)


def _get_club_colour(item: NewsItem) -> str:
    text = (item.headline + " " + item.body[:200]).lower()
    for club, colour in settings.CLUB_COLOURS.items():
        if club != "default" and club in text:
            return colour
    return settings.CLUB_COLOURS["default"]


# ── Frame factory ─────────────────────────────────────────────────────────────

def _make_frame_func(
    item: NewsItem,
    script: Script,
    size: tuple[int, int],
    ticker_text: str,
):
    """
    Returns make_frame(t) -> np.ndarray.
    MoviePy calls this for every frame; all animation is driven by t.
    """
    w, h        = size
    is_vertical = w < h
    scale       = w / 1920

    # Colours
    club_hex   = _get_club_colour(item)
    accent_rgb = _hex_to_rgb(club_hex)
    bg_rgb     = (11, 11, 18)       # deep navy-black
    header_bg  = (18, 18, 30)

    # Fonts
    font_brand    = _get_font(int(26 * scale), bold=True)
    font_date     = _get_font(int(21 * scale))
    font_badge    = _get_font(int(27 * scale), bold=True)
    font_headline = _get_font(int(70 * scale), bold=True)
    font_source   = _get_font(int(26 * scale))
    font_ticker   = _get_font(int(27 * scale))
    font_live     = _get_font(int(22 * scale), bold=True)

    # Layout constants
    margin      = int(80 * scale)
    accent_bar  = int(6 * scale)          # left vertical bar width
    content_x   = margin + accent_bar + int(20 * scale)
    header_h    = int(68 * scale)
    ticker_h    = int(58 * scale)
    ticker_y    = h - ticker_h
    ticker_label_w = int(220 * scale)
    ticker_speed   = int(170 * scale)     # pixels per second

    badge_text      = BADGE_LABELS.get(script.script_type, "NEWS")
    badge_y         = header_h + int(70 * scale)
    max_chars       = 26 if is_vertical else 36
    headline_lines  = _wrap_text(item.headline, max_chars)[:3]
    line_h          = int(86 * scale)
    headline_y      = badge_y + int(65 * scale)
    divider_y       = headline_y + len(headline_lines) * line_h + int(20 * scale)
    source_y        = divider_y + int(22 * scale)

    now_str = datetime.now().strftime("%d %b %Y  %H:%M")

    # Pre-measure ticker text width for seamless loop
    _tmp = Image.new("RGB", (10, 10))
    _d   = ImageDraw.Draw(_tmp)
    _tb  = _d.textbbox((0, 0), ticker_text, font=font_ticker)
    ticker_text_w = max(1, _tb[2] - _tb[0] + int(80 * scale))

    def make_frame(t: float) -> np.ndarray:
        img  = Image.new("RGB", (w, h), color=bg_rgb)
        draw = ImageDraw.Draw(img)

        # ── Subtle accent glow in top-left corner ─────────────────────────────
        for r in range(int(500 * scale), 0, int(-25 * scale)):
            brightness = int(18 * (1 - r / (500 * scale)))
            ar, ag, ab = accent_rgb
            glow_col = (
                min(255, bg_rgb[0] + int(ar * brightness / 255)),
                min(255, bg_rgb[1] + int(ag * brightness / 255)),
                min(255, bg_rgb[2] + int(ab * brightness / 255)),
            )
            draw.ellipse(
                [-r // 2, -r // 2, r // 2, r // 2],
                fill=glow_col,
            )

        # ── Left accent bar (grows downward 0 → 0.40s) ───────────────────────
        bar_prog = _clamp(t / 0.40)
        if bar_prog > 0:
            bar_max_h = ticker_y
            draw.rectangle(
                [(0, 0), (accent_bar, int(bar_max_h * _ease_out(bar_prog)))],
                fill=accent_rgb,
            )

        # ── Header (slides down from top 0 → 0.35s) ──────────────────────────
        hdr_prog   = _clamp(t / 0.35)
        hdr_offset = int(header_h * (1 - _ease_out(hdr_prog)))
        hdr_top    = -hdr_offset
        hdr_bot    = header_h - hdr_offset

        draw.rectangle([(0, hdr_top), (w, hdr_bot)], fill=header_bg)
        # Bottom accent line on header
        draw.rectangle([(0, hdr_bot), (w, hdr_bot + int(3 * scale))], fill=accent_rgb)

        # Brand name in header
        brand_y = hdr_top + (header_h - int(28 * scale)) // 2
        draw.text(
            (content_x, brand_y),
            settings.BRAND_NAME.upper(),
            fill=accent_rgb,
            font=font_brand,
        )

        # Date top-right
        draw.text(
            (w - margin, brand_y),
            now_str,
            fill=(150, 150, 165),
            font=font_date,
            anchor="ra",
        )

        # ── LIVE dot (pulses, appears after 0.30s) ────────────────────────────
        if t > 0.30:
            pulse = 0.55 + 0.45 * abs(math.sin(t * math.pi * 1.8))
            live_r = int(pulse * 255)
            dot_r  = int(7 * scale)
            dot_cx = w - margin - int(100 * scale)
            dot_cy = hdr_top + header_h // 2
            draw.ellipse(
                [(dot_cx - dot_r, dot_cy - dot_r), (dot_cx + dot_r, dot_cy + dot_r)],
                fill=(live_r, 40, 40),
            )
            draw.text(
                (dot_cx + dot_r + int(7 * scale), dot_cy - int(11 * scale)),
                "LIVE",
                fill=(live_r, 60, 60),
                font=font_live,
            )

        # ── Content-type badge (scales in 0.30 → 0.65s, then pulses) ─────────
        badge_prog = _clamp((t - 0.30) / 0.35)
        if badge_prog > 0:
            scale_factor = (
                _ease_out(badge_prog)
                if badge_prog < 1.0
                else 1.0 + 0.012 * math.sin(t * 5.0)
            )
            pad   = int(14 * scale)
            bb    = draw.textbbox((0, 0), badge_text, font=font_badge)
            b_w   = int((bb[2] - bb[0] + pad * 2) * scale_factor)
            b_h   = int((bb[3] - bb[1] + pad) * scale_factor)
            _draw_rounded_rect(
                draw,
                (content_x, badge_y, content_x + b_w, badge_y + b_h),
                radius=int(4 * scale),
                fill=accent_rgb,
            )
            draw.text(
                (content_x + int(pad * scale_factor), badge_y + int(pad / 2 * scale_factor)),
                badge_text,
                fill=(255, 255, 255),
                font=font_badge,
            )

        # ── Headline lines (staggered slide-in from left) ─────────────────────
        for i, line in enumerate(headline_lines):
            start = 0.55 + i * 0.14
            prog  = _clamp((t - start) / 0.38)
            if prog > 0:
                slide_x = int((1 - _ease_out(prog)) * -220 * scale)
                y = headline_y + i * line_h
                x = content_x + slide_x
                # Drop shadow
                draw.text(
                    (x + int(3 * scale), y + int(3 * scale)),
                    line,
                    fill=(0, 0, 0),
                    font=font_headline,
                )
                draw.text((x, y), line, fill=(255, 255, 255), font=font_headline)

        # ── Divider line (draws left → right 1.20 → 1.55s) ───────────────────
        div_prog = _clamp((t - 1.20) / 0.35)
        if div_prog > 0:
            max_div_w = w - content_x - margin
            draw.rectangle(
                [
                    (content_x, divider_y),
                    (content_x + int(max_div_w * _ease_out(div_prog)), divider_y + int(2 * scale)),
                ],
                fill=accent_rgb,
            )

        # ── Source text (fades in 1.30 → 1.70s) ──────────────────────────────
        src_prog = _clamp((t - 1.30) / 0.40)
        if src_prog > 0:
            v = int(160 * src_prog)
            draw.text(
                (content_x, source_y),
                f"Source: {item.source}",
                fill=(v, v, int(v * 1.05)),
                font=font_source,
            )

        # ── Bottom ticker ─────────────────────────────────────────────────────
        # Background panel
        draw.rectangle([(0, ticker_y), (w, h)], fill=(8, 8, 16))
        # Top separator line
        draw.rectangle(
            [(0, ticker_y), (w, ticker_y + int(2 * scale))],
            fill=accent_rgb,
        )

        # Draw scrolling text FIRST (behind label box)
        scroll_offset = int((ticker_speed * t) % ticker_text_w)
        text_y_ticker = ticker_y + (ticker_h - int(28 * scale)) // 2
        for rep in range(3):  # draw three copies for seamless loop
            tx = ticker_label_w + int(20 * scale) - scroll_offset + rep * ticker_text_w
            if -ticker_text_w < tx < w:
                draw.text(
                    (tx, text_y_ticker),
                    ticker_text,
                    fill=(210, 210, 225),
                    font=font_ticker,
                )

        # Label box on top (covers any text bleeding into it)
        draw.rectangle(
            [(0, ticker_y + int(2 * scale)), (ticker_label_w, h)],
            fill=accent_rgb,
        )
        lbl = "● BREAKING"
        lb  = draw.textbbox((0, 0), lbl, font=font_badge)
        lw  = lb[2] - lb[0]
        draw.text(
            ((ticker_label_w - lw) // 2, ticker_y + (ticker_h - (lb[3] - lb[1])) // 2),
            lbl,
            fill=(255, 255, 255),
            font=font_badge,
        )

        return np.array(img)

    return make_frame


# ── Public API ────────────────────────────────────────────────────────────────

def create_video(
    script: Script,
    voiceover_path: Path | None = None,
    item: NewsItem | None = None,
) -> Path:
    """
    Create an animated broadcast-style news video.

    Args:
        script:         Script dataclass (text, type, format).
        voiceover_path: Path to ElevenLabs MP3 (optional; uses estimated duration if missing).
        item:           NewsItem for headline + branding (optional; falls back to script text).

    Returns:
        Path to the MP4 in storage/Videos/Raw/.
    """
    from moviepy.editor import AudioFileClip, VideoClip

    output_path = settings.VIDEOS_RAW_DIR / f"{script.news_id}_{script.format}_raw.mp4"

    if output_path.exists():
        logger.info("Video already exists, skipping: %s", output_path.name)
        return output_path

    settings.VIDEOS_RAW_DIR.mkdir(parents=True, exist_ok=True)

    if item is None:
        from datetime import timezone
        item = NewsItem(
            id=script.news_id,
            headline=script.text[:120],
            body=script.text,
            url="",
            source=settings.BRAND_NAME,
            source_type="rss",
            timestamp=datetime.now(timezone.utc),
        )

    size = _VERTICAL if script.format == "short" else _LANDSCAPE

    # Ticker text — loops continuously
    ticker_text = (
        f"  {item.headline}  ▪  {item.source}  ▪  "
        f"{settings.BRAND_NAME}  ▪  {settings.BRAND_TAGLINE}  ▪  "
    )

    make_frame = _make_frame_func(item, script, size, ticker_text)

    # Audio
    audio_clip = None
    if voiceover_path and voiceover_path.exists():
        audio_clip = AudioFileClip(str(voiceover_path))
        duration   = audio_clip.duration
    else:
        duration = float(script.estimated_duration_seconds)
        logger.warning("No voiceover — video will be silent, duration=%ds", int(duration))

    video = VideoClip(make_frame, duration=duration)
    if audio_clip:
        video = video.set_audio(audio_clip)

    logger.info(
        "Rendering animated news video: %s (%.1fs, %dx%d) ...",
        output_path.name, duration, size[0], size[1],
    )
    video.write_videofile(
        str(output_path),
        fps=_FPS,
        codec="libx264",
        audio_codec="aac" if audio_clip else None,
        verbose=False,
        logger=None,
    )

    if audio_clip:
        audio_clip.close()
    video.close()

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info("Video saved: %s (%.1f MB)", output_path.name, size_mb)
    return output_path
