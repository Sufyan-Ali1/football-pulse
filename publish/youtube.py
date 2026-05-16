"""
YouTube uploader — Step 9.

Uploads the final branded video, attaches the thumbnail,
auto-generates SEO metadata via Groq, and schedules publish time.
"""
import json
import logging
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from openai import OpenAI

from config import settings
from core.types import NewsItem, Script, VideoMetadata

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
]
_groq = OpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")


def _get_youtube_client():
    creds = None
    if settings.YOUTUBE_TOKEN_PATH.exists():
        with open(settings.YOUTUBE_TOKEN_PATH, "rb") as f:
            creds = pickle.load(f)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow  = InstalledAppFlow.from_client_secrets_file(
                str(settings.YOUTUBE_CLIENT_SECRETS_PATH), _SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open(settings.YOUTUBE_TOKEN_PATH, "wb") as f:
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
    prompt = _METADATA_PROMPT.format(
        brand_name=settings.BRAND_NAME,
        content_type=script.script_type,
        script_text=script.text[:800],
    )
    try:
        resp = _groq.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.5,
        )
        data        = json.loads(resp.choices[0].message.content)
        description = data.get("description", "")[:5000]
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


def _next_publish_time() -> str:
    dt = datetime.now(timezone.utc) + timedelta(minutes=5)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.000Z")


# ── Upload ────────────────────────────────────────────────────────────────────

def upload_video(
    video_path: Path,
    thumbnail_path: Path,
    item: NewsItem,
    script: Script,
    schedule: bool = True,
) -> str:
    """
    Upload a video to YouTube with auto-generated metadata and thumbnail.
    Returns the YouTube video ID.
    """
    metadata = generate_metadata(item, script)
    if schedule:
        metadata.publish_at = _next_publish_time()

    youtube = _get_youtube_client()
    body    = {
        "snippet": {
            "title":       metadata.title,
            "description": metadata.description,
            "tags":        metadata.tags,
            "categoryId":  metadata.category_id,
        },
        "status": {
            "privacyStatus": "private",
            **({"publishAt": metadata.publish_at} if metadata.publish_at else {}),
        },
    }

    media    = MediaFileUpload(str(video_path), mimetype="video/mp4", resumable=True)
    request  = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
    response = None
    while response is None:
        _, response = request.next_chunk()

    video_id = response["id"]
    logger.info("YouTube upload complete: %s | '%s'", video_id, metadata.title)

    try:
        youtube.thumbnails().set(
            videoId=video_id,
            media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg"),
        ).execute()
        logger.info("Thumbnail attached to %s", video_id)
    except Exception as e:
        logger.warning("Thumbnail upload failed for %s: %s", video_id, e)

    return video_id
