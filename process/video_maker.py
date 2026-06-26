"""
Video orchestration — Step 6.

All video rendering uses the broadcast compositor (process/broadcast/).
B-roll clips are selected by the LLM during script generation and
looked up from the local video_clips DB table.

Single-story and multi-story videos both use create_multi_story_video().
Pass a list of one tuple for a single-story video.
"""
import logging
import math
from datetime import datetime
from pathlib import Path

import numpy as np
from PIL import Image

if not hasattr(Image, "ANTIALIAS"):
    Image.ANTIALIAS = Image.Resampling.LANCZOS  # type: ignore[attr-defined]

from config import settings
from core.types import NewsItem, Script
from core.database import get_clips_by_ids
from process.broadcast.assets import load_background, load_frame_and_mask
from process.broadcast.compositor import make_frame_func as _broadcast_make_frame
from process.broadcast.ticker import build_ticker as _build_ticker
from process.broadcast.animations import build_dp_anim as _build_dp_anim
from process.broadcast.data import build_data_dict as _build_broadcast_data
from process.broadcast import constants as _BC

_CHANNEL = settings.BRAND_NAME
_TAGLINE = settings.BRAND_TAGLINE

logger = logging.getLogger(__name__)

_INTRO_VIDEO_PATH = settings.BASE_DIR / "config" / "video" / "intro.mp4"
_OUTRO_VIDEO_PATH = settings.BASE_DIR / "config" / "video" / "outro.mp4"


def _clip_filename(file_path: str) -> str:
    return str(file_path).replace("\\", "/").rstrip("/").split("/")[-1]


def _ticker_text(item: NewsItem) -> str:
    headline = " ".join(item.headline.split())  # collapse all whitespace/newlines to single spaces
    return f"  {headline}  ▪  {item.source}  ▪  {_CHANNEL}  ▪  {_TAGLINE}  ▪  "


def _fit_clip(clip, target_w: int, target_h: int):
    """Scale-to-cover then center-crop a VideoFileClip to target dimensions."""
    scale = max(target_w / clip.w, target_h / clip.h)
    clip = clip.resize(scale)
    x1 = (clip.w - target_w) / 2
    y1 = (clip.h - target_h) / 2
    return clip.crop(x1=x1, y1=y1, x2=x1 + target_w, y2=y1 + target_h)


class _ClipSequence:
    """Lightweight looping sequence that avoids MoviePy concatenation memory overhead."""

    def __init__(self, clips: list) -> None:
        self.clips = [clip for clip in clips if getattr(clip, "duration", 0)]
        self.duration = sum(float(clip.duration) for clip in self.clips)
        self._bounds: list[tuple[float, float, object]] = []
        offset = 0.0
        for clip in self.clips:
            end = offset + float(clip.duration)
            self._bounds.append((offset, end, clip))
            offset = end

    def get_frame(self, t: float):
        if not self._bounds or self.duration <= 0:
            raise ValueError("No clips available in sequence")
        local_t = t % self.duration
        for start, end, clip in self._bounds:
            if local_t < end:
                return clip.get_frame(max(0.0, local_t - start))
        start, _, clip = self._bounds[-1]
        return clip.get_frame(max(0.0, local_t - start))

    def close(self) -> None:
        for clip in self.clips:
            try:
                clip.close()
            except Exception:
                pass


