"""
Buffer API social media poster.
Posts the 15-second short-form vertical clip to:
  - YouTube Shorts (via YouTube Data API v3)
  - TikTok, Instagram Reels, X (via Buffer API)

Captions and hashtags are auto-generated from the short script.
"""
import logging
from pathlib import Path

import requests
from openai import OpenAI

from config import settings
from modules.news_monitor import NewsItem
from modules.script_generator import Script

logger = logging.getLogger(__name__)

BUFFER_API_BASE = "https://api.bufferapp.com/1"

_CAPTION_PROMPT = """Write a punchy social media caption for a 15-second football news clip.

Script: {script_text}
Brand: {brand_name}

Rules:
- Max 150 characters for the caption text
- Include 5 highly relevant football hashtags at the end
- Tone: energetic, urgent, social-native
- End with: "Follow {brand_name}"

Return ONLY the caption text with hashtags. No labels."""


def _generate_caption(script: Script) -> str:
    try:
        client = OpenAI(api_key=settings.OPENAI_API_KEY)
        prompt = _CAPTION_PROMPT.format(
            script_text=script.text,
            brand_name=settings.BRAND_NAME,
        )
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=100,
            temperature=0.7,
        )
        return response.choices[0].message.content.strip()
    except Exception as e:
        logger.warning("Caption generation failed: %s", e)
        return f"Football news just in! Follow {settings.BRAND_NAME} for updates. #Football #FootballNews #Transfers"


def _upload_to_buffer(
    profile_id: str,
    caption: str,
    video_path: Path,
    platform_name: str,
) -> dict:
    """
    Posts a video update to Buffer for the given profile.
    Note: Buffer's video upload requires a two-step flow (upload → post).
    """
    # Step 1: Upload media to Buffer
    with open(video_path, "rb") as f:
        upload_response = requests.post(
            f"{BUFFER_API_BASE}/media/upload.json",
            headers={"Authorization": f"Bearer {settings.BUFFER_ACCESS_TOKEN}"},
            files={"file": (video_path.name, f, "video/mp4")},
            timeout=120,
        )
    upload_response.raise_for_status()
    media_id = upload_response.json().get("id")

    # Step 2: Create a Buffer post with the uploaded media
    post_response = requests.post(
        f"{BUFFER_API_BASE}/updates/create.json",
        headers={"Authorization": f"Bearer {settings.BUFFER_ACCESS_TOKEN}"},
        data={
            "profile_ids[]": profile_id,
            "text": caption,
            "media[video_id]": media_id,
            "now": "true",
        },
        timeout=30,
    )
    post_response.raise_for_status()
    logger.info("Posted to %s via Buffer", platform_name)
    return post_response.json()


def post_short_to_socials(
    short_video_path: Path,
    item: NewsItem,
    script: Script,
) -> None:
    """
    Posts the 15-second vertical video to all configured social platforms.
    """
    if not short_video_path.exists():
        logger.warning("Short video not found, skipping social post: %s", short_video_path)
        return

    caption = _generate_caption(script)
    logger.info("Caption generated for social post: %s", caption[:80])

    platforms = [
        (settings.BUFFER_PROFILE_ID_TIKTOK,    "TikTok"),
        (settings.BUFFER_PROFILE_ID_INSTAGRAM,  "Instagram Reels"),
        (settings.BUFFER_PROFILE_ID_TWITTER,    "X (Twitter)"),
        (settings.BUFFER_PROFILE_ID_YOUTUBE,    "YouTube Shorts"),
    ]

    for profile_id, platform_name in platforms:
        if not profile_id:
            logger.info("Skipping %s — no profile ID configured", platform_name)
            continue
        try:
            _upload_to_buffer(profile_id, caption, short_video_path, platform_name)
        except Exception as e:
            logger.error("Failed to post to %s: %s", platform_name, e)
