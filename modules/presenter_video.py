"""
HeyGen AI presenter video generation.
Submits a video generation job, polls until complete, downloads the result
to storage/Videos/Raw/.
"""
import logging
import time
from pathlib import Path

import requests

from config import settings
from modules.script_generator import Script

logger = logging.getLogger(__name__)

HEYGEN_BASE = "https://api.heygen.com"
HEYGEN_HEADERS = {
    "X-Api-Key": settings.HEYGEN_API_KEY,
    "Content-Type": "application/json",
}


def _create_video_job(script: Script, voiceover_path: Path | None = None) -> str:
    """
    Submits a video generation request to HeyGen.
    Returns the video_id for polling.

    If voiceover_path is provided, uploads the audio and uses it.
    Otherwise, HeyGen generates its own voice from the script text.
    """
    audio_url: str | None = None
    if voiceover_path and voiceover_path.exists():
        audio_url = _upload_audio_to_heygen(voiceover_path)

    voice_config = (
        {"type": "audio", "audio_url": audio_url}
        if audio_url
        else {
            "type": "text",
            "input_text": script.text,
            "voice_id": "default",
        }
    )

    payload = {
        "video_inputs": [
            {
                "character": {
                    "type": "avatar",
                    "avatar_id": settings.HEYGEN_AVATAR_ID,
                    "avatar_style": "normal",
                },
                "voice": voice_config,
                "background": {
                    "type": "color",
                    "value": "#1A1A2E",
                },
            }
        ],
        "dimension": {"width": 1920, "height": 1080},
        "aspect_ratio": "16:9" if script.format == "main" else "9:16",
    }

    response = requests.post(
        f"{HEYGEN_BASE}/v2/video/generate",
        json=payload,
        headers=HEYGEN_HEADERS,
        timeout=30,
    )
    response.raise_for_status()
    data = response.json()

    video_id = data.get("data", {}).get("video_id")
    if not video_id:
        raise RuntimeError(f"HeyGen did not return a video_id: {data}")

    logger.info("HeyGen job submitted. video_id=%s", video_id)
    return video_id


def _upload_audio_to_heygen(audio_path: Path) -> str:
    """Uploads an MP3 to HeyGen's asset endpoint and returns a usable URL."""
    with open(audio_path, "rb") as f:
        response = requests.post(
            f"{HEYGEN_BASE}/v1/asset",
            headers={"X-Api-Key": settings.HEYGEN_API_KEY},
            files={"file": (audio_path.name, f, "audio/mpeg")},
            timeout=60,
        )
    response.raise_for_status()
    return response.json()["data"]["url"]


def _poll_video_status(video_id: str) -> tuple[str, str | None]:
    """
    Returns (status, download_url).
    status is one of: "processing" | "completed" | "failed" | "pending"
    """
    response = requests.get(
        f"{HEYGEN_BASE}/v1/video_status.get",
        params={"video_id": video_id},
        headers=HEYGEN_HEADERS,
        timeout=15,
    )
    response.raise_for_status()
    data = response.json().get("data", {})
    return data.get("status", "pending"), data.get("video_url")


def _download_video(url: str, output_path: Path) -> Path:
    response = requests.get(url, stream=True, timeout=300)
    response.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info("Presenter video downloaded: %s", output_path.name)
    return output_path


def create_presenter_video(script: Script, voiceover_path: Path | None = None) -> Path:
    """
    Full flow: submit → poll → download.
    Returns path to the downloaded raw video file.
    """
    output_path = settings.VIDEOS_RAW_DIR / f"{script.news_id}_{script.format}_raw.mp4"

    if output_path.exists():
        logger.info("Raw video already exists, skipping: %s", output_path.name)
        return output_path

    video_id = _create_video_job(script, voiceover_path)

    # Poll until complete (HeyGen typically takes 2–10 minutes)
    max_wait_seconds = 1800  # 30 minutes hard limit
    elapsed = 0
    while elapsed < max_wait_seconds:
        time.sleep(settings.HEYGEN_POLL_INTERVAL_SECONDS)
        elapsed += settings.HEYGEN_POLL_INTERVAL_SECONDS

        status, video_url = _poll_video_status(video_id)
        logger.info("HeyGen status for %s: %s (elapsed %ds)", video_id, status, elapsed)

        if status == "completed" and video_url:
            return _download_video(video_url, output_path)
        if status == "failed":
            raise RuntimeError(f"HeyGen video generation failed for video_id={video_id}")

    raise TimeoutError(f"HeyGen video not ready after {max_wait_seconds}s for video_id={video_id}")
