"""
AI thumbnail generation for YouTube uploads.

Flow:
  1. Groq receives all news stories and writes a complete, detailed Gemini image prompt
     that describes hook text, player, layout, effects, and logo placement.
  2. Gemini 2.0 Flash (Vertex AI) receives the prompt + the actual logo.png image
     and generates the complete 1280x720 thumbnail in one shot.
  3. The result is resized/cropped to exact canvas size and saved.
"""
from __future__ import annotations

import base64
import io
import json
import logging
import re
import time
from pathlib import Path

import requests
from PIL import Image
from google.auth import default as google_auth_default
from google.auth.transport.requests import Request as GoogleAuthRequest

from clients.groq_client import get_groq_client
from config import settings
from core.types import NewsItem, Script

logger = logging.getLogger(__name__)

_CANVAS_SIZE = (settings.THUMBNAIL_WIDTH, settings.THUMBNAIL_HEIGHT)
_LOGO_PATH   = settings.BASE_DIR / "config" / "images" / "logo.png"
_groq        = get_groq_client()

# Gemini model on Vertex AI that supports image input + image output
_GEMINI_MODEL = settings.THUMBNAIL_GEMINI_MODEL

# ── Groq planner prompt ───────────────────────────────────────────────────────

_THUMBNAIL_PLAN_PROMPT = """You are the thumbnail creative director for a football YouTube channel called "{brand_name}".

Your task: write ONE complete, production-ready image generation prompt for Gemini that will produce a premium clickbait-style football YouTube thumbnail.

A Football Pulse logo image is attached. The prompt MUST instruct Gemini to place that exact logo in the bottom-right corner of the thumbnail.

Inputs:
- Focus mode: {focus_mode}
- Stories:
{stories_block}

Return VALID JSON with exactly one key:
- "image_prompt": the complete Gemini image generation prompt (minimum 300 words, describe everything)

The image_prompt MUST cover ALL of these sections in detail:

━━ 1. HOOK TEXT ━━
Pick the single most clickbait-worthy 2-6 word hook from the stories (ALL CAPS).
Stack it on 2 lines maximum (e.g. "HUGE FIFA\\nUPDATE!" or "WORLD CUP\\nSHOCKER!").
Describe it as: massive bold Impact/condensed white text, neon green glow shadow behind each letter, thick black stroke outline, positioned in the center-right zone of the image, text height roughly 35-40% of total image height so it dominates the frame and is readable on mobile.

━━ 2. SUBJECT ━━
Choose 1 (or 2 for rivalry stories) globally famous football player(s) directly relevant to the story.
Describe: full name, pose (waist-up, looking at camera or reacting with strong visible emotion matching the story — shock/celebration/anger/determination), sharp focus, dramatic front-right directional stadium lighting, slight motion blur on background only.
Player fills the left 35-40% of the frame.

━━ 3. LAYOUT & COMPOSITION ━━
- Left 38%: player, brightly lit, sharp
- Center-right 56%: very dark clean zone — deep black to dark forest-green vertical gradient — so the white hook text sits on a dark background and is maximally readable
- Bottom-right corner (about 12% of image height): the Football Pulse logo from the provided reference image, placed here with a subtle neon green circular glow around it
- 16:9 aspect ratio, 1280x720

━━ 4. BACKGROUND ━━
Dark football stadium at night. Out-of-focus crowd bokeh lights. Dramatic green floodlights. Atmospheric smoke and haze. Adds depth without competing with the text.

━━ 5. VISUAL EFFECTS ━━
Neon green (#39FF14) particle sparks and energy streaks emanating from the player toward the center of the frame. Thin broadcast HUD lines at the edges. Subtle green glow/aura around the player for separation. High contrast cinematic sports broadcast look. Premium YouTube thumbnail quality.

━━ 6. LOGO ━━
"In the bottom-right corner, place the Football Pulse logo exactly as shown in the provided reference image. Size: approximately 12-14% of the total image height. Add a subtle soft neon green circular glow around the logo for visibility against the dark background."

━━ 7. ABSOLUTE RULES ━━
- Do NOT include any watermarks
- Do NOT add any text other than the hook text described above
- Do NOT invent players unrelated to the story
- Do NOT use bright or busy backgrounds that compete with text readability
- Do NOT add extra logos or branding beyond the Football Pulse logo in the corner

JSON only. No markdown. No explanation outside the JSON."""


