"""
HeyGen AI presenter video generator — Step 6.

Submits a video generation job to HeyGen, polls until complete,
then downloads the result to storage/Videos/Raw/.

HeyGen typically takes 2–10 minutes per video.
The pipeline retries and has a 30-minute hard timeout.
"""
import logging
import time
from pathlib import Path

import requests

from config import settings
from core.types import Script

logger = logging.getLogger(__name__)

_BASE    = "https://api.heygen.com"
_HEADERS = {"X-Api-Key": settings.HEYGEN_API_KEY, "Content-Type": "application/json"}


def _upload_audio(audio_path: Path) -> str:
    """Upload an MP3 to HeyGen assets and return the hosted URL."""
    with open(audio_path, "rb") as f:
        resp = requests.post(
            f"{_BASE}/v1/asset",
            headers={"X-Api-Key": settings.HEYGEN_API_KEY},
            files={"file": (audio_path.name, f, "audio/mpeg")},
            timeout=60,
        )
    resp.raise_for_status()
    return resp.json()["data"]["url"]


def _submit_job(script: Script, voiceover_path: Path | None) -> str:
    """Submit a HeyGen video generation job. Returns video_id."""
    audio_url = _upload_audio(voiceover_path) if voiceover_path and voiceover_path.exists() else None

    voice = (
        {"type": "audio", "audio_url": audio_url}
        if audio_url
        else {"type": "text", "input_text": script.text, "voice_id": "default"}
    )

    payload = {
        "video_inputs": [{
            "character": {
                "type": "avatar",
                "avatar_id": settings.HEYGEN_AVATAR_ID,
                "avatar_style": "normal",
            },
            "voice":      voice,
            "background": {"type": "color", "value": "#1A1A2E"},
        }],
        "dimension":    {"width": 1920, "height": 1080},
        "aspect_ratio": "16:9" if script.format == "main" else "9:16",
    }

    resp = requests.post(f"{_BASE}/v2/video/generate", json=payload, headers=_HEADERS, timeout=30)
    resp.raise_for_status()
    video_id = resp.json().get("data", {}).get("video_id")
    if not video_id:
        raise RuntimeError(f"HeyGen did not return a video_id: {resp.json()}")

    logger.info("HeyGen job submitted: video_id=%s", video_id)
    return video_id


def _poll_status(video_id: str) -> tuple[str, str | None]:
    """Returns (status, download_url). Status: pending | processing | completed | failed."""
    resp = requests.get(
        f"{_BASE}/v1/video_status.get",
        params={"video_id": video_id},
        headers=_HEADERS,
        timeout=15,
    )
    resp.raise_for_status()
    data = resp.json().get("data", {})
    return data.get("status", "pending"), data.get("video_url")


def _download(url: str, output_path: Path) -> Path:
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info("Presenter video downloaded: %s", output_path.name)
    return output_path


def create_presenter_video(script: Script, voiceover_path: Path | None = None) -> Path:
    """
    Full flow: submit → poll → download.
    Returns path to the raw video file in storage/Videos/Raw/.
    """
    output_path = settings.VIDEOS_RAW_DIR / f"{script.news_id}_{script.format}_raw.mp4"

    if output_path.exists():
        logger.info("Raw video already exists, skipping: %s", output_path.name)
        return output_path

    video_id    = _submit_job(script, voiceover_path)
    max_wait    = 1800  # 30-minute hard limit
    elapsed     = 0

    while elapsed < max_wait:
        time.sleep(settings.HEYGEN_POLL_INTERVAL_SECONDS)
        elapsed += settings.HEYGEN_POLL_INTERVAL_SECONDS
        status, url = _poll_status(video_id)
        logger.info("HeyGen %s: %s (%ds elapsed)", video_id, status, elapsed)

        if status == "completed" and url:
            return _download(url, output_path)
        if status == "failed":
            raise RuntimeError(f"HeyGen failed for video_id={video_id}")

    raise TimeoutError(f"HeyGen timed out after {max_wait}s for video_id={video_id}")
