"""
YouTube uploader — Step 9.

Uploads the final branded video, attaches the thumbnail,
auto-generates SEO metadata via Groq, and schedules publish time.
"""
import json
import logging
import socket
import ssl
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
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
_RETRIABLE_HTTP_STATUS_CODES = {500, 502, 503, 504}
_UPLOAD_MAX_RETRIES = 6


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


def _is_retriable_upload_error(exc: Exception) -> bool:
    if isinstance(exc, HttpError):
        return getattr(getattr(exc, "resp", None), "status", None) in _RETRIABLE_HTTP_STATUS_CODES
    return isinstance(
        exc,
        (
            TimeoutError,
            socket.timeout,
            ssl.SSLError,
            ConnectionError,
            OSError,
        ),
    )


def _execute_resumable_upload(request, title: str) -> dict:
    response = None
    attempt = 0

    while response is None:
        try:
            _, response = request.next_chunk(num_retries=3)
        except Exception as exc:
            if not _is_retriable_upload_error(exc) or attempt >= _UPLOAD_MAX_RETRIES:
                raise
            sleep_seconds = min(2 ** attempt, 32)
            attempt += 1
            logger.warning(
                "Transient YouTube upload error for '%s' (attempt %d/%d): %s. Retrying in %ss",
                title,
                attempt,
                _UPLOAD_MAX_RETRIES,
                exc,
                sleep_seconds,
            )
            time.sleep(sleep_seconds)
            continue

    return response


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

_WORLD_CUP_METADATA_PROMPT = """You are an SEO expert for a football YouTube channel called "{brand_name}".

Generate YouTube metadata for a MULTI-STORY FIFA World Cup roundup video.

Channel tone:
- credible football newsroom
- exciting, curiosity-driven, but not spammy
- hook + facts style

Video focus:
- FIFA World Cup and directly related coverage only
- use the strongest storylines as hook points

Stories covered:
{stories}

Return VALID JSON with exactly these keys:
- "title": one compelling YouTube title, max 95 chars, must mention World Cup or FIFA World Cup naturally
- "description": 300-500 word description with a strong 2-3 line hook at the top, then readable bullet-style coverage summary, then hashtags at the end
- "tags": List of 15 relevant tags (strings), heavily focused on FIFA World Cup topics

Title requirements:
- use hook + facts style
- no generic phrasing like "Football News Today | 5 Stories | Date"
- no fake claims
- prioritize the biggest 1-3 World Cup angles

JSON only. No markdown, no explanation."""


def generate_metadata(item: NewsItem, script: Script) -> VideoMetadata:
    prompt = _METADATA_PROMPT.format(
        brand_name=settings.BRAND_NAME,
        content_type=script.script_type,
        script_text=script.text[:800],
    )
    try:
        groq_client = get_groq_client()
        resp = groq_client.chat.completions.create(
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


def generate_multi_story_metadata(
    items: list[NewsItem],
    scripts: list[Script],
    focus_mode: str = "",
) -> VideoMetadata:
    if not items:
        raise ValueError("generate_multi_story_metadata requires at least one item")

    story_lines = []
    for idx, item in enumerate(items, start=1):
        script_text = scripts[idx - 1].text if idx - 1 < len(scripts) else ""
        story_lines.append(
            f"{idx}. Headline: {item.headline}\n"
            f"   Source: {item.source}\n"
            f"   Script summary: {script_text[:280]}"
        )
    stories_block = "\n".join(story_lines)

    is_world_cup = focus_mode == "world_cup"
    prompt = (
        _WORLD_CUP_METADATA_PROMPT.format(
            brand_name=settings.BRAND_NAME,
            stories=stories_block,
        )
        if is_world_cup
        else _METADATA_PROMPT.format(
            brand_name=settings.BRAND_NAME,
            content_type="multi_story_roundup",
            script_text="\n".join(s.text[:250] for s in scripts),
        )
    )

    top_headline = items[0].headline
    if is_world_cup:
        fallback_title = f"FIFA World Cup Latest: {top_headline}"[:95]
        fallback_description = (
            "Latest FIFA World Cup headlines in one fast roundup.\n\n"
            + "\n".join(f"- {item.headline}" for item in items)
            + f"\n\n{settings.BRAND_NAME} - {settings.BRAND_TAGLINE}"
        )
        fallback_tags = [
            "fifa world cup",
            "world cup",
            "world cup news",
            "football world cup",
            settings.BRAND_NAME.lower(),
        ]
    else:
        fallback_title = top_headline[:95]
        fallback_description = (
            "Top football stories in this roundup.\n\n"
            + "\n".join(f"- {item.headline}" for item in items)
            + f"\n\n{settings.BRAND_NAME} - {settings.BRAND_TAGLINE}"
        )
        fallback_tags = ["football", "football news", settings.BRAND_NAME.lower()]

    try:
        groq_client = get_groq_client()
        resp = groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=900,
            temperature=0.65,
            response_format={"type": "json_object"},
        )
        data = json.loads(resp.choices[0].message.content)
        description = str(data.get("description", "")).strip()[:5000]
        if description:
            description += f"\n\n{settings.BRAND_NAME} - {settings.BRAND_TAGLINE}"
        else:
            description = fallback_description
        title = str(data.get("title", "")).strip()[:95] or fallback_title
        tags = [str(tag) for tag in data.get("tags", []) if tag][:30] or fallback_tags
        return VideoMetadata(title=title, description=description, tags=tags)
    except Exception as e:
        logger.warning("Multi-story metadata generation failed: %s - using fallback", e)
        return VideoMetadata(
            title=fallback_title,
            description=fallback_description,
            tags=fallback_tags,
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
    response = _execute_resumable_upload(request, metadata.title)

    video_id = response["id"]
    logger.info("YouTube upload complete: %s | '%s'", video_id, metadata.title)

    if thumbnail_path:
        try:
            youtube.thumbnails().set(
                videoId=video_id,
                media_body=MediaFileUpload(str(thumbnail_path), mimetype="image/png"),
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
