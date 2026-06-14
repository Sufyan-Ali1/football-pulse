import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

BASE_DIR = Path(__file__).resolve().parent.parent

# ── Paths ─────────────────────────────────────────────────────────────────────
DATABASE_DIR   = BASE_DIR / "database"
TEMP_DIR       = BASE_DIR / "temp"
VOICEOVERS_DIR = TEMP_DIR / "voiceover"
VIDEOS_DIR     = TEMP_DIR / "videos" / "final"
CLIPS_DIR      = BASE_DIR / "config" / "clips"
THUMBNAILS_DIR = TEMP_DIR / "thumbnails"

# ── Groq ─────────────────────────────────────────────────────────────────────
GROQ_API_KEY          = os.environ.get("GROQ_API_KEY", "")
GROQ_API_KEY_2        = os.environ.get("GROQ_API_KEY_2", "")
GROQ_API_KEY_3        = os.environ.get("GROQ_API_KEY_3", "")
GROQ_API_KEY_4        = os.environ.get("GROQ_API_KEY_4", "")
GROQ_API_KEY_5        = os.environ.get("GROQ_API_KEY_5", "")
GROQ_MODEL            = "llama-3.3-70b-versatile"
GROQ_VISION_MODEL     = "meta-llama/llama-4-scout-17b-16e-instruct"

# ── ElevenLabs ───────────────────────────────────────────────────────────────
ELEVENLABS_API_KEY          = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID_ENGLISH = os.environ.get("ELEVENLABS_VOICE_ID_ENGLISH", "")
ELEVENLABS_VOICE_ID_YORUBA  = os.environ.get("ELEVENLABS_VOICE_ID_YORUBA", "")


# ── Twitter / X (future) ─────────────────────────────────────────────────────
TWITTER_BEARER_TOKEN   = os.environ.get("TWITTER_BEARER_TOKEN", "")

# ── Google OAuth (shared client for YouTube + Drive) ─────────────────────────
GOOGLE_CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
GOOGLE_CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
GOOGLE_CLOUD_PROJECT = os.environ.get("GOOGLE_CLOUD_PROJECT", "").strip()
GOOGLE_CLOUD_LOCATION = os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1").strip()

# ── YouTube ───────────────────────────────────────────────────────────────────
YOUTUBE_REFRESH_TOKEN = os.environ.get("YOUTUBE_REFRESH_TOKEN", "")
YOUTUBE_PLAYLIST_ID   = os.environ.get("YOUTUBE_PLAYLIST_ID", "")

# ── Buffer (future — social posting) ─────────────────────────────────────────
BUFFER_ACCESS_TOKEN        = os.environ.get("BUFFER_ACCESS_TOKEN", "")

# ── Google Drive ──────────────────────────────────────────────────────────────
GDRIVE_REFRESH_TOKEN = os.environ.get("GDRIVE_REFRESH_TOKEN", "")
GDRIVE_FOLDER_ID     = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

# ── Brand ─────────────────────────────────────────────────────────────────────
BRAND_NAME    = os.environ.get("BRAND_NAME", "Football Credo Hub")
BRAND_TAGLINE = os.environ.get("BRAND_TAGLINE", "Football News. Every Second.")
CONTENT_FOCUS = os.environ.get("CONTENT_FOCUS", "").strip().lower()

# Thumbnail generation
THUMBNAIL_ENABLED      = os.environ.get("THUMBNAIL_ENABLED", "false").strip().lower() in {"1", "true", "yes", "on"}
THUMBNAIL_GEMINI_MODEL = os.environ.get("THUMBNAIL_GEMINI_MODEL", "gemini-2.5-flash-image").strip()
THUMBNAIL_WIDTH        = int(os.environ.get("THUMBNAIL_WIDTH", "1280"))
THUMBNAIL_HEIGHT       = int(os.environ.get("THUMBNAIL_HEIGHT", "720"))

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
POLL_INTERVAL_RSS = 3600  # 1 hour

# ── Daily video config ────────────────────────────────────────────────────────
BREAKING_SCORE_THRESHOLD = int(os.environ.get("BREAKING_SCORE_THRESHOLD", "100"))
MIN_STORIES_FOR_DAILY    = int(os.environ.get("MIN_STORIES_FOR_DAILY", "2"))
MAX_STORIES_FOR_DAILY    = int(os.environ.get("MAX_STORIES_FOR_DAILY", "5"))
DAILY_VIDEO_HOURS_UTC    = [9, 19]   # 9 AM and 7 PM UTC

# ── Pipeline retry config ─────────────────────────────────────────────────────
MAX_RETRIES     = 3
RETRY_BACKOFF   = 2  # exponential backoff base (seconds)
