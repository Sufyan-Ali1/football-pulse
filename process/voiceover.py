"""
Voiceover generator - Step 5.

Generates an MP3 voiceover for a script using the configured TTS provider.
Supported providers come from clients.tts, currently ElevenLabs and Edge TTS.
"""
import logging
from pathlib import Path

from clients.tts import get_tts_provider
from config import settings
from core.types import Script

logger = logging.getLogger(__name__)


def generate_voiceover(script: Script, language: str = "english") -> Path:
    """Generate an MP3 voiceover for the given script."""
    language = language.lower().strip()
    output_path = settings.VOICEOVERS_DIR / f"{script.news_id}_{script.format}_{language}.mp3"

    if output_path.exists():
        logger.info("Voiceover already exists, skipping: %s", output_path.name)
        return output_path

    settings.VOICEOVERS_DIR.mkdir(parents=True, exist_ok=True)

    primary_name = settings.VOICEOVER_TTS_PROVIDER
    fallback_name = "elevenlabs"

    try:
        provider = get_tts_provider(primary_name)
        return provider.synthesize(script.text, output_path, language=language)
    except Exception as primary_exc:
        if primary_name.strip().lower() == fallback_name:
            raise

        logger.warning(
            "Primary TTS provider %s failed for %s: %s. Falling back to %s.",
            primary_name,
            output_path.name,
            primary_exc,
            fallback_name,
        )

        try:
            fallback_provider = get_tts_provider(fallback_name)
            return fallback_provider.synthesize(script.text, output_path, language=language)
        except Exception as fallback_exc:
            raise RuntimeError(
                f"Primary TTS provider {primary_name!r} failed: {primary_exc}. "
                f"Fallback provider {fallback_name!r} failed: {fallback_exc}"
            ) from fallback_exc
