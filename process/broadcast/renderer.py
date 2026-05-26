"""
render() — entry point for the broadcast compositor.
Orchestrates all components; called by video_maker.py and the standalone script.
"""
from datetime import datetime
from pathlib import Path

from moviepy.editor import VideoClip, AudioFileClip

from . import constants as C
from .assets import load_background, load_frame_and_mask, load_video_clip
from .animations import build_dp_anim
from .ticker import build_ticker
from .compositor import make_frame_func


def render(data: dict, output_path: Path | str, duration: float) -> Path:
    """
    Render a breaking-news broadcast video to output_path.

    Args:
        data:        Data dict with headline_white/red, source, deal_points,
                     ticker, left_video, breaking_label, deal_label, voiceover.
        output_path: Destination MP4 path.
        duration:    Video length in seconds.

    Returns:
        Resolved Path to the written MP4.
    """
    output_path = Path(output_path)

    bg_clip             = load_background("config/video/background.mp4")
    frame_img, win_mask = load_frame_and_mask("config/images/frame.png")
    left_clip           = load_video_clip(data["left_video"]) if data.get("left_video") else None
    ticker_img, ticker_w = build_ticker(data)
    dp_anim             = build_dp_anim(data)
    date_str            = (
        str(datetime.now().day) + " " + datetime.now().strftime("%b  %H:%M")
    )

    make_frame = make_frame_func(
        data, bg_clip, frame_img, win_mask,
        left_clip, ticker_img, ticker_w, dp_anim, date_str,
    )

    clip = VideoClip(make_frame, duration=duration)

    if data.get("voiceover"):
        audio = AudioFileClip(data["voiceover"])
        if audio.duration >= duration:
            audio = audio.subclip(0, duration)
        else:
            audio = audio.audio_loop(duration=duration)
        clip = clip.set_audio(audio)

    clip.write_videofile(
        str(output_path),
        fps=C.FPS,
        codec="libx264",
        audio=bool(data.get("voiceover")),
        verbose=False,
        logger=None,
    )
    clip.close()
    return output_path.resolve()
