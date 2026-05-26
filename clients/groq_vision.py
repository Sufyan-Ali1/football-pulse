"""
Groq vision API client.
Sends a PIL image frame to Groq's vision model and returns
a plain-text description + keyword list for clip indexing.
"""
import base64
import logging
from io import BytesIO

import requests
from PIL import Image

from config import settings

logger = logging.getLogger(__name__)

_PROMPT = (
    "You are a sports video analyst. You are looking at three frames taken at "
    "25%, 50%, and 75% through the same video clip.\n"
    "Based on all three frames together, describe the clip in one sentence (max 20 words). "
    "Focus on the visual content: action, people, setting, objects.\n"
    "Then list exactly 5 relevant keywords.\n\n"
    "Respond in this exact format — no extra text:\n"
    "DESCRIPTION: <one sentence>\n"
    "KEYWORDS: <word1>, <word2>, <word3>, <word4>, <word5>"
)


def describe_frame(frames: list[Image.Image]) -> tuple[str, str]:
    """Send 3 PIL frames from the same clip to Groq Vision and return (description, keywords).

    Returns ('', '') on failure so callers can use a safe fallback.
    """
    groq_key = getattr(settings, "GROQ_API_KEY", "")
    if not groq_key:
        logger.warning("GROQ_API_KEY not set — skipping vision description")
        return "", ""

    content: list[dict] = []
    for image in frames:
        buf = BytesIO()
        image.convert("RGB").save(buf, format="JPEG", quality=85)
        b64 = base64.b64encode(buf.getvalue()).decode()
        content.append({
            "type": "image_url",
            "image_url": {"url": f"data:image/jpeg;base64,{b64}"},
        })
    content.append({"type": "text", "text": _PROMPT})

    try:
        resp = requests.post(
            "https://api.groq.com/openai/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {groq_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": settings.GROQ_VISION_MODEL,
                "messages": [{"role": "user", "content": content}],
                "max_tokens": 120,
                "temperature": 0.2,
            },
            timeout=30,
        )
        resp.raise_for_status()
        text = resp.json()["choices"][0]["message"]["content"].strip()
        desc, kws = _parse(text)
        logger.info("Vision: %r | kws: %r", desc, kws)
        return desc, kws

    except Exception as exc:
        logger.warning("Groq vision call failed: %s", exc)
        return "", ""


def _parse(text: str) -> tuple[str, str]:
    desc, kws = "", ""
    for line in text.splitlines():
        if line.startswith("DESCRIPTION:"):
            desc = line[len("DESCRIPTION:"):].strip()
        elif line.startswith("KEYWORDS:"):
            kws = line[len("KEYWORDS:"):].strip()
    return desc, kws
