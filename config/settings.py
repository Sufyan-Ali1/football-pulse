import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Storage paths ────────────────────────────────────────────────────────────
STORAGE_DIR        = BASE_DIR / "storage"
VOICEOVERS_DIR     = STORAGE_DIR / "Voiceovers"
VIDEOS_RAW_DIR     = STORAGE_DIR / "Videos" / "Raw"
VIDEOS_FINAL_DIR   = STORAGE_DIR / "Videos" / "Final"
THUMBNAILS_DIR     = STORAGE_DIR / "Thumbnails"

# ── Groq ─────────────────────────────────────────────────────────────────────
GROQ_API_KEY          = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL            = "llama-3.3-70b-versatile"
GROQ_VISION_MODEL     = "meta-llama/llama-4-scout-17b-16e-instruct"

# ── Pexels (stock B-roll video for news frame) ────────────────────────────────
PEXELS_API_KEY = os.environ.get("PEXELS_API_KEY", "")


# ── ElevenLabs ───────────────────────────────────────────────────────────────
ELEVENLABS_API_KEY          = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID_ENGLISH = os.environ.get("ELEVENLABS_VOICE_ID_ENGLISH", "")
ELEVENLABS_VOICE_ID_YORUBA  = os.environ.get("ELEVENLABS_VOICE_ID_YORUBA", "")


# ── Twitter / X ──────────────────────────────────────────────────────────────
TWITTER_BEARER_TOKEN   = os.environ.get("TWITTER_BEARER_TOKEN", "")
TWITTER_API_KEY        = os.environ.get("TWITTER_API_KEY", "")
TWITTER_API_SECRET     = os.environ.get("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN   = os.environ.get("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_SECRET  = os.environ.get("TWITTER_ACCESS_SECRET", "")

# ── YouTube ───────────────────────────────────────────────────────────────────
YOUTUBE_CLIENT_SECRETS_PATH = BASE_DIR / os.environ.get(
    "YOUTUBE_CLIENT_SECRETS_PATH", "config/secrets/youtube_client_secrets.json"
)
YOUTUBE_TOKEN_PATH = BASE_DIR / os.environ.get(
    "YOUTUBE_TOKEN_PATH", "config/secrets/youtube_token.json"
)
YOUTUBE_STREAM_KEY  = os.environ.get("YOUTUBE_STREAM_KEY", "")
YOUTUBE_RTMP_URL    = os.environ.get("YOUTUBE_RTMP_URL", "rtmp://a.rtmp.youtube.com/live2")
YOUTUBE_CHANNEL_ID  = os.environ.get("YOUTUBE_CHANNEL_ID", "")

# ── Buffer ───────────────────────────────────────────────────────────────────
BUFFER_ACCESS_TOKEN        = os.environ.get("BUFFER_ACCESS_TOKEN", "")
BUFFER_PROFILE_ID_YOUTUBE  = os.environ.get("BUFFER_PROFILE_ID_YOUTUBE", "")
BUFFER_PROFILE_ID_TIKTOK   = os.environ.get("BUFFER_PROFILE_ID_TIKTOK", "")
BUFFER_PROFILE_ID_INSTAGRAM = os.environ.get("BUFFER_PROFILE_ID_INSTAGRAM", "")
BUFFER_PROFILE_ID_TWITTER  = os.environ.get("BUFFER_PROFILE_ID_TWITTER", "")

# ── Google Drive ──────────────────────────────────────────────────────────────
GDRIVE_CLIENT_SECRETS_PATH = BASE_DIR / os.environ.get(
    "GDRIVE_CLIENT_SECRETS_PATH", "config/secrets/gdrive_client_secrets.json"
)
GDRIVE_TOKEN_PATH = BASE_DIR / os.environ.get(
    "GDRIVE_TOKEN_PATH", "config/secrets/gdrive_token.json"
)
GDRIVE_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

# ── Brand ─────────────────────────────────────────────────────────────────────
BRAND_NAME    = os.environ.get("BRAND_NAME", "Football Credo Hub")
BRAND_TAGLINE = os.environ.get("BRAND_TAGLINE", "Football News. Every Second.")

# ── Club colours (hex) for branding overlays ─────────────────────────────────
CLUB_COLOURS: dict[str, str] = {
    "manchester united": "#DA291C",
    "man utd":           "#DA291C",
    "chelsea":           "#034694",
    "real madrid":       "#FEBE10",
    "barcelona":         "#A50044",
    "psg":               "#004170",
    "paris saint-germain": "#004170",
    "al-nassr":          "#F5C518",
    "inter miami":       "#F7B5CD",
    "arsenal":           "#EF0107",
    "liverpool":         "#C8102E",
    "manchester city":   "#6CABDD",
    "tottenham":         "#132257",
    "juventus":          "#000000",
    "ac milan":          "#FB090B",
    "inter milan":       "#010E80",
    "atletico madrid":   "#CB3524",
    "default":           "#1A1A2E",
}

# ── Scheduler intervals (seconds) ────────────────────────────────────────────
POLL_INTERVAL_RSS            = 3600  # 1 hour
POLL_INTERVAL_TWITTER        = 900   # 15 minutes
POLL_INTERVAL_GOOGLE_ALERTS  = 1800  # 30 minutes

# ── Daily video config ────────────────────────────────────────────────────────
BREAKING_SCORE_THRESHOLD = int(os.environ.get("BREAKING_SCORE_THRESHOLD", "100"))
MIN_STORIES_FOR_DAILY    = int(os.environ.get("MIN_STORIES_FOR_DAILY", "3"))
MAX_STORIES_FOR_DAILY    = int(os.environ.get("MAX_STORIES_FOR_DAILY", "5"))
DAILY_VIDEO_HOUR_UTC     = int(os.environ.get("DAILY_VIDEO_HOUR_UTC", "20"))

# ── Pipeline retry config ─────────────────────────────────────────────────────
MAX_RETRIES     = 3
RETRY_BACKOFF   = 2  # exponential backoff base (seconds)
