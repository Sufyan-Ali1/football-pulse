"""
YouTube uploader — Step 9.

Uploads the final branded video, attaches the thumbnail,
auto-generates SEO metadata via Groq, and schedules publish time.
"""
import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
from clients.groq_client import get_groq_client
from config import settings
from core.types import NewsItem, Script, VideoMetadata

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]
_groq = get_groq_client()


def _get_youtube_client():
    from google.oauth2.credentials import Credentials
    if not settings.YOUTUBE_REFRESH_TOKEN:
        raise RuntimeError("YOUTUBE_REFRESH_TOKEN is not set in .env")
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise RuntimeError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env")
    creds = Credentials(
        token=None,
        refresh_token=settings.YOUTUBE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=_SCOPES,
    )
    creds.refresh(Request())
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


def _normalise_privacy_status(value: str) -> str:
    allowed = {"private", "unlisted", "public"}
    status = (value or "private").lower().strip()
    if status not in allowed:
        logger.warning("Invalid YouTube privacy_status=%r, falling back to private", value)
        return "private"
    return status


# ── Upload ────────────────────────────────────────────────────────────────────

def upload_video(
    video_path: Path,
    thumbnail_path: Path | None,
    metadata: VideoMetadata,
    schedule: bool = False,
) -> str:
    """
    Upload a video to YouTube with the provided metadata and optional thumbnail.
    Returns the YouTube video ID.

    Build metadata with generate_metadata(item, script) for single-story videos,
    or construct VideoMetadata directly for multi-story/custom uploads.
    """
    if schedule:
        metadata.publish_at = _next_publish_time()

    privacy_status = _normalise_privacy_status(metadata.privacy_status)
    if metadata.publish_at:
        # YouTube scheduled uploads must be private until the scheduled publish time.
        privacy_status = "private"

    youtube = _get_youtube_client()
    body    = {
        "snippet": {
            "title":       metadata.title,
            "description": metadata.description,
            "tags":        metadata.tags,
            "categoryId":  metadata.category_id,
        },
        "status": {
            "privacyStatus": privacy_status,
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

    if thumbnail_path:
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/jpeg"),
            ).execute()
            logger.info("Thumbnail attached to %s", video_id)
        except Exception as e:
            logger.warning("Thumbnail upload failed for %s: %s", video_id, e)

    if settings.YOUTUBE_PLAYLIST_ID:
        try:
            youtube.playlistItems().insert(
                part="snippet",
                body={
                    "snippet": {
                        "playlistId": settings.YOUTUBE_PLAYLIST_ID,
                        "resourceId": {"kind": "youtube#video", "videoId": video_id},
                    }
                },
            ).execute()
            logger.info("Added to playlist %s: %s", settings.YOUTUBE_PLAYLIST_ID, video_id)
        except Exception as e:
            logger.warning("Playlist insert failed for %s: %s", video_id, e)

    return video_id
