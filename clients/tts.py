from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Protocol

import requests

from config import settings

logger = logging.getLogger(__name__)

_ELEVENLABS_TTS_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice_id}"
_ELEVENLABS_VOICE_SETTINGS = {
    "stability": 0.55,
    "similarity_boost": 0.75,
    "style": 0.3,
    "use_speaker_boost": True,
}


class TtsProvider(Protocol):
    def synthesize(self, text: str, output_path: Path, *, language: str = "english") -> Path:
        ...


class ElevenLabsTtsProvider:
    def synthesize(self, text: str, output_path: Path, *, language: str = "english") -> Path:
        language = language.lower().strip()
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
                "text": text,
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
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(response.content)
        logger.info("TTS saved: %s", output_path)
        return output_path


class EdgeTtsProvider:
    def synthesize(self, text: str, output_path: Path, *, language: str = "english") -> Path:
        language = language.lower().strip()
        voice = (
            settings.EDGE_TTS_VOICE_YORUBA
            if language == "yoruba"
            else settings.EDGE_TTS_VOICE_ENGLISH
        ).strip()
        if not voice:
            raise RuntimeError(f"Edge TTS voice is not configured for language={language!r}")

        try:
            import edge_tts
        except ImportError as exc:
            raise RuntimeError("edge-tts is not installed. Run: venv\\Scripts\\pip.exe install edge-tts") from exc

        output_path.parent.mkdir(parents=True, exist_ok=True)

        async def _save() -> None:
            communicate = edge_tts.Communicate(
                text=text,
                voice=voice,
                rate=settings.EDGE_TTS_RATE,
                volume=settings.EDGE_TTS_VOLUME,
            )
            await communicate.save(str(output_path))

        asyncio.run(_save())
        logger.info("TTS saved: %s", output_path)
        return output_path


def get_tts_provider(name: str | None = None) -> TtsProvider:
    provider_name = (name or settings.LIVECOMM_PROVIDER).strip().lower()
    if provider_name == "elevenlabs":
        return ElevenLabsTtsProvider()
    if provider_name in {"edge-tts", "edgetts"}:
        return EdgeTtsProvider()
    raise ValueError(f"Unsupported live commentary TTS provider: {provider_name!r}")
