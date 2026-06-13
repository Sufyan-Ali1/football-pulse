"""
AI thumbnail generation for YouTube uploads.

The Vertex Imagen output is treated as the final thumbnail artifact. The code
does not overlay local branding/text or generate fallback thumbnails.
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

_VERTEX_IMAGEN_API_URL = (
    "https://{location}-aiplatform.googleapis.com/v1/"
    "projects/{project}/locations/{location}/publishers/google/models/{model}:predict"
)
_CANVAS_SIZE = (settings.THUMBNAIL_WIDTH, settings.THUMBNAIL_HEIGHT)
_LOGO_PATH = settings.BASE_DIR / "config" / "images" / "logo.png"
_RATE_LIMIT_RETRY_DELAYS = (4, 10)
_groq = get_groq_client()

_THUMBNAIL_PLAN_PROMPT = """You are the thumbnail strategist for a football YouTube channel called "{brand_name}".

Your task is to write one production-ready image-generation prompt for a COMPLETE football YouTube thumbnail.

Inputs:
- Focus mode: {focus_mode}
- Stories:
{stories_block}
- Logo reference available locally: {logo_reference}

Return VALID JSON with exactly this key:
- "image_prompt": one detailed premium prompt for a COMPLETE Vertex Imagen thumbnail image

Rules:
- Pick the strongest and most clickable angle across all stories, not just story 1.
- The image_prompt is the only required output. Do not summarize the news separately.
- The image_prompt must include everything Imagen needs:
  - the strongest thumbnail angle
  - 1 or 2 relevant famous football subjects
  - their expression, pose, and visual importance
  - the correct story framing such as shock, rivalry, injury, confirmation, squad update, or match alert
  - the football setting and World Cup context when relevant
  - premium sports-broadcast composition guidance
  - black, neon-green, and white Football Pulse visual mood
  - dramatic lighting, stadium atmosphere, smoke, broadcast HUD/tactical elements if helpful
  - the exact visible hook text that should appear inside the thumbnail image
  - text placement guidance so the hook remains large and readable on mobile
- The image_prompt must instruct the model to create the COMPLETE thumbnail, not only a background.
- The image_prompt must instruct the model to place the Football Pulse brand mark/logo in the lower-right corner, matching the provided logo reference as closely as possible.
- The image_prompt must explicitly say no watermark.
- Prefer globally recognizable players only when they are relevant to the chosen angle.
- Do not invent unrelated players or false facts.

