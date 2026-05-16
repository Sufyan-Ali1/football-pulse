"""
ElevenLabs voiceover generator — Step 5.

Converts script text to an MP3 using ElevenLabs TTS.
  language="english" → uses ELEVENLABS_VOICE_ID_ENGLISH
  language="yoruba"  → uses ELEVENLABS_VOICE_ID_YORUBA (Module 3 only)

Output saved to storage/Voiceovers/{news_id}_{format}_{language}.mp3
"""
import logging
from pathlib import Path

import requests

from config import settings
from core.types import Script

logger = logging.getLogger(__name__)

_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

_VOICE_SETTINGS = {
    "stability":        0.55,
    "similarity_boost": 0.75,
    "style":            0.3,
    "use_speaker_boost": True,
}


def generate_voiceover(script: Script, language: str = "english") -> Path:
    """
    Generate an MP3 voiceover for the given script.

    Args:
        script:   Script dataclass with the text to speak.
        language: "english" (default) or "yoruba".

    Returns:
        Path to the saved MP3 file.
    """
    voice_id = (
        settings.ELEVENLABS_VOICE_ID_YORUBA
        if language == "yoruba"
        else settings.ELEVENLABS_VOICE_ID_ENGLISH
    )

    output_path = settings.VOICEOVERS_DIR / f"{script.news_id}_{script.format}_{language}.mp3"

    if output_path.exists():
        logger.info("Voiceover already exists, skipping: %s", output_path.name)
        return output_path

    headers = {
        "xi-api-key":   settings.ELEVENLABS_API_KEY,
        "Content-Type": "application/json",
        "Accept":       "audio/mpeg",
    }
    payload = {
        "text":          script.text,
        "model_id":      "eleven_multilingual_v2",
        "voice_settings": _VOICE_SETTINGS,
    }

    response = requests.post(
        _TTS_URL.format(voice_id=voice_id),
        json=payload, headers=headers, timeout=120,
    )
    response.raise_for_status()

    settings.VOICEOVERS_DIR.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(response.content)
    logger.info("Voiceover saved: %s (%.1f KB)", output_path.name, output_path.stat().st_size / 1024)
    return output_path
