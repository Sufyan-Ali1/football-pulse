"""
Video editor / branding — Step 7.

Applies intro, outro, news ticker, club colours, and brand watermark
to the raw HeyGen presenter video via the Creatomate API,
producing the final branded video in storage/Videos/Final/.
"""
import logging
import time
from pathlib import Path

import requests

from config import settings
from core.constants import BADGE_LABELS
from core.types import ContentType, NewsItem, Script

logger = logging.getLogger(__name__)

_API_URL  = "https://api.creatomate.com/v1/renders"
_HEADERS  = {
    "Authorization": f"Bearer {settings.CREATOMATE_API_KEY}",
    "Content-Type":  "application/json",
}
_MAX_POLL = 600   # 10 minutes
_INTERVAL = 15


def _club_colour(item: NewsItem) -> str:
    text = (item.headline + " " + item.body[:200]).lower()
    for club, colour in settings.CLUB_COLOURS.items():
        if club != "default" and club in text:
            return colour
    return settings.CLUB_COLOURS["default"]


def _submit_render(raw_video_path: Path, item: NewsItem, script: Script) -> str:
    is_vertical  = script.format == "short"
    template_id  = (
        settings.CREATOMATE_TEMPLATE_VERTICAL
        if is_vertical
        else settings.CREATOMATE_TEMPLATE_LANDSCAPE
    )
    modifications = {
        "presenter-video":    raw_video_path.as_posix(),
        "headline-ticker":    item.headline[:80],
        "brand-name":         settings.BRAND_NAME,
        "brand-tagline":      settings.BRAND_TAGLINE,
        "club-colour":        _club_colour(item),
        "content-type-badge": BADGE_LABELS.get(script.script_type, "NEWS"),
    }
    resp = requests.post(
        _API_URL,
        json={"template_id": template_id, "modifications": modifications, "output_format": "mp4"},
        headers=_HEADERS,
        timeout=30,
    )
    resp.raise_for_status()
    render_id = resp.json()[0]["id"]
    logger.info("Creatomate render submitted: %s", render_id)
    return render_id


def _poll_render(render_id: str) -> str:
    """Poll until render completes. Returns the download URL."""
    elapsed = 0
    while elapsed < _MAX_POLL:
        time.sleep(_INTERVAL)
        elapsed += _INTERVAL
        resp = requests.get(f"{_API_URL}/{render_id}", headers=_HEADERS, timeout=15)
        resp.raise_for_status()
        data   = resp.json()
        status = data.get("status")
        logger.info("Creatomate %s: %s (%ds)", render_id, status, elapsed)
        if status == "succeeded":
            return data["url"]
        if status in ("failed", "canceled"):
            raise RuntimeError(f"Creatomate render {render_id} failed: {data.get('error')}")
    raise TimeoutError(f"Creatomate render {render_id} timed out after {_MAX_POLL}s")


def _download(url: str, output_path: Path) -> Path:
    resp = requests.get(url, stream=True, timeout=300)
    resp.raise_for_status()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "wb") as f:
        for chunk in resp.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info("Branded video saved: %s", output_path.name)
    return output_path


def apply_branding(raw_video_path: Path, item: NewsItem, script: Script) -> Path:
    """
    Apply Creatomate branding template to the raw presenter video.
    Returns path to the final branded video in storage/Videos/Final/.
    """
    suffix      = "short" if script.format == "short" else "final"
    output_path = settings.VIDEOS_FINAL_DIR / f"{script.news_id}_{suffix}_branded.mp4"

    if output_path.exists():
        logger.info("Branded video already exists, skipping: %s", output_path.name)
        return output_path

    render_id    = _submit_render(raw_video_path, item, script)
    download_url = _poll_render(render_id)
    return _download(download_url, output_path)
