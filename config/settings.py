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
GROQ_API_KEY   = os.environ.get("GROQ_API_KEY", "")
GROQ_MODEL     = "llama-3.3-70b-versatile"

# ── OpenAI (kept as fallback) ─────────────────────────────────────────────────
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "")
OPENAI_MODEL   = "gpt-4o"

# ── ElevenLabs ───────────────────────────────────────────────────────────────
ELEVENLABS_API_KEY          = os.environ.get("ELEVENLABS_API_KEY", "")
ELEVENLABS_VOICE_ID_ENGLISH = os.environ.get("ELEVENLABS_VOICE_ID_ENGLISH", "")
ELEVENLABS_VOICE_ID_YORUBA  = os.environ.get("ELEVENLABS_VOICE_ID_YORUBA", "")

# ── HeyGen (not used — replaced by SadTalker) ────────────────────────────────
HEYGEN_API_KEY    = os.environ.get("HEYGEN_API_KEY", "")
HEYGEN_AVATAR_ID  = os.environ.get("HEYGEN_AVATAR_ID", "")
HEYGEN_POLL_INTERVAL_SECONDS = 30

# ── SadTalker (local talking head generator) ──────────────────────────────────
SADTALKER_PATH           = os.environ.get("SADTALKER_PATH", "")
PRESENTER_PHOTO_ENGLISH  = BASE_DIR / os.environ.get("PRESENTER_PHOTO_ENGLISH", "config/presenter_english.jpg")
PRESENTER_PHOTO_YORUBA   = BASE_DIR / os.environ.get("PRESENTER_PHOTO_YORUBA",  "config/presenter_yoruba.jpg")
SADTALKER_QUALITY        = os.environ.get("SADTALKER_QUALITY", "256")   # "256" fast | "512" high quality

# ── Creatomate ───────────────────────────────────────────────────────────────
CREATOMATE_API_KEY              = os.environ.get("CREATOMATE_API_KEY", "")
CREATOMATE_TEMPLATE_LANDSCAPE   = os.environ.get("CREATOMATE_TEMPLATE_ID_LANDSCAPE", "")
CREATOMATE_TEMPLATE_VERTICAL    = os.environ.get("CREATOMATE_TEMPLATE_ID_VERTICAL", "")

# ── Canva ─────────────────────────────────────────────────────────────────────
CANVA_API_KEY                = os.environ.get("CANVA_API_KEY", "")
CANVA_THUMBNAIL_TEMPLATE_ID  = os.environ.get("CANVA_THUMBNAIL_TEMPLATE_ID", "")

# ── Twitter / X ──────────────────────────────────────────────────────────────
TWITTER_BEARER_TOKEN   = os.environ.get("TWITTER_BEARER_TOKEN", "")
TWITTER_API_KEY        = os.environ.get("TWITTER_API_KEY", "")
TWITTER_API_SECRET     = os.environ.get("TWITTER_API_SECRET", "")
TWITTER_ACCESS_TOKEN   = os.environ.get("TWITTER_ACCESS_TOKEN", "")
TWITTER_ACCESS_SECRET  = os.environ.get("TWITTER_ACCESS_SECRET", "")

# ── YouTube ───────────────────────────────────────────────────────────────────
YOUTUBE_CLIENT_SECRETS_PATH = BASE_DIR / os.environ.get(
    "YOUTUBE_CLIENT_SECRETS_PATH", "config/youtube_client_secrets.json"
)
YOUTUBE_TOKEN_PATH = BASE_DIR / os.environ.get(
    "YOUTUBE_TOKEN_PATH", "config/youtube_token.json"
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
GDRIVE_SERVICE_ACCOUNT_PATH = BASE_DIR / os.environ.get(
    "GOOGLE_DRIVE_SERVICE_ACCOUNT_PATH", "config/gdrive_service_account.json"
)
GDRIVE_FOLDER_ID = os.environ.get("GOOGLE_DRIVE_FOLDER_ID", "")

# ── Brand ─────────────────────────────────────────────────────────────────────
BRAND_NAME    = os.environ.get("BRAND_NAME", "Football Lacuna HQ")
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
POLL_INTERVAL_RSS            = 300   # 5 minutes
POLL_INTERVAL_TWITTER        = 900   # 15 minutes
POLL_INTERVAL_GOOGLE_ALERTS  = 1800  # 30 minutes

# ── Pipeline retry config ─────────────────────────────────────────────────────
MAX_RETRIES     = 3
RETRY_BACKOFF   = 2  # exponential backoff base (seconds)