# ── Public entry points ───────────────────────────────────────────────────────

def create_roundup_thumbnail(
    items: list[NewsItem],
    scripts: list[Script],
    output_stem: str,
    focus_mode: str = "",
) -> Path | None:
    if not settings.THUMBNAIL_ENABLED:
        logger.info("Thumbnail generation disabled")
        return None
    if not items:
        logger.warning("Thumbnail generation skipped: no stories provided")
        return None

    output_dir = settings.THUMBNAILS_DIR / output_stem
    output_dir.mkdir(parents=True, exist_ok=True)

    prompt = _build_thumbnail_prompt_via_groq(items, scripts, focus_mode)
    if not prompt:
        logger.warning("Thumbnail prompt generation failed for %s", output_stem)
        return None

    logger.info("Sending to Gemini for thumbnail generation ...")
    image = _generate_gemini_image(prompt, _LOGO_PATH)
    if not image:
        logger.warning("Gemini thumbnail generation failed for %s", output_stem)
        return None

    final_path = output_dir / f"{output_stem}_thumbnail.png"
    _save_thumbnail(image, final_path)
    logger.info("Thumbnail saved: %s", final_path)
    return final_path


# ── Groq: build the Gemini prompt ────────────────────────────────────────────

def _build_thumbnail_prompt_via_groq(
    items: list[NewsItem],
    scripts: list[Script],
    focus_mode: str,
) -> str | None:
    story_lines = []
    for idx, item in enumerate(items, start=1):
        script = scripts[idx - 1] if idx - 1 < len(scripts) else None
        summary = _sanitize(script.text if script else item.body)[:300]
        story_lines.append(
            f"{idx}. Headline: {item.headline}\n"
            f"   Source: {item.source}\n"
            f"   Summary: {summary}"
        )

    groq_prompt = _THUMBNAIL_PLAN_PROMPT.format(
        brand_name=settings.BRAND_NAME,
        focus_mode=focus_mode or "general_football",
        stories_block="\n".join(story_lines),
    )
    logger.info("Groq thumbnail planner prompt:\n%s", groq_prompt)

    try:
        response = _groq.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": groq_prompt}],
            max_tokens=1200,
            temperature=0.6,
            response_format={"type": "json_object"},
        )
        raw = response.choices[0].message.content
        logger.info("Groq thumbnail planner response:\n%s", raw)
        data = json.loads(raw)
        prompt = str(data.get("image_prompt", "")).strip()
        if not prompt:
            raise ValueError("image_prompt key is empty")
        logger.info("Gemini image prompt (%d chars):\n%s", len(prompt), prompt)
        return prompt
    except Exception as exc:
        logger.warning("Groq thumbnail planner failed: %s", exc)
        return None


# ── Gemini: generate the image ────────────────────────────────────────────────

