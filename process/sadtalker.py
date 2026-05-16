"""
SadTalker integration — Step 6.

Animates a static presenter photo to lip-sync with an ElevenLabs MP3,
producing a talking head MP4 video.

How it works:
  photo (one static image)  +  voice.mp3  →  talking_head.mp4
  SadTalker animates the face to match the audio

Requires:
  - SadTalker cloned and set up locally (see tests/test_sadtalker.py for steps)
  - SADTALKER_PATH set in .env
  - PRESENTER_PHOTO_ENGLISH (and PRESENTER_PHOTO_YORUBA for Module 3) in config/

Output saved to: storage/Videos/Raw/{news_id}_{format}_raw.mp4
"""
import logging
import shutil
import subprocess
from pathlib import Path

from config import settings
from core.types import Script

logger = logging.getLogger(__name__)

_SADTALKER_DIR = Path(settings.SADTALKER_PATH) if settings.SADTALKER_PATH else None


# ── Internal helpers ──────────────────────────────────────────────────────────

def _check_setup() -> None:
    """Raise a clear error if SadTalker isn't configured."""
    if not _SADTALKER_DIR or not _SADTALKER_DIR.exists():
        raise RuntimeError(
            "SadTalker directory not found.\n"
            f"  Expected : {settings.SADTALKER_PATH or '(SADTALKER_PATH not set in .env)'}\n"
            "  Fix      : Set SADTALKER_PATH in .env to your SadTalker clone folder.\n"
            "  Setup    : See tests/test_sadtalker.py for full setup instructions."
        )
    inference = _SADTALKER_DIR / "inference.py"
    if not inference.exists():
        raise RuntimeError(
            f"inference.py not found in {_SADTALKER_DIR}.\n"
            "  Is this the correct SadTalker folder?"
        )
    checkpoints = _SADTALKER_DIR / "checkpoints"
    if not checkpoints.exists() or not any(checkpoints.iterdir()):
        raise RuntimeError(
            "SadTalker model weights not found in checkpoints/.\n"
            "  Fix: Run the weight download step in tests/test_sadtalker.py."
        )


def _get_photo(language: str) -> Path:
    """Return the presenter photo path for the given language."""
    photo = (
        settings.PRESENTER_PHOTO_YORUBA
        if language == "yoruba"
        else settings.PRESENTER_PHOTO_ENGLISH
    )
    if not photo.exists():
        raise FileNotFoundError(
            f"Presenter photo not found: {photo}\n"
            "  Fix: Put a clear face photo at that path.\n"
            "  Best: front-facing, neutral expression, good lighting, 512×512 or larger."
        )
    return photo


def _find_output(result_dir: Path) -> Path | None:
    """Find the newest MP4 SadTalker wrote to the result directory."""
    mp4s = sorted(result_dir.glob("*.mp4"), key=lambda f: f.stat().st_mtime)
    return mp4s[-1] if mp4s else None


# ── Public API ────────────────────────────────────────────────────────────────

def generate_talking_head(
    script: Script,
    voiceover_path: Path,
    language: str = "english",
) -> Path:
    """
    Generate a talking head video using SadTalker.

    Args:
        script:         Script dataclass (used for output path naming).
        voiceover_path: Path to ElevenLabs MP3 file.
        language:       "english" or "yoruba" — selects the presenter photo.

    Returns:
        Path to the MP4 in storage/Videos/Raw/.
    """
    _check_setup()

    if not voiceover_path.exists():
        raise FileNotFoundError(f"Voiceover not found: {voiceover_path}")

    photo       = _get_photo(language)
    output_path = settings.VIDEOS_RAW_DIR / f"{script.news_id}_{script.format}_raw.mp4"

    if output_path.exists():
        logger.info("Talking head already exists, skipping: %s", output_path.name)
        return output_path

    # SadTalker writes its output to result_dir — we move it afterwards
    result_dir = settings.VIDEOS_RAW_DIR / f"_sadtalker_tmp_{script.news_id}"
    result_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        "python", "inference.py",
        "--driven_audio", str(voiceover_path.resolve()),
        "--source_image",  str(photo.resolve()),
        "--result_dir",    str(result_dir.resolve()),
        "--still",                              # minimal head movement (news presenter style)
        "--preprocess",    "crop",              # crop & centre the face automatically
        "--size",          settings.SADTALKER_QUALITY,  # 256=fast, 512=high quality
        "--expression_scale", "1.0",            # natural expression level
    ]

    logger.info(
        "SadTalker: generating talking head for %s (%s, quality=%s) ...",
        script.news_id, language, settings.SADTALKER_QUALITY,
    )
    logger.info("This takes 5-15 min on CPU, 1-2 min on GPU. Do not interrupt.")

    try:
        proc = subprocess.run(
            cmd,
            cwd=str(_SADTALKER_DIR),
            capture_output=True,
            text=True,
            timeout=1800,   # 30-minute hard limit
        )

        if proc.returncode != 0:
            logger.error("SadTalker stderr:\n%s", proc.stderr[-3000:])
            raise RuntimeError(
                f"SadTalker exited with code {proc.returncode}. "
                "Check the error above."
            )

        generated = _find_output(result_dir)
        if not generated:
            raise RuntimeError(
                f"SadTalker finished but no MP4 found in {result_dir}. "
                "Check SadTalker output above for errors."
            )

        settings.VIDEOS_RAW_DIR.mkdir(parents=True, exist_ok=True)
        shutil.move(str(generated), str(output_path))

        size_mb = output_path.stat().st_size / (1024 * 1024)
        logger.info(
            "Talking head saved: %s (%.1f MB)", output_path.name, size_mb
        )
        return output_path

    finally:
        # Always clean up the temp directory
        if result_dir.exists():
            shutil.rmtree(result_dir, ignore_errors=True)
