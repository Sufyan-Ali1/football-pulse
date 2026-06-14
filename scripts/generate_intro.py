"""
Generate a premium 1080p AI intro video using Google Veo 3.1 Standard
through Vertex AI and save to config/video/intro.mp4.

Prompt is read from:
    config/prompts/intro_prompt.txt

Recommended:
    For perfect logo/text quality, do NOT let Veo generate your logo/text.
    Generate the cinematic football background with Veo, then overlay logo/tagline
    later using FFmpeg or MoviePy.

Usage:
    venv\\Scripts\\python scripts\\generate_intro.py
    venv\\Scripts\\python scripts\\generate_intro.py --output config/video/outro.mp4
"""

from __future__ import annotations

import argparse
import base64
import logging
import sys
import time
from pathlib import Path
from typing import Any

import requests

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from config import settings
from publish.thumbnail import _get_vertex_access_token

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)

_PROMPT_PATH = ROOT / "config" / "prompts" / "intro_prompt.txt"
_LOGO_PATH = ROOT / "config" / "images" / "logo.png"
_DEFAULT_OUT = ROOT / "config" / "video" / "intro.mp4"

# Best quality 1080p model for one-time generation.
_VEO_MODEL = "veo-3.1-generate-001"

_DURATION_SECONDS = 8
_RESOLUTION = "1080p"
_ASPECT_RATIO = "16:9"

_POLL_INTERVAL = 15
_MAX_WAIT = 600

def _guess_mime_type(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".jpg", ".jpeg"}:
        return "image/jpeg"
    if suffix == ".png":
        return "image/png"
    if suffix == ".webp":
        return "image/webp"
    return "image/png"


def _encode_image(path: Path) -> tuple[str, str]:
    """Return (base64_string, mime_type) for an image file."""
    return base64.b64encode(path.read_bytes()).decode("utf-8"), _guess_mime_type(path)


def _build_payload(
    prompt: str,
    start_frame: Path | None,
    end_frame: Path | None,
) -> dict[str, Any]:
    instance: dict[str, Any] = {"prompt": prompt}

    if start_frame:
        b64, mime = _encode_image(start_frame)
        instance["image"] = {"bytesBase64Encoded": b64, "mimeType": mime}
        logger.info("Start frame attached: %s", start_frame.name)

    if end_frame:
        b64, mime = _encode_image(end_frame)
        instance["lastFrame"] = {"bytesBase64Encoded": b64, "mimeType": mime}
        logger.info("End frame attached: %s", end_frame.name)

    return {
        "instances": [instance],
        "parameters": {
            "aspectRatio": _ASPECT_RATIO,
            "sampleCount": 1,
            "durationSeconds": _DURATION_SECONDS,
            "resolution": _RESOLUTION,
            "addWatermark": False,
            "personGeneration": "allow_adult",
        },
    }


def _start_generation(payload: dict[str, Any], token: str) -> str:
    """Submit the Veo job and return the operation name."""

    url = (
        f"https://{settings.GOOGLE_CLOUD_LOCATION}-aiplatform.googleapis.com/v1/"
        f"projects/{settings.GOOGLE_CLOUD_PROJECT}/locations/{settings.GOOGLE_CLOUD_LOCATION}/"
        f"publishers/google/models/{_VEO_MODEL}:predictLongRunning"
    )

    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    resp = requests.post(url, headers=headers, json=payload, timeout=120)

    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"Veo request failed.\n"
            f"Status: {resp.status_code}\n"
            f"Response: {resp.text}"
        ) from exc

    data = resp.json()
    operation_name = data.get("name")

    if not operation_name:
        raise RuntimeError(f"Veo did not return an operation name: {data}")

    logger.info("Veo job started: %s", operation_name)
    return operation_name


def _poll_operation(operation_name: str, token: str) -> dict[str, Any]:
    """Poll until the operation is done and return the result.

    Uses fetchPredictOperation — the correct endpoint for Veo UUID-based operations.
    """
    url = (
        f"https://{settings.GOOGLE_CLOUD_LOCATION}-aiplatform.googleapis.com/v1/"
        f"projects/{settings.GOOGLE_CLOUD_PROJECT}/locations/{settings.GOOGLE_CLOUD_LOCATION}/"
        f"publishers/google/models/{_VEO_MODEL}:fetchPredictOperation"
    )
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"operationName": operation_name}

    elapsed = 0
    while elapsed < _MAX_WAIT:
        time.sleep(_POLL_INTERVAL)
        elapsed += _POLL_INTERVAL

        resp = requests.post(url, headers=headers, json=body, timeout=60)
        try:
            resp.raise_for_status()
        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Veo polling failed.\nStatus: {resp.status_code}\nResponse: {resp.text}"
            ) from exc

        data = resp.json()
        done = data.get("done", False)
        logger.info("Polling ... elapsed=%ds done=%s", elapsed, done)

        if done:
            if "error" in data:
                raise RuntimeError(f"Veo operation failed: {data['error']}")
            return data

    raise TimeoutError(f"Veo generation timed out after {_MAX_WAIT}s")