def _generate_gemini_image(prompt: str, logo_path: Path | None = None) -> Image.Image | None:
    """Call Gemini 2.0 Flash on Vertex AI with prompt + logo, return PIL image."""
    if not settings.GOOGLE_CLOUD_PROJECT:
        logger.warning("Gemini thumbnail skipped: GOOGLE_CLOUD_PROJECT not set")
        return None

    url = (
        f"https://{settings.GOOGLE_CLOUD_LOCATION}-aiplatform.googleapis.com/v1/"
        f"projects/{settings.GOOGLE_CLOUD_PROJECT}/locations/{settings.GOOGLE_CLOUD_LOCATION}/"
        f"publishers/google/models/{_GEMINI_MODEL}:generateContent"
    )

    parts: list[dict] = [{"text": prompt}]

    if logo_path and logo_path.exists():
        logo_b64 = base64.b64encode(logo_path.read_bytes()).decode("utf-8")
        mime = "image/png" if logo_path.suffix.lower() == ".png" else "image/jpeg"
        parts.append({"inlineData": {"mimeType": mime, "data": logo_b64}})
        logger.info("Logo attached to Gemini request: %s", logo_path.name)
    else:
        logger.warning("Logo not found at %s — generating without logo reference", logo_path)

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {"responseModalities": ["IMAGE", "TEXT"]},
    }

    token = _get_vertex_access_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    for attempt in range(3):
        resp = requests.post(url, headers=headers, json=payload, timeout=180)
        try:
            resp.raise_for_status()
        except requests.HTTPError:
            status = resp.status_code
            if status == 429 and attempt < 2:
                delay = (attempt + 1) * 10
                logger.warning("Gemini rate-limited — retrying in %ds", delay)
                time.sleep(delay)
                continue
            logger.error("Gemini API %d: %s", status, resp.text[:800])
            return None

        data = resp.json()
        image = _extract_image_from_gemini_response(data)
        if image:
            return image
        logger.warning("Gemini returned no image on attempt %d: %s", attempt + 1, str(data)[:400])
        break

    return None


def _extract_image_from_gemini_response(data: dict) -> Image.Image | None:
    """Pull the generated image out of a Gemini generateContent response."""
    for candidate in data.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            inline = part.get("inlineData") or part.get("inline_data") or {}
            b64    = inline.get("data", "")
            mime   = inline.get("mimeType", "")
            if b64 and "image" in mime:
                return Image.open(io.BytesIO(base64.b64decode(b64))).convert("RGB")
    return None


# ── Save ──────────────────────────────────────────────────────────────────────

def _save_thumbnail(image: Image.Image, output_path: Path) -> None:
    final = _cover_resize(image, _CANVAS_SIZE)
    final.save(output_path, format="PNG", optimize=True)


# ── Auth ──────────────────────────────────────────────────────────────────────

def _get_vertex_access_token() -> str:
    creds, project = google_auth_default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not settings.GOOGLE_CLOUD_PROJECT and project:
        logger.info("Using ADC project: %s", project)
    if not creds.valid:
        creds.refresh(GoogleAuthRequest())
    token = getattr(creds, "token", None)
    if not token:
        raise RuntimeError(
            "Vertex auth failed. Run 'gcloud auth application-default login'."
        )
    return token


# ── Helpers ───────────────────────────────────────────────────────────────────

def _cover_resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    tw, th = size
    scale   = max(tw / image.width, th / image.height)
    resized = image.resize(
        (max(1, int(image.width * scale)), max(1, int(image.height * scale))),
        Image.LANCZOS,
    )
    left = max(0, (resized.width - tw) // 2)
    top  = max(0, (resized.height - th) // 2)
    return resized.crop((left, top, left + tw, top + th))


def _sanitize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()


def _extract_hook_text(item: NewsItem, script: Script | None, focus_mode: str) -> str:
    source  = script.display_headline if (script and script.display_headline) else item.headline
    cleaned = re.sub(r"\s+", " ", source).strip()
    cleaned = re.sub(r"\b(FIFA WORLD CUP|WORLD CUP|BREAKING NEWS)\b[:\- ]*", "", cleaned, flags=re.I).strip()
    cleaned = cleaned.replace("|", " ")
    cleaned = re.sub(r"[\"'`]", "", cleaned)
    if focus_mode == "world_cup" and "world cup" not in cleaned.lower():
        cleaned = f"World Cup: {cleaned}"
    return cleaned[:70].upper()
