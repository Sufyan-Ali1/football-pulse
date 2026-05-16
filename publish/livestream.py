"""
24/7 YouTube Livestream manager — Step 11.

Maintains a YouTube playlist that the live broadcast reads from.
Every new uploaded video is added to the rotation playlist.
The FFmpeg process streams that playlist on loop to YouTube's RTMP endpoint.

start_ffmpeg_stream() is called once at startup from main.py.
rebuild_concat_list() is called after every new video is added.
"""
import logging
import pickle
import subprocess
from pathlib import Path

from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

from config import settings

logger = logging.getLogger(__name__)

_SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

_PLAYLIST_ID_FILE = Path(__file__).resolve().parent.parent / "config" / "livestream_playlist_id.txt"


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


def _get_or_create_playlist() -> str:
    """Return the livestream playlist ID, creating it on first run."""
    if _PLAYLIST_ID_FILE.exists():
        return _PLAYLIST_ID_FILE.read_text().strip()

    youtube  = _get_youtube_client()
    response = youtube.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title":           f"{settings.BRAND_NAME} – 24/7 Live News Rotation",
                "description":     f"Auto-rotating playlist for the {settings.BRAND_NAME} 24/7 livestream.",
                "defaultLanguage": "en",
            },
            "status": {"privacyStatus": "public"},
        },
    ).execute()

    playlist_id = response["id"]
    _PLAYLIST_ID_FILE.write_text(playlist_id)
    logger.info("Created livestream playlist: %s", playlist_id)
    return playlist_id


def add_video_to_rotation(youtube_video_id: str) -> None:
    """Add a newly uploaded YouTube video to the 24/7 rotation playlist."""
    playlist_id = _get_or_create_playlist()
    youtube     = _get_youtube_client()
    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": youtube_video_id},
            }
        },
    ).execute()
    logger.info("Added %s to playlist %s", youtube_video_id, playlist_id)


def rebuild_concat_list() -> None:
    """Rebuild the FFmpeg concat list after new videos are added."""
    video_files = sorted(settings.VIDEOS_FINAL_DIR.glob("*_final_branded.mp4"))
    concat_list = settings.VIDEOS_FINAL_DIR / "concat_list.txt"
    with open(concat_list, "w") as f:
        for vf in video_files:
            f.write(f"file '{vf.as_posix()}'\n")
    logger.info("Rebuilt concat list: %d videos", len(video_files))


def start_ffmpeg_stream() -> subprocess.Popen | None:
    """
    Start an FFmpeg process that streams storage/Videos/Final/ on loop
    to YouTube's RTMP endpoint. Call once at startup.
    """
    video_files = sorted(settings.VIDEOS_FINAL_DIR.glob("*_final_branded.mp4"))
    if not video_files:
        logger.warning("No final videos found — FFmpeg stream not started.")
        return None

    rebuild_concat_list()
    concat_list  = settings.VIDEOS_FINAL_DIR / "concat_list.txt"
    rtmp_target  = f"{settings.YOUTUBE_RTMP_URL}/{settings.YOUTUBE_STREAM_KEY}"

    cmd = [
        "ffmpeg", "-re",
        "-stream_loop", "-1",
        "-f", "concat", "-safe", "0",
        "-i", str(concat_list),
        "-c:v", "libx264", "-preset", "veryfast",
        "-b:v", "4500k", "-maxrate", "4500k", "-bufsize", "9000k",
        "-pix_fmt", "yuv420p", "-g", "60",
        "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
        "-f", "flv", rtmp_target,
    ]

    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    logger.info("FFmpeg stream started (PID %d) → %s", process.pid, rtmp_target)
    return process