def create_multi_story_video(
    stories: list[tuple[Script, NewsItem, Path | None]],
    output_name: str = "multi_story_breaking",
    include_intro_outro: bool = True,
    include_intro: bool | None = None,
    include_outro: bool | None = None,
) -> Path:
    """Render one or more news stories into a single broadcast video.

    Set include_intro_outro=False to skip intro/outro (useful for quick tests).
    Each story uses clip IDs from script.selected_clip_ids (set by
    generate_segment_script). voiceover_path can be None for silent segments.
    """
    from moviepy.editor import (
        VideoClip,
        VideoFileClip as _VFC,
        concatenate_videoclips,
        AudioFileClip,
        CompositeAudioClip,
    )

    if include_intro is None:
        include_intro = include_intro_outro
    if include_outro is None:
        include_outro = include_intro_outro

    output_path = settings.VIDEOS_DIR / f"{output_name}.mp4"
    settings.VIDEOS_DIR.mkdir(parents=True, exist_ok=True)

    _TRANSITION_DUR = 3.2

    video_clips: list = []
    audio_clips: list = []

    total = len(stories)
    print(f"\n{'='*56}")
    print(f"  Broadcast Video  |  {total} stor{'y' if total == 1 else 'ies'}")
    print(f"{'='*56}")

    # Load shared broadcast assets once (cached at module level in assets.py)
    bg_clip             = load_background("config/video/background.mp4")
    frame_img, win_mask = load_frame_and_mask("config/images/frame.png")
    date_str = (
        str(datetime.now().day) + " " + datetime.now().strftime("%b  %H:%M")
    )
    print("  Broadcast assets loaded (background + frame.png)")

    # Intro
    t_offset = 0.0
    if include_intro:
        if _INTRO_VIDEO_PATH.exists():
            intro_clip = _VFC(str(_INTRO_VIDEO_PATH))
            intro_clip = _fit_clip(intro_clip, _BC.W, _BC.H)
            _INTRO_DUR = intro_clip.duration
            if intro_clip.audio:
                audio_clips.append(intro_clip.audio.set_start(0.0))
            video_clips.append(intro_clip.without_audio())
            print(f"  Intro: {_INTRO_DUR:.1f}s")
        else:
            _INTRO_DUR = 3.0
            video_clips.append(VideoClip(
                lambda t: np.zeros((_BC.H, _BC.W, 3), dtype=np.uint8),
                duration=_INTRO_DUR,
            ))
            print("  WARNING: intro.mp4 not found — black fallback")
        t_offset = _INTRO_DUR
    else:
        print("  Intro skipped")

    def _black_clip(dur: float = _TRANSITION_DUR) -> VideoClip:
        return VideoClip(
            lambda t: np.zeros((_BC.H, _BC.W, 3), dtype=np.uint8),
            duration=dur,
        )

    # ── Logo sweep transition ─────────────────────────────────────────────────
    _LOGO_PATH = settings.BASE_DIR / "config" / "images" / "logo.png"
    _LOGO_H    = 520
    _TILT      = 0.55   # "/" bar angle
    _PAD       = 600    # off-screen padding
    _LOGO_SHIFT_X = 40
    _STRIPES   = [
        (0,   90, (28, 67, 10), 1.00),
        (80,  55, (41, 97, 14), 1.00),
        (140, 22, (58, 128, 20), 1.00),
        (163,  6, (92, 168, 36), 1.00),
    ]

    _logo_img: Image.Image | None = None
    if _LOGO_PATH.exists():
        _raw = Image.open(_LOGO_PATH).convert("RGBA")
        _scale = _LOGO_H / _raw.height
        _logo_img = _raw.resize((int(_raw.width * _scale), _LOGO_H), Image.LANCZOS)
        _logo_img = _logo_img.rotate(
            math.degrees(math.atan(_TILT)),
            resample=Image.BICUBIC,
            expand=True,
        )
        logger.info("Transition logo loaded: %dx%d", _logo_img.width, _logo_img.height)

    def _logo_sweep_clip(
        old_get_frame,        # callable: t -> np.ndarray
        new_get_frame,        # callable: t -> np.ndarray
        old_start_t: float,   # time in old clip to begin from (pass old_dur to continue past voice end)
        dur: float = _TRANSITION_DUR,
    ) -> VideoClip:
        """
        Wipe transition: "/" diagonal band sweeps bottom-left -> top-right.
          Right of band = old story, LIVE — ticker/video keep advancing.
          Left  of band = new story, LIVE — headline animates in from t=0.
        old_start_t = old_dur makes the old side continue exactly where the
        voice ended with no freeze and no rewind.
        Transition sound is added separately in the audio timeline.
        """
        _y_g, _x_g = np.mgrid[0:_BC.H, 0:_BC.W]
        _diag  = _x_g.astype(np.float32) - _y_g.astype(np.float32) * _TILT
        lw = _logo_img.width  if _logo_img else 0
        lh = _logo_img.height if _logo_img else 0

        def _make_frame(t: float) -> np.ndarray:
            # Old side: continues live from old_start_t (past voice end — no freeze)
            # New side: starts fresh at t=0 so headline animates in during the wipe
            old_f = old_get_frame(old_start_t + t).astype(np.float32)
            new_f = new_get_frame(t).astype(np.float32)

            p  = t / dur
            cx = -_PAD + p * (_BC.W + 2 * _PAD)
            cy = _BC.H + _PAD - p * (_BC.H + 2 * _PAD)
            d_center = cx - cy * _TILT

            left_mask = (_diag < d_center)[:, :, np.newaxis]
            canvas    = np.where(left_mask, new_f, old_f)

            for d_off, hw, color, opacity in _STRIPES:
                dist = np.abs(_diag - (d_center + d_off))
                mask = (dist <= hw)[:, :, np.newaxis]
                col  = np.array(color, dtype=np.float32)
                canvas = np.where(mask, canvas * (1.0 - opacity) + col * opacity, canvas)

            out = canvas.clip(0, 255).astype(np.uint8)

            if _logo_img is None:
                return out

            px = int(cx + _LOGO_SHIFT_X) - lw // 2
            py = int(cy) - lh // 2
            fade = min(1.0, min(p, 1.0 - p) / 0.12)
            if fade <= 0.0:
                return out

            logo_rgba = _logo_img.copy()
            if fade < 1.0:
                r, g, b, a = logo_rgba.split()
                logo_rgba = Image.merge("RGBA", (r, g, b, a.point(lambda v: int(v * fade))))

            pil_out = Image.fromarray(out)
            sx0 = max(0, -px);          sy0 = max(0, -py)
            sx1 = min(lw, _BC.W - px);  sy1 = min(lh, _BC.H - py)
            dx  = max(0, px);           dy  = max(0, py)
            if sx1 > sx0 and sy1 > sy0:
                crop = logo_rgba.crop((sx0, sy0, sx1, sy1))
                pil_out.paste(crop, (dx, dy), crop)
            return np.array(pil_out)

        return VideoClip(_make_frame, duration=dur)

    # ── Pass 1: build all story clips ────────────────────────────────────────
    built: list[tuple] = []   # (VideoClip, audio_clip, duration, left_clip)
    _downloaded_clips: list[Path] = []  # cleaned up after render

    for idx, (script, item, vo_path) in enumerate(stories):
        print(f"\n[{idx+1}/{total}] {item.headline[:70]}")
        logger.info("Story %d/%d: %s", idx + 1, total, item.headline[:60])

        print("  Step 1/3 — Audio / duration")
        audio_clip = None
        if vo_path and Path(vo_path).exists():
            audio_clip = AudioFileClip(str(vo_path))
            duration = audio_clip.duration
            print(f"    Voiceover: {Path(vo_path).name}  ({duration:.1f}s)")
        else:
            duration = float(script.estimated_duration_seconds)
            print(f"    No voiceover — using estimated {duration:.0f}s")
        duration = max(duration, 10.0)

        print("  Step 2/3 — Downloading clips from Drive")
        left_clip = None
        left_path = None
        if script.selected_clip_ids:
            from clients.gdrive import download_clip as _drive_download
            rows = get_clips_by_ids(script.selected_clip_ids)
            loaded = []
            drive_clip_dir = settings.TEMP_DIR / "drive_clips"
            drive_clip_dir.mkdir(parents=True, exist_ok=True)
            for row in rows:
                filename = _clip_filename(str(row["file_path"]))
                download_path = drive_clip_dir / filename

                # Never reuse a prior local copy here. Clips must come from Drive.
                if download_path.exists():
                    try:
                        download_path.unlink()
                    except Exception:
                        pass

                if _drive_download(filename, download_path):
                    print(f"    Clip downloaded from Drive: {filename}")
                    _downloaded_clips.append(download_path)
                    loaded.append((download_path, _VFC(str(download_path))))
                else:
                    print(f"    Clip not available on Drive: {filename}")
            if loaded:
                left_path = loaded[0][0]
                if len(loaded) == 1:
                    left_clip = loaded[0][1]
                    print(f"    Clip: {loaded[0][0].name}")
                else:
                    left_clip = _ClipSequence([c for _, c in loaded])
                    names = ", ".join(p.name for p, _ in loaded)
                    print(f"    Clips ({len(loaded)} looped sequence): {names}")
            else:
                print("    No clips available — left panel empty")
        else:
            print("    No clip IDs in script — left panel empty")

        print("  Step 3/3 — Building broadcast frame")
        ticker_text          = _ticker_text(item)
        data                 = _build_broadcast_data(script, item, None, left_path, ticker_text)
        ticker_img, ticker_w = _build_ticker(data)
        dp_anim              = _build_dp_anim(data)

        make_frame = _broadcast_make_frame(
            data, bg_clip, frame_img, win_mask,
            left_clip, ticker_img, ticker_w, dp_anim, date_str,
        )
        clip = VideoClip(make_frame, duration=duration)
        print(f"    Broadcast frame ready ({duration:.1f}s @ {_BC.FPS}fps)")

        built.append((clip, audio_clip, duration, left_clip))
        print(f"  [OK] Story {idx+1} built")

    # ── Pass 2: assemble ──────────────────────────────────────────────────────
    # Timeline per story pair:
    #   [story N — full voice duration, full video duration — they end together] →
    #   [wipe: old side live past voice end / new side = static first frame (empty slate)] →
    #   [story N+1 — full clip from t=0, voice starts after wipe]
    #
    # All stories play their full duration so voice always ends exactly when
    # the wipe starts — no voice overlap with animation.
    # The new side of the wipe shows a static first frame (headline not yet
    # visible at t=0) so there is no double headline render after the wipe.
    _TRANSITION_SFX_PATH = settings.BASE_DIR / "config" / "audio" / "transition.mp3"

    for idx, (clip, audio_clip, duration, _) in enumerate(built):
        video_clips.append(clip)
        if audio_clip:
            audio_clips.append(audio_clip.set_start(t_offset))
        t_offset += duration

        if idx < total - 1:
            old_clip, _, old_dur, _ = built[idx]
            new_clip                = built[idx + 1][0]

            # Old side: continues live from old_dur — ticker keeps scrolling
            # New side: static frame at t=0 — empty slate, headline not yet visible
            #           so after the wipe the headline animates in fresh (no double render)
            new_first_frame = new_clip.get_frame(0)
            video_clips.append(_logo_sweep_clip(
                old_clip.get_frame, lambda t, f=new_first_frame: f, old_dur,
            ))

            # Transition sound plays during the wipe
            if _TRANSITION_SFX_PATH.exists():
                sfx = AudioFileClip(str(_TRANSITION_SFX_PATH))
                if sfx.duration > _TRANSITION_DUR:
                    sfx = sfx.subclip(0, _TRANSITION_DUR)
                audio_clips.append(sfx.set_start(t_offset))
                print(f"    Transition SFX: {_TRANSITION_SFX_PATH.name}")
            else:
                print(f"    No transition SFX ({_TRANSITION_SFX_PATH.name} not found)")

            t_offset += _TRANSITION_DUR
            logger.info("Transition %d->%d added (%.1fs)", idx + 1, idx + 2, _TRANSITION_DUR)

        print(f"  [OK] Story {idx+1} queued  (running total: {t_offset:.1f}s)")

    # Outro
    if include_outro:
        if _OUTRO_VIDEO_PATH.exists():
            outro_clip = _VFC(str(_OUTRO_VIDEO_PATH))
            outro_clip = _fit_clip(outro_clip, _BC.W, _BC.H)
            _OUTRO_DUR = outro_clip.duration
            if outro_clip.audio:
                audio_clips.append(outro_clip.audio.set_start(t_offset))
            video_clips.append(outro_clip.without_audio())
            print(f"  Outro: {_OUTRO_DUR:.1f}s")
        else:
            print("  WARNING: outro.mp4 not found — skipping")
        if _OUTRO_VIDEO_PATH.exists():
            t_offset += _OUTRO_DUR
    else:
        print("  Outro skipped")

    total_dur = t_offset
    print(f"\n  Step 4/4 — Concatenating {len(video_clips)} clips ({total_dur:.1f}s total) ...")
    logger.info("Concatenating %d clips (total %.1fs) ...", len(video_clips), total_dur)
    final = concatenate_videoclips(video_clips, method="compose")
    if audio_clips:
        final = final.set_audio(CompositeAudioClip(audio_clips))
        print(f"  Audio: {len(audio_clips)} track(s) merged")

    print(f"\n  Rendering -> {output_path.name}  (this takes a while) ...")
    logger.info("Rendering %s ...", output_path.name)
    has_audio = bool(audio_clips)
    try:
        final.write_videofile(
            str(output_path),
            fps=_BC.FPS,
            codec="libx264",
            audio=has_audio,
            audio_codec="aac" if has_audio else None,
            ffmpeg_params=["-preset", "ultrafast"],
            threads=2,
            verbose=False,
            logger=None,
        )
    finally:
        final.close()
        # Close all individual clips so Windows releases file handles before Drive sync
        for clip, audio_clip, _, left_clip in built:
            try:
                clip.close()
            except Exception:
                pass
            if left_clip:
                try:
                    left_clip.close()
                except Exception:
                    pass
            if audio_clip:
                try:
                    audio_clip.close()
                except Exception:
                    pass
        for p in _downloaded_clips:
            try:
                p.unlink()
            except Exception:
                pass
        if _downloaded_clips:
            print(f"  Cleaned up {len(_downloaded_clips)} downloaded clip(s)")

    size_mb = output_path.stat().st_size / (1024 * 1024)
    logger.info("Video saved: %s (%.1f MB, %.1fs)", output_path.name, size_mb, total_dur)
    print(f"\n{'='*56}")
    print(f"  [OK] DONE  {output_path.name}")
    print(f"      Size: {size_mb:.1f} MB   Duration: {total_dur:.1f}s")
    print(f"{'='*56}\n")
    return output_path
