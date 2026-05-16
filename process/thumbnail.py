"""
Thumbnail generator — Step 8.

Primary:  Canva API (template-based branded thumbnails).
Fallback: Pillow — generates a basic branded thumbnail programmatically
          if Canva is unavailable or not yet configured.

Output saved to storage/Thumbnails/{news_id}_thumb.jpg
"""
import logging
import time
from pathlib import Path

import requests

from config import settings
from core.constants import BADGE_LABELS
from core.types import NewsItem, Script

logger = logging.getLogger(__name__)

_CANVA_BASE = "https://api.canva.com/rest/v1"
_CANVA_HDR  = {
    "Authorization": f"Bearer {settings.CANVA_API_KEY}",
    "Content-Type":  "application/json",
}


def _club_colour(item: NewsItem) -> str:
    text = (item.headline + " " + item.body[:200]).lower()
    for club, colour in settings.CLUB_COLOURS.items():
        if club != "default" and club in text:
            return colour
    return settings.CLUB_COLOURS["default"]


# ── Canva API ─────────────────────────────────────────────────────────────────

def _canva_thumbnail(item: NewsItem, script: Script, output_path: Path) -> Path:
    badge    = BADGE_LABELS.get(script.script_type, "NEWS")
    headline = item.headline[:60] + ("…" if len(item.headline) > 60 else "")
    payload  = {
        "design_id": settings.CANVA_THUMBNAIL_TEMPLATE_ID,
        "fields": [
            {"name": "headline",    "text":  {"text": headline}},
            {"name": "badge",       "text":  {"text": badge}},
            {"name": "brand-name",  "text":  {"text": settings.BRAND_NAME}},
            {"name": "club-colour", "color": {"value": _club_colour(item)}},
        ],
        "export_format": "jpg",
        "quality": 90,
    }
    resp = requests.post(
        f"{_CANVA_BASE}/designs/{settings.CANVA_THUMBNAIL_TEMPLATE_ID}/autofill",
        json=payload, headers=_CANVA_HDR, timeout=60,
    )
    resp.raise_for_status()
    job_id = resp.json().get("job", {}).get("id")
    if not job_id:
        raise RuntimeError("Canva did not return a job id")

    for _ in range(20):
        time.sleep(3)
        poll = requests.get(f"{_CANVA_BASE}/autofills/{job_id}", headers=_CANVA_HDR, timeout=15)
        poll.raise_for_status()
        job = poll.json().get("job", {})
        if job.get("status") == "success":
            url      = job["result"]["design"]["urls"]["default"]
            img_data = requests.get(url, timeout=60).content
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(img_data)
            logger.info("Canva thumbnail saved: %s", output_path.name)
            return output_path
        if job.get("status") == "failed":
            raise RuntimeError(f"Canva autofill failed: {job}")

    raise TimeoutError("Canva thumbnail job timed out")


# ── Pillow fallback ───────────────────────────────────────────────────────────

def _hex_to_rgb(hex_colour: str) -> tuple[int, int, int]:
    h = hex_colour.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _pillow_thumbnail(item: NewsItem, script: Script, output_path: Path) -> Path:
    from PIL import Image, ImageDraw, ImageFont

    badge      = BADGE_LABELS.get(script.script_type, "NEWS")
    bg_colour  = _hex_to_rgb(_club_colour(item))
    img        = Image.new("RGB", (1280, 720), color=bg_colour)
    draw       = ImageDraw.Draw(img)

    draw.rectangle([(0, 400), (1280, 720)], fill=(0, 0, 0, 200))

    try:
        font_big    = ImageFont.truetype("arial.ttf", 52)
        font_badge  = ImageFont.truetype("arial.ttf", 36)
        font_brand  = ImageFont.truetype("arial.ttf", 28)
    except OSError:
        font_big = font_badge = font_brand = ImageFont.load_default()

    draw.text((60, 420), badge, fill=(255, 200, 0), font=font_badge)

    words, line, lines = item.headline.split(), "", []
    for word in words:
        if len(line + word) > 45:
            lines.append(line.strip())
            line = ""
        line += word + " "
    lines.append(line.strip())

    y = 475
    for text_line in lines[:2]:
        draw.text((60, y), text_line, fill=(255, 255, 255), font=font_big)
        y += 62

    draw.text((60, 670), settings.BRAND_NAME, fill=(180, 180, 180), font=font_brand)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(output_path, "JPEG", quality=90)
    logger.info("Pillow thumbnail saved: %s", output_path.name)
    return output_path


# ── Public interface ──────────────────────────────────────────────────────────

def generate_thumbnail(item: NewsItem, script: Script) -> Path:
    """Generate a thumbnail. Tries Canva first, falls back to Pillow."""
    output_path = settings.THUMBNAILS_DIR / f"{script.news_id}_thumb.jpg"

    if output_path.exists():
        logger.info("Thumbnail already exists, skipping: %s", output_path.name)
        return output_path

    try:
        return _canva_thumbnail(item, script, output_path)
    except Exception as e:
        logger.warning("Canva failed (%s) — using Pillow fallback", e)
        return _pillow_thumbnail(item, script, output_path)
