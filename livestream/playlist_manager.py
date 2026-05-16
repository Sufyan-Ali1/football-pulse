"""
24/7 YouTube Livestream playlist manager.

Strategy: Uses a YouTube playlist that the live broadcast reads from.
Every time a new final video is uploaded to YouTube, it is added to the
rotating playlist. The channel's 24/7 live stream plays this playlist on loop.

For the actual continuous RTMP stream, this assumes an FFmpeg process is
running on the server (see start_ffmpeg_stream() below).
"""
import logging
import pickle
import subprocess
from pathlib import Path

from googleapiclient.discovery import build
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request

from config import settings

logger = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.force-ssl",
]

# The playlist that the livestream reads from — created once, ID stored here.
# After first run, update this in settings or .env.
_LIVESTREAM_PLAYLIST_FILE = Path(__file__).resolve().parent.parent / "config" / "livestream_playlist_id.txt"


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


def _get_or_create_playlist() -> str:
    """Returns the livestream playlist ID, creating it if it doesn't exist."""
    if _LIVESTREAM_PLAYLIST_FILE.exists():
        return _LIVESTREAM_PLAYLIST_FILE.read_text().strip()

    youtube = _get_youtube_client()
    response = youtube.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": f"{settings.BRAND_NAME} – 24/7 Live News Rotation",
                "description": f"Auto-rotating playlist for the {settings.BRAND_NAME} 24/7 livestream.",
                "defaultLanguage": "en",
            },
            "status": {"privacyStatus": "public"},
        },
    ).execute()

    playlist_id = response["id"]
    _LIVESTREAM_PLAYLIST_FILE.write_text(playlist_id)
    logger.info("Created livestream playlist: %s", playlist_id)
    return playlist_id


def add_video_to_rotation(youtube_video_id: str) -> None:
    """Adds a newly uploaded YouTube video to the 24/7 rotation playlist."""
    playlist_id = _get_or_create_playlist()
    youtube = _get_youtube_client()

    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {
                    "kind": "youtube#video",
                    "videoId": youtube_video_id,
                },
            }
        },
    ).execute()

    logger.info("Added video %s to livestream playlist %s", youtube_video_id, playlist_id)


def get_playlist_video_count() -> int:
    """Returns how many videos are currently in the rotation playlist."""
    playlist_id = _get_or_create_playlist()
    youtube = _get_youtube_client()
    response = youtube.playlists().list(
        part="contentDetails",
        id=playlist_id,
    ).execute()
    items = response.get("items", [])
    if items:
        return items[0]["contentDetails"]["itemCount"]
    return 0


def start_ffmpeg_stream() -> subprocess.Popen:
    """
    Starts an FFmpeg process that streams the /Videos/Final/ folder
    in a loop to YouTube's RTMP endpoint.

    This is intended to run on a VPS (Linux). The playlist of files is
    dynamically built from whatever is in VIDEOS_FINAL_DIR.

    Call this once at startup. The process runs indefinitely.
    """
    video_files = sorted(settings.VIDEOS_FINAL_DIR.glob("*_final_branded.mp4"))
    if not video_files:
        logger.warning("No final videos found for FFmpeg stream.")
        return None

    # Build FFmpeg concat input
    concat_list = settings.VIDEOS_FINAL_DIR / "concat_list.txt"
    with open(concat_list, "w") as f:
        for vf in video_files:
            f.write(f"file '{vf.as_posix()}'\n")

    rtmp_target = f"{settings.YOUTUBE_RTMP_URL}/{settings.YOUTUBE_STREAM_KEY}"

    cmd = [
        "ffmpeg",
        "-re",
        "-stream_loop", "-1",
        "-f", "concat",
        "-safe", "0",
        "-i", str(concat_list),
        "-c:v", "libx264",
        "-preset", "veryfast",
        "-b:v", "4500k",
        "-maxrate", "4500k",
        "-bufsize", "9000k",
        "-pix_fmt", "yuv420p",
        "-g", "60",
        "-c:a", "aac",
        "-b:a", "128k",
        "-ar", "44100",
        "-f", "flv",
        rtmp_target,
    ]

    logger.info("Starting FFmpeg stream to %s", rtmp_target)
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    logger.info("FFmpeg PID: %d", process.pid)
    return process


def rebuild_concat_list() -> None:
    """Rebuilds the FFmpeg concat list when new videos are added."""
    video_files = sorted(settings.VIDEOS_FINAL_DIR.glob("*_final_branded.mp4"))
    concat_list = settings.VIDEOS_FINAL_DIR / "concat_list.txt"
    with open(concat_list, "w") as f:
        for vf in video_files:
            f.write(f"file '{vf.as_posix()}'\n")
    logger.info("Rebuilt concat list with %d videos", len(video_files))
