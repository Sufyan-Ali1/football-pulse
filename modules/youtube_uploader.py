"""
YouTube Data API v3 uploader.
Uploads the final branded video, attaches the thumbnail,
auto-generates SEO metadata via GPT-4, and schedules the publish time.
"""
import logging
import pickle
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from openai import OpenAI

from config import settings
from modules.news_monitor import NewsItem
from modules.script_generator import Script

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]

# Max YouTube description length
_MAX_DESCRIPTION = 5000


@dataclass
class VideoMetadata:
    title: str
    description: str
    tags: list[str]
    category_id: str = "17"   # 17 = Sports
    privacy_status: str = "private"   # "private" until publish_at
    publish_at: str | None = None      # ISO 8601, triggers scheduled publish


def _get_youtube_client():
    creds = None
    token_path = settings.YOUTUBE_TOKEN_PATH

    if token_path.exists():
        with open(token_path, "rb") as f:
            creds = pickle.load(f)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(settings.YOUTUBE_CLIENT_SECRETS_PATH), SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(token_path, "wb") as f:
            pickle.dump(creds, f)

    return build("youtube", "v3", credentials=creds)


# ── Metadata generation ───────────────────────────────────────────────────────

_METADATA_PROMPT = """You are an SEO expert for a football YouTube channel called "{brand_name}".

Generate YouTube metadata for this video:
Content type: {content_type}
Script: {script_text}

Return VALID JSON with exactly these keys:
- "title": SEO-optimised YouTube title (max 95 chars, include club names and "Football News")
- "description": Engaging description (300-500 words) with hashtags at the end
- "tags": List of 15 relevant tags (strings)

JSON only. No markdown, no explanation."""


def generate_metadata(item: NewsItem, script: Script) -> VideoMetadata:
    client = OpenAI(api_key=settings.OPENAI_API_KEY)
    prompt = _METADATA_PROMPT.format(
        brand_name=settings.BRAND_NAME,
        content_type=script.script_type,
        script_text=script.text[:800],
    )
    try:
        import json
        response = client.chat.completions.create(
            model=settings.OPENAI_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.5,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)

        description = data.get("description", "")[:_MAX_DESCRIPTION]
        description += f"\n\n{settings.BRAND_NAME} – {settings.BRAND_TAGLINE}"

        return VideoMetadata(
            title=data.get("title", item.headline)[:95],
            description=description,
            tags=data.get("tags", ["football", "football news"])[:30],
        )
    except Exception as e:
        logger.warning("Metadata generation failed: %s — using fallback", e)
        return VideoMetadata(
            title=item.headline[:95],
            description=f"{item.headline}\n\nSource: {item.source}\n\n{settings.BRAND_NAME} – {settings.BRAND_TAGLINE}",
            tags=["football", "football news", "transfer news", settings.BRAND_NAME.lower()],
        )


# ── Upload ────────────────────────────────────────────────────────────────────

def _next_publish_time() -> str:
    """
    Returns an ISO 8601 timestamp for the next available publish slot.
    Schedules videos at least 5 minutes in the future, spread ~30 min apart.
    (A more advanced scheduler would check existing slots.)
    """
    dt = datetime.now(timezone.utc) + timedelta(minutes=5)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


def upload_video(
    video_path: Path,
    thumbnail_path: Path,
    item: NewsItem,
    script: Script,
    schedule: bool = True,
) -> str:
    """
    Uploads a video to YouTube with metadata and thumbnail.
    Returns the YouTube video ID.
    """
    metadata = generate_metadata(item, script)
    if schedule:
        metadata.publish_at = _next_publish_time()

    youtube = _get_youtube_client()

    body = {
        "snippet": {
            "title": metadata.title,
            "description": metadata.description,
            "tags": metadata.tags,
            "categoryId": metadata.category_id,
        },
        "status": {
            "privacyStatus": "private",
            **({"publishAt": metadata.publish_at} if metadata.publish_at else {}),
        },
    }

    media = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    request = youtube.videos().insert(
        part="snippet,status",
        body=body,
        media_body=media,
    )

    response = None
    while response is None:
        _, response = request.next_chunk()

    video_id = response["id"]
    logger.info("YouTube upload complete. video_id=%s title='%s'", video_id, metadata.title)

    # Attach thumbnail
    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg"),
        ).execute()
        logger.info("Thumbnail attached to %s", video_id)
    except Exception as e:
        logger.warning("Thumbnail upload failed for %s: %s", video_id, e)

    return video_id
