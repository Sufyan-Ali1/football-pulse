"""
Thumbnail generator.
Primary: Canva API (template-based branded thumbnails).
Fallback: Pillow (PIL) — generates a basic branded thumbnail programmatically
          when the Canva API is unavailable or misconfigured.
"""
import logging
from pathlib import Path

import requests

from config import settings
from modules.news_monitor import NewsItem
from modules.script_generator import Script
from pipeline.content_classifier import ContentType

logger = logging.getLogger(__name__)

CANVA_API_BASE = "https://api.canva.com/rest/v1"
CANVA_HEADERS = {
    "Authorization": f"Bearer {settings.CANVA_API_KEY}",
    "Content-Type": "application/json",
}

_BADGE_LABELS: dict[ContentType, str] = {
    "breaking_news":   "BREAKING NEWS",
    "transfer_rumour": "TRANSFER NEWS",
    "club_update":     "CLUB UPDATE",
    "tactical":        "TACTICAL ANALYSIS",
}


def _get_club_colour(item: NewsItem) -> str:
    text = (item.headline + " " + item.body[:200]).lower()
    for club, colour in settings.CLUB_COLOURS.items():
        if club != "default" and club in text:
            return colour
    return settings.CLUB_COLOURS["default"]


# ── Canva API ─────────────────────────────────────────────────────────────────

def _generate_canva_thumbnail(
    item: NewsItem,
    script: Script,
    output_path: Path,
) -> Path:
    badge = _BADGE_LABELS.get(script.script_type, "NEWS")
    headline_short = item.headline[:60] + ("…" if len(item.headline) > 60 else "")

    payload = {
        "design_id": settings.CANVA_THUMBNAIL_TEMPLATE_ID,
        "fields": [
            {"name": "headline",    "text": {"text": headline_short}},
            {"name": "badge",       "text": {"text": badge}},
            {"name": "brand-name",  "text": {"text": settings.BRAND_NAME}},
            {"name": "club-colour", "color": {"value": _get_club_colour(item)}},
        ],
        "export_format": "jpg",
        "quality": 90,
    }

    response = requests.post(
        f"{CANVA_API_BASE}/designs/{settings.CANVA_THUMBNAIL_TEMPLATE_ID}/autofill",
        json=payload,
        headers=CANVA_HEADERS,
        timeout=60,
    )
    response.raise_for_status()
    result = response.json()

    # Canva returns a job — poll for completion
    job_id = result.get("job", {}).get("id")
    if not job_id:
        raise RuntimeError("Canva did not return a job id")

    import time
    for _ in range(20):
        time.sleep(3)
        poll = requests.get(
            f"{CANVA_API_BASE}/autofills/{job_id}",
            headers=CANVA_HEADERS,
            timeout=15,
        )
        poll.raise_for_status()
        job = poll.json().get("job", {})
        if job.get("status") == "success":
            download_url = job["result"]["design"]["urls"]["default"]
            img_data = requests.get(download_url, timeout=60).content
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(img_data)
            logger.info("Canva thumbnail saved: %s", output_path.name)
            return output_path
        if job.get("status") == "failed":
            raise RuntimeError(f"Canva autofill job failed: {job}")

    raise TimeoutError("Canva thumbnail job timed out")


# ── Pillow fallback ───────────────────────────────────────────────────────────

def _hex_to_rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _generate_pillow_thumbnail(
    item: NewsItem,
    script: Script,
    output_path: Path,
) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    badge = _BADGE_LABELS.get(script.script_type, "NEWS")
    club_colour = _get_club_colour(item)
    bg_colour = _hex_to_rgb(club_colour)
    accent = (255, 255, 255)

    img = Image.new("RGB", (1280, 720), color=bg_colour)
    draw = ImageDraw.Draw(img)

    # Dark overlay strip for text readability
    draw.rectangle([(0, 400), (1280, 720)], fill=(0, 0, 0, 200))

    try:
        font_headline = ImageFont.truetype("arial.ttf", 52)
        font_badge = ImageFont.truetype("arial.ttf", 36)
        font_brand = ImageFont.truetype("arial.ttf", 28)
    except OSError:
        font_headline = ImageFont.load_default()
        font_badge = font_headline
        font_brand = font_headline

    # Badge
    draw.text((60, 420), badge, fill=(255, 200, 0), font=font_badge)

    # Headline (wrapped)
    words = item.headline.split()
    line, lines = "", []
    for word in words:
        if len(line + word) > 45:
            lines.append(line.strip())
            line = ""
        line += word + " "
    lines.append(line.strip())

    y = 475
    for line in lines[:2]:
        draw.text((60, y), line, fill=accent, font=font_headline)
        y += 62

    # Brand name
    draw.text((60, 670), settings.BRAND_NAME, fill=(180, 180, 180), font=font_brand)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "JPEG", quality=90)
    logger.info("Pillow fallback thumbnail saved: %s", output_path.name)
    return output_path


# ── Public interface ──────────────────────────────────────────────────────────

def generate_thumbnail(item: NewsItem, script: Script) -> Path:
    output_path = settings.THUMBNAILS_DIR / f"{script.news_id}_thumb.jpg"

    if output_path.exists():
        logger.info("Thumbnail already exists, skipping: %s", output_path.name)
        return output_path

    try:
        return _generate_canva_thumbnail(item, script, output_path)
    except Exception as e:
        logger.warning("Canva thumbnail failed (%s), using Pillow fallback", e)
        return _generate_pillow_thumbnail(item, script, output_path)
