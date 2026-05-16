"""
Creatomate video editor / branding module.
Applies intro, outro, news ticker, club colours, and brand watermark
to the raw HeyGen presenter video, producing the final branded video.
"""
import logging
import time
from pathlib import Path

import requests

from config import settings
from modules.news_monitor import NewsItem
from modules.script_generator import Script

logger = logging.getLogger(__name__)

CREATOMATE_API_URL = "https://api.creatomate.com/v1/renders"
CREATOMATE_HEADERS = {
    "Authorization": f"Bearer {settings.CREATOMATE_API_KEY}",
    "Content-Type": "application/json",
}

_MAX_POLL_SECONDS = 600  # 10 minutes
_POLL_INTERVAL = 15


def _get_club_colour(item: NewsItem) -> str:
    text = (item.headline + " " + item.body[:200]).lower()
    for club, colour in settings.CLUB_COLOURS.items():
        if club != "default" and club in text:
            return colour
    return settings.CLUB_COLOURS["default"]


def _build_modifications(
    raw_video_path: Path,
    item: NewsItem,
    script: Script,
    club_colour: str,
) -> dict:
    """
    Builds the Creatomate 'modifications' payload.
    These keys must match the element names inside the Creatomate template.
    """
    return {
        "presenter-video": {
            "source": raw_video_path.as_posix(),
        },
        "headline-ticker": item.headline[:80],
        "brand-name": settings.BRAND_NAME,
        "brand-tagline": settings.BRAND_TAGLINE,
        "club-colour": club_colour,
        "content-type-badge": _content_type_label(script.script_type),
    }


def _content_type_label(content_type: str) -> str:
    labels = {
        "breaking_news":   "BREAKING",
        "transfer_rumour": "TRANSFER",
        "club_update":     "NEWS",
        "tactical":        "ANALYSIS",
    }
    return labels.get(content_type, "NEWS")


def _submit_render(modifications: dict, is_vertical: bool) -> str:
    """Submits a render job to Creatomate. Returns the render ID."""
    template_id = (
        settings.CREATOMATE_TEMPLATE_VERTICAL
        if is_vertical
        else settings.CREATOMATE_TEMPLATE_LANDSCAPE
    )
    payload = {
        "template_id": template_id,
        "modifications": modifications,
        "output_format": "mp4",
    }
    response = requests.post(
        CREATOMATE_API_URL, json=payload, headers=CREATOMATE_HEADERS, timeout=30
    )
    response.raise_for_status()
    renders = response.json()
    render_id = renders[0]["id"]
    logger.info("Creatomate render submitted. render_id=%s", render_id)
    return render_id


def _poll_render(render_id: str) -> str:
    """Polls until render is complete. Returns the download URL."""
    elapsed = 0
    while elapsed < _MAX_POLL_SECONDS:
        time.sleep(_POLL_INTERVAL)
        elapsed += _POLL_INTERVAL

        response = requests.get(
            f"{CREATOMATE_API_URL}/{render_id}",
            headers=CREATOMATE_HEADERS,
            timeout=15,
        )
        response.raise_for_status()
        data = response.json()
        status = data.get("status")
        logger.info("Creatomate render %s: %s (elapsed %ds)", render_id, status, elapsed)

        if status == "succeeded":
            return data["url"]
        if status in ("failed", "canceled"):
            raise RuntimeError(f"Creatomate render {render_id} failed: {data.get('error')}")

    raise TimeoutError(f"Creatomate render {render_id} timed out after {_MAX_POLL_SECONDS}s")


def _download_render(url: str, output_path: Path) -> Path:
    response = requests.get(url, stream=True, timeout=300)
    response.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info("Branded video saved: %s", output_path.name)
    return output_path


def apply_branding(
    raw_video_path: Path,
    item: NewsItem,
    script: Script,
) -> Path:
    """
    Applies branding template to the raw presenter video via Creatomate.
    Returns the path to the final branded video.
    """
    is_vertical = script.format == "short"
    suffix = "short" if is_vertical else "final"
    output_path = settings.VIDEOS_FINAL_DIR / f"{script.news_id}_{suffix}_branded.mp4"

    if output_path.exists():
        logger.info("Branded video already exists, skipping: %s", output_path.name)
        return output_path

    club_colour = _get_club_colour(item)
    modifications = _build_modifications(raw_video_path, item, script, club_colour)

    render_id = _submit_render(modifications, is_vertical)
    download_url = _poll_render(render_id)
    return _download_render(download_url, output_path)
