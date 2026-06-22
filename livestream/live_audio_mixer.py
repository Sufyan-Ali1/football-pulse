from __future__ import annotations

import argparse
import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings

logger = logging.getLogger("live_audio_mixer")

SAMPLE_RATE = 44100
CHANNELS = 2
SAMPLE_WIDTH = 2
CHUNK_SECONDS = 0.2
FRAME_COUNT = int(SAMPLE_RATE * CHUNK_SECONDS)
CHUNK_BYTES = FRAME_COUNT * CHANNELS * SAMPLE_WIDTH


def _setup_logging() -> None:
    Path(settings.LIVESTREAM_LOG_DIR).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(Path(settings.LIVESTREAM_LOG_DIR) / "commentary_mixer.log", encoding="utf-8"),
        ],
    )


def _queue_dir(fixture_id: int) -> Path:
    return Path(settings.LIVECOMM_QUEUE_DIR) / f"fixture_{fixture_id}"


def _played_dir(fixture_id: int) -> Path:
    return Path(settings.LIVECOMM_PLAYED_DIR) / f"fixture_{fixture_id}"


def _build_decode_command(source: str, *, loop: bool) -> list[str]:
    command = [settings.LIVESTREAM_FFMPEG_BIN, "-nostdin", "-loglevel", "error"]
    if loop:
        command.extend(["-stream_loop", "-1"])
    command.extend(
        [
            "-i",
            source,
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "-ar",
            str(SAMPLE_RATE),
            "-ac",
            str(CHANNELS),
            "pipe:1",
        ]
    )
    return command


def _spawn_decoder(source: str, *, loop: bool) -> subprocess.Popen[bytes]:
    return subprocess.Popen(
        _build_decode_command(source, loop=loop),
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
    )


def _load_clip_pcm(path: Path) -> np.ndarray:
    proc = _spawn_decoder(str(path), loop=False)
    raw = proc.stdout.read() if proc.stdout else b""
    proc.wait(timeout=30)
    if proc.returncode not in (0, None):
        raise RuntimeError(f"Failed to decode commentary clip: {path}")
    pcm = np.frombuffer(raw, dtype=np.int16)
    if pcm.size == 0:
        return np.zeros((0, CHANNELS), dtype=np.int16)
    return pcm.reshape((-1, CHANNELS))


def _read_background_chunk(proc: subprocess.Popen[bytes] | None) -> np.ndarray:
    if proc is None or proc.stdout is None:
        return np.zeros((FRAME_COUNT, CHANNELS), dtype=np.int16)
    raw = proc.stdout.read(CHUNK_BYTES)
    if len(raw) < CHUNK_BYTES:
        return np.zeros((FRAME_COUNT, CHANNELS), dtype=np.int16)
    return np.frombuffer(raw, dtype=np.int16).reshape((-1, CHANNELS))


def _next_clip_metadata(queue_dir: Path) -> dict | None:
    items = sorted(queue_dir.glob("*.json"))
    if not items:
        return None
    meta_path = items[0]
    payload = json.loads(meta_path.read_text(encoding="utf-8"))
    if int(payload.get("expires_at") or 0) and int(payload["expires_at"]) <= int(time.time()):
        try:
            meta_path.unlink()
        except FileNotFoundError:
            pass
        audio_path = Path(payload.get("audio_path") or "")
        if audio_path.exists():
            audio_path.unlink(missing_ok=True)
        return None
    return {
        "meta_path": meta_path,
        "payload": payload,
    }


def _archive_clip(meta: dict, played_dir: Path) -> None:
    played_dir.mkdir(parents=True, exist_ok=True)
    meta_path = Path(meta["meta_path"])
    audio_path = Path(meta["payload"]["audio_path"])
    meta_path.replace(played_dir / meta_path.name)
    if audio_path.exists():
        audio_path.replace(played_dir / audio_path.name)


def _write_pipe(pipe_path: Path, fixture_id: int) -> None:
    queue_dir = _queue_dir(fixture_id)
    played_dir = _played_dir(fixture_id)
    queue_dir.mkdir(parents=True, exist_ok=True)
    played_dir.mkdir(parents=True, exist_ok=True)

    bg_proc: subprocess.Popen[bytes] | None = None
    if settings.LIVESTREAM_AUDIO_FILE:
        bg_proc = _spawn_decoder(settings.LIVESTREAM_AUDIO_FILE, loop=True)

    pipe_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        if pipe_path.exists():
            pipe_path.unlink()
        os.mkfifo(pipe_path)
    except FileExistsError:
        pass

    fd = os.open(pipe_path, os.O_RDWR)
    active_clip: np.ndarray | None = None
    active_index = 0

    with os.fdopen(fd, "wb", buffering=0) as handle:
        logger.info("Audio mixer streaming to %s", pipe_path)
        while True:
            started = time.monotonic()
            if active_clip is None:
                meta = _next_clip_metadata(queue_dir)
                if meta:
                    try:
                        active_clip = _load_clip_pcm(Path(meta["payload"]["audio_path"]))
                        active_index = 0
                        logger.info("Playing commentary clip %s", meta["payload"]["clip_id"])
                        _archive_clip(meta, played_dir)
                    except Exception as exc:
                        logger.warning("Failed to load commentary clip: %s", exc)
                        active_clip = None

            bg_chunk = _read_background_chunk(bg_proc)
            mix = bg_chunk.astype(np.float32)

            if active_clip is not None and active_index < len(active_clip):
                end = min(active_index + FRAME_COUNT, len(active_clip))
                clip_chunk = active_clip[active_index:end].astype(np.float32)
                if len(clip_chunk) < FRAME_COUNT:
                    pad = np.zeros((FRAME_COUNT - len(clip_chunk), CHANNELS), dtype=np.float32)
                    clip_chunk = np.vstack([clip_chunk, pad])
                duck_gain = float(10 ** (-settings.LIVECOMM_DUCK_DB / 20.0))
                mix = mix * duck_gain + clip_chunk
                active_index = end
                if active_index >= len(active_clip):
                    active_clip = None
                    active_index = 0

            out = np.clip(mix, -32768, 32767).astype(np.int16)
            handle.write(out.tobytes())
            elapsed = time.monotonic() - started
            if elapsed < CHUNK_SECONDS:
                time.sleep(CHUNK_SECONDS - elapsed)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mix looping background audio with queued commentary clips.")
    parser.add_argument("--fixture-id", required=True, type=int)
    parser.add_argument("--pipe-path", required=True)
    args = parser.parse_args()
    _setup_logging()
    _write_pipe(Path(args.pipe_path), args.fixture_id)


if __name__ == "__main__":
    main()