def _download_video_from_uri(uri: str, token: str | None) -> bytes:
    """Download video bytes from a URI returned by Veo.

    Handles both https:// and gs:// (Google Cloud Storage) URIs.
    """
    if uri.startswith("gs://"):
        # GCS URI — use storage client
        from google.cloud import storage as gcs
        path = uri[5:]  # strip gs://
        bucket_name, blob_name = path.split("/", 1)
        client = gcs.Client(project=settings.GOOGLE_CLOUD_PROJECT)
        bucket = client.bucket(bucket_name)
        blob = bucket.blob(blob_name)
        return blob.download_as_bytes()

    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    resp = requests.get(uri, headers=headers, timeout=180)

    try:
        resp.raise_for_status()
    except requests.HTTPError as exc:
        raise RuntimeError(
            f"Failed to download generated video.\n"
            f"URI: {uri}\n"
            f"Status: {resp.status_code}\n"
            f"Response: {resp.text[:1000]}"
        ) from exc

    return resp.content


def _extract_video_bytes(result: dict[str, Any], token: str | None = None) -> bytes:
    """
    Extract video bytes from Veo response.

    Supports:
    1. Old/prediction-style base64 responses
    2. New generateVideoResponse generatedSamples format
    3. URI-based video output
    """

    response = result.get("response", {})

    # Case 1: Vertex prediction-style response.
    predictions = response.get("predictions") or result.get("predictions") or []

    for prediction in predictions:
        b64 = (
            prediction.get("bytesBase64Encoded")
            or prediction.get("video", {}).get("bytesBase64Encoded")
        )

        if b64:
            return base64.b64decode(b64)

        uri = (
            prediction.get("uri")
            or prediction.get("video", {}).get("uri")
        )

        if uri:
            return _download_video_from_uri(uri, token)

    # Case 2: videos[] format (Veo 3.1 actual response format)
    for video in response.get("videos", []):
        b64 = video.get("bytesBase64Encoded")
        if b64:
            return base64.b64decode(b64)
        uri = video.get("uri")
        if uri:
            return _download_video_from_uri(uri, token)

    # Case 3: generateVideoResponse format.
    generated_samples = (
        response.get("generateVideoResponse", {})
        .get("generatedSamples", [])
    )

    for sample in generated_samples:
        video = sample.get("video", {})

        b64 = video.get("bytesBase64Encoded")
        if b64:
            return base64.b64decode(b64)

        uri = video.get("uri")
        if uri:
            return _download_video_from_uri(uri, token)

    # Case 3: Some responses may put generateVideoResponse directly at top level.
    generated_samples = (
        result.get("generateVideoResponse", {})
        .get("generatedSamples", [])
    )

    for sample in generated_samples:
        video = sample.get("video", {})

        b64 = video.get("bytesBase64Encoded")
        if b64:
            return base64.b64decode(b64)

        uri = video.get("uri")
        if uri:
            return _download_video_from_uri(uri, token)

    raise ValueError(f"No video bytes or video URI found in Veo response: {result}")


def generate_intro(
    output_path: Path,
    start_frame: Path | None = None,
    end_frame: Path | None = None,
) -> None:
    if not settings.GOOGLE_CLOUD_PROJECT:
        logger.error("GOOGLE_CLOUD_PROJECT is not set in .env")
        sys.exit(1)

    if not settings.GOOGLE_CLOUD_LOCATION:
        logger.error("GOOGLE_CLOUD_LOCATION is not set in .env")
        sys.exit(1)

    if not _PROMPT_PATH.exists():
        logger.error("Prompt file not found: %s", _PROMPT_PATH)
        sys.exit(1)

    prompt = _PROMPT_PATH.read_text(encoding="utf-8").strip()
    if not prompt:
        logger.error("Prompt file is empty: %s", _PROMPT_PATH)
        sys.exit(1)

    logger.info("Prompt loaded (%d chars)", len(prompt))
    logger.info("Prompt:\n%s", prompt)

    if start_frame and not start_frame.exists():
        logger.error("Start frame not found: %s", start_frame)
        sys.exit(1)

    if end_frame and not end_frame.exists():
        logger.error("End frame not found: %s", end_frame)
        sys.exit(1)

    token = _get_vertex_access_token()
    payload = _build_payload(prompt, start_frame, end_frame)

    logger.info(
        "Submitting Veo job: model=%s, duration=%ds, aspectRatio=%s, resolution=%s",
        _VEO_MODEL, _DURATION_SECONDS, _ASPECT_RATIO, _RESOLUTION,
    )

    operation_name = _start_generation(payload, token)
    logger.info("Waiting for Veo to finish. Polling every %ds, timeout %ds.", _POLL_INTERVAL, _MAX_WAIT)

    result = _poll_operation(operation_name, token)
    video_bytes = _extract_video_bytes(result, token)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(video_bytes)
    logger.info("Video saved: %s (%.1f MB)", output_path, len(video_bytes) / (1024 * 1024))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate 1080p intro/outro video using Google Veo"
    )
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUT, help="Output video path")
    parser.add_argument("--start-frame", type=Path, default=None, help="Path to start frame image")
    parser.add_argument("--end-frame", type=Path, default=None, help="Path to end frame image")
    args = parser.parse_args()

    generate_intro(args.output, args.start_frame, args.end_frame)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())