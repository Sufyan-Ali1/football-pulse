"""
Voiceover generator - Step 5.

Converts script text to an MP3 via ElevenLabs.
  language="english" -> ElevenLabs (ELEVENLABS_VOICE_ID_ENGLISH)
  language="yoruba"  -> ElevenLabs (ELEVENLABS_VOICE_ID_YORUBA)

Output saved to storage/Voiceovers/{news_id}_{format}_{language}.mp3
"""
import logging
from pathlib import Path

import requests

from config import settings
from core.types import Script

logger = logging.getLogger(__name__)

_ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"

_ELEVENLABS_VOICE_SETTINGS = {
    "stability": 0.55,
    "similarity_boost": 0.75,
    "style": 0.3,
    "use_speaker_boost": True,
}



def _generate_elevenlabs(script: Script, language: str, output_path: Path) -> Path:
    voice_id = (
        settings.ELEVENLABS_VOICE_ID_YORUBA
        if language == "yoruba"
        else settings.ELEVENLABS_VOICE_ID_ENGLISH
    )
    if not settings.ELEVENLABS_API_KEY or not voice_id:
        raise RuntimeError(f"ElevenLabs credentials are not configured for language={language!r}")

    response = requests.post(
        _ELEVENLABS_TTS_URL.format(voice_id=voice_id),
        json={
            "text": script.text,
            "model_id": "eleven_multilingual_v2",
            "voice_settings": _ELEVENLABS_VOICE_SETTINGS,
        },
        headers={
            "xi-api-key": settings.ELEVENLABS_API_KEY,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        },
        timeout=120,
    )
    response.raise_for_status()
    output_path.write_bytes(response.content)
    logger.info(
        "ElevenLabs voiceover saved: %s (%.1f KB)",
        output_path.name,
        output_path.stat().st_size / 1024,
    )
    return output_path


def generate_voiceover(script: Script, language: str = "english") -> Path:
    """Generate an MP3 voiceover for the given script."""
    language = language.lower().strip()
    output_path = settings.VOICEOVERS_DIR / f"{script.news_id}_{script.format}_{language}.mp3"

    if output_path.exists():
        logger.info("Voiceover already exists, skipping: %s", output_path.name)
        return output_path

    settings.VOICEOVERS_DIR.mkdir(parents=True, exist_ok=True)

    if language in ("english", "yoruba"):
        return _generate_elevenlabs(script, language, output_path)

    raise ValueError("language must be 'english' or 'yoruba'")