JSON only. No markdown, no explanation."""


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

    plan = _build_thumbnail_plan(items, scripts, focus_mode)
    prompt = str(plan["image_prompt"]).strip()
    logger.info("Thumbnail prompt start for '%s'", items[0].headline[:90])
    logger.info("Vertex Imagen prompt:\n%s", prompt)
    logger.info("Thumbnail prompt ready (%d chars)", len(prompt))

    generated_path = _generate_vertex_imagen_image(prompt, output_dir, output_stem)
    if not generated_path:
        logger.warning("AI thumbnail generation failed for %s", output_stem)
        return None

    logger.info("Thumbnail image selected: %s", generated_path.name)
    final_path = output_dir / f"{output_stem}_thumbnail.png"
    _finalize_generated_thumbnail(generated_path, final_path)
    logger.info("Thumbnail saved without local overlays: %s", final_path)
    return final_path


def create_test_thumbnail_from_prompt(
    prompt: str,
    output_stem: str = "test_thumbnail",
    hook_text: str = "HUGE WORLD CUP UPDATE",
    kicker: str = "FIFA WORLD CUP",
    source_label: str = "Football Pulse",
) -> Path | None:
    del hook_text, kicker, source_label

    if not settings.THUMBNAIL_ENABLED:
        logger.info("Thumbnail generation disabled")
        return None

    output_dir = settings.THUMBNAILS_DIR / output_stem
    output_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Test thumbnail prompt ready (%d chars)", len(prompt))
    logger.info("Vertex Imagen prompt:\n%s", prompt)
    generated_path = _generate_vertex_imagen_image(
        prompt,
        output_dir,
        output_stem,
        candidate_count=1,
    )
    if not generated_path:
        logger.warning("Test thumbnail AI image generation failed for %s", output_stem)
        return None

    logger.info("Test thumbnail image selected: %s", generated_path.name)
    final_path = output_dir / f"{output_stem}_thumbnail.png"
    _finalize_generated_thumbnail(generated_path, final_path)
    logger.info("Test thumbnail saved without local overlays: %s", final_path)
    return final_path


def _build_thumbnail_prompt(item: NewsItem, script: Script | None, focus_mode: str) -> str:
    story_text = script.text if script else item.body
    body_snippet = _sanitize_prompt_text(story_text)[:420]
    headline = _sanitize_prompt_text(item.headline)
    hook_text = _extract_hook_text(item, script, focus_mode)[:28]
    focus_line = (
        "Topic focus: FIFA World Cup breaking football news. "
        if focus_mode == "world_cup"
        else "Topic focus: breaking football news. "
    )
    logo_hint = (
        "Use the provided Football Pulse logo reference as the lower-right corner brand mark. "
        if _LOGO_PATH.exists()
        else "Reserve the lower-right corner for a Football Pulse style brand mark. "
    )
    return (
        "Create a dramatic 16:9 COMPLETE YouTube thumbnail for a football breaking-news video. "
        f"{focus_line}"
        f'The thumbnail must visibly show the hook text "{hook_text}" in big, bold, highly readable lettering. '
        "Use a premium sports-broadcast style, sharp subject focus, stadium atmosphere, high contrast, "
        "clean composition, dynamic energy, and mobile-friendly text placement. "
        f"{logo_hint}"
        "Do not add any watermark. "
        "Color direction: deep blacks, dark greens, vivid green highlights, subtle white accents. "
        f"Headline context: {headline}. "
        f"Story context: {body_snippet}"
    )


def _build_thumbnail_plan(
    items: list[NewsItem],
    scripts: list[Script],
    focus_mode: str,
) -> dict:
    lead_item = items[0]
    lead_script = scripts[0] if scripts else None
    fallback = {
        "image_prompt": _build_thumbnail_prompt(lead_item, lead_script, focus_mode),
    }

    story_lines = []
    for idx, item in enumerate(items, start=1):
        script = scripts[idx - 1] if idx - 1 < len(scripts) else None
        summary = _sanitize_prompt_text(script.text if script else item.body)[:260]
        story_lines.append(
            f"{idx}. Headline: {item.headline}\n"
            f"   Source: {item.source}\n"
            f"   Summary: {summary}"
        )

    prompt = _THUMBNAIL_PLAN_PROMPT.format(
        brand_name=settings.BRAND_NAME,
        focus_mode=focus_mode or "general_football",
        stories_block="\n".join(story_lines),
        logo_reference="Football Pulse logo file is available for reference." if _LOGO_PATH.exists() else "No local logo file available.",
    )
    logger.info("Groq thumbnail planner prompt:\n%s", prompt)

    try:
        response = _groq.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=900,
            temperature=0.55,
            response_format={"type": "json_object"},
        )
        raw_content = response.choices[0].message.content
        logger.info("Groq thumbnail planner raw response:\n%s", raw_content)
        data = json.loads(raw_content)
        image_prompt = str(data.get("image_prompt", "")).strip() or fallback["image_prompt"]
        logger.info("Groq thumbnail planner selected image prompt:\n%s", image_prompt)
        return {"image_prompt": image_prompt}
    except Exception as exc:
        logger.warning("Thumbnail plan generation failed: %s - using fallback prompt only", exc)
        logger.info("Groq thumbnail planner fallback image prompt:\n%s", fallback["image_prompt"])
        return fallback


def _generate_vertex_imagen_image(
    prompt: str,
    output_dir: Path,
    output_stem: str,
    candidate_count: int | None = None,
) -> Path | None:
    if not settings.GOOGLE_CLOUD_PROJECT:
        logger.warning("Vertex thumbnail generation skipped: GOOGLE_CLOUD_PROJECT missing")
        return None

    total_candidates = candidate_count or settings.THUMBNAIL_CANDIDATES
    generated_paths: list[Path] = []
    for index in range(total_candidates):
        logger.info("Thumbnail API call %d/%d start", index + 1, total_candidates)
        try:
            image = _call_vertex_imagen_api(prompt)
            candidate_path = output_dir / f"{output_stem}_candidate_{index + 1}.png"
            image.save(candidate_path, format="PNG")
            logger.info("Thumbnail API call %d saved: %s", index + 1, candidate_path.name)
            generated_paths.append(candidate_path)
        except Exception as exc:
            logger.warning("Thumbnail API call %d failed: %s", index + 1, exc)
    return generated_paths[0] if generated_paths else None


def _call_vertex_imagen_api(prompt: str) -> Image.Image:
    payload = _build_google_image_payload(prompt)
    url = _VERTEX_IMAGEN_API_URL.format(
        location=settings.GOOGLE_CLOUD_LOCATION,
        project=settings.GOOGLE_CLOUD_PROJECT,
        model=settings.THUMBNAIL_MODEL,
    )
    token = _get_vertex_access_token()
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    for attempt in range(len(_RATE_LIMIT_RETRY_DELAYS) + 1):
        response = requests.post(url, headers=headers, json=payload, timeout=90)
        try:
            response.raise_for_status()
            data = response.json()
            image_bytes = _extract_image_bytes(data)
            return Image.open(io.BytesIO(image_bytes)).convert("RGB")
        except requests.HTTPError as exc:
            status = response.status_code
            body = _format_google_error_body(response)
            if status == 429 and attempt < len(_RATE_LIMIT_RETRY_DELAYS):
                delay = _RATE_LIMIT_RETRY_DELAYS[attempt]
                logger.warning(
                    "Vertex Imagen rate-limited for model %s. Retry %d in %ss. Response: %s",
                    settings.THUMBNAIL_MODEL,
                    attempt + 1,
                    delay,
                    body,
                )
                time.sleep(delay)
                continue
            raise RuntimeError(
                f"Vertex Imagen API {status} for model {settings.THUMBNAIL_MODEL}: {body}"
            ) from exc

    raise RuntimeError(f"Vertex Imagen API failed for model {settings.THUMBNAIL_MODEL}")


def _get_vertex_access_token() -> str:
    creds, project = google_auth_default(scopes=["https://www.googleapis.com/auth/cloud-platform"])
    if not settings.GOOGLE_CLOUD_PROJECT and project:
        logger.info("Using ADC project for Vertex thumbnail generation: %s", project)
    if not creds.valid:
        creds.refresh(GoogleAuthRequest())
    token = getattr(creds, "token", None)
    if not token:
        raise RuntimeError(
            "Vertex auth failed. Set GOOGLE_APPLICATION_CREDENTIALS or run "
            "'gcloud auth application-default login'."
        )
    return token


def _build_google_image_payload(prompt: str) -> dict:
    return {
        "instances": [
            {
                "prompt": prompt,
            }
        ],
        "parameters": {
            "sampleCount": 1,
            "aspectRatio": "16:9",
            "personGeneration": "allow_adult",
        },
    }


def _extract_image_bytes(data: dict) -> bytes:
    predictions = data.get("predictions") or []
    for prediction in predictions:
        bytes_base64 = (
            prediction.get("bytesBase64Encoded")
            or prediction.get("bytes_base64_encoded")
            or prediction.get("image", {}).get("imageBytes")
        )
        if bytes_base64:
            return base64.b64decode(bytes_base64)
    raise ValueError("Imagen response did not include generated image bytes")


def _format_google_error_body(response: requests.Response) -> str:
    try:
        data = response.json()
    except ValueError:
        return response.text[:500].strip() or "<empty response body>"
    error = data.get("error")
    if isinstance(error, dict):
        message = error.get("message", "")
        status = error.get("status", "")
        details = error.get("details", [])
        details_text = f" details={details}" if details else ""
        return f"{status}: {message}{details_text}".strip()
    return str(data)[:500]


def _finalize_generated_thumbnail(generated_path: Path, output_path: Path) -> None:
    with Image.open(generated_path) as generated:
        final = _cover_resize(generated.convert("RGB"), _CANVAS_SIZE)
        final.save(output_path, format="PNG", optimize=True)


def _extract_hook_text(item: NewsItem, script: Script | None, focus_mode: str) -> str:
    source = item.headline
    if script and script.display_headline:
        source = script.display_headline
    cleaned = re.sub(r"\s+", " ", source).strip()
    cleaned = re.sub(r"\b(FIFA WORLD CUP|WORLD CUP|BREAKING NEWS)\b[:\- ]*", "", cleaned, flags=re.I).strip()
    cleaned = cleaned.replace("|", " ")
    cleaned = re.sub(r"[\"'`]", "", cleaned)
    if focus_mode == "world_cup" and "world cup" not in cleaned.lower():
        cleaned = f"World Cup: {cleaned}"
    return cleaned[:70].upper()


def _cover_resize(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    target_w, target_h = size
    scale = max(target_w / image.width, target_h / image.height)
    resized = image.resize((max(1, int(image.width * scale)), max(1, int(image.height * scale))), Image.LANCZOS)
    left = max(0, (resized.width - target_w) // 2)
    top = max(0, (resized.height - target_h) // 2)
    return resized.crop((left, top, left + target_w, top + target_h))


def _sanitize_prompt_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").replace("\n", " ")).strip()
