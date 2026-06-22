from __future__ import annotations

import json
import logging
import os
import signal
import subprocess
import sys
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)


class EncoderError(RuntimeError):
    pass


@dataclass(slots=True)
class EncoderState:
    fixture_id: int
    frame_url: str
    display: str
    xvfb_pid: int
    chromium_pid: int
    mixer_pid: int
    commentary_worker_pid: int
    ffmpeg_pid: int
    audio_pipe_path: str
    started_at: int


def _state_path() -> Path:
    return Path(settings.LIVESTREAM_STATE_FILE)


def _log_dir() -> Path:
    path = Path(settings.LIVESTREAM_LOG_DIR)
    path.mkdir(parents=True, exist_ok=True)
    return path


def _frame_url(fixture_id: int) -> str:
    return f"{settings.LIVESTREAM_BASE_URL.rstrip('/')}/live-score/fixture/{fixture_id}"


def _rtmp_url() -> str:
    if not settings.LIVESTREAM_STREAM_KEY:
        raise EncoderError("LIVESTREAM_STREAM_KEY is not configured")
    return f"rtmp://a.rtmp.youtube.com/live2/{settings.LIVESTREAM_STREAM_KEY}"


def _write_state(state: EncoderState) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def load_state() -> EncoderState | None:
    path = _state_path()
    if not path.exists():
        return None
    return EncoderState(**json.loads(path.read_text(encoding="utf-8")))


def _pid_running(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def is_running() -> bool:
    state = load_state()
    if not state:
        return False
    required = [state.xvfb_pid, state.chromium_pid, state.ffmpeg_pid]
    if settings.LIVECOMM_ENABLED:
        required.append(state.mixer_pid)
    return all(_pid_running(pid) for pid in required)


def is_commentary_worker_running() -> bool:
    state = load_state()
    if not state or not settings.LIVECOMM_ENABLED:
        return False
    return _pid_running(state.commentary_worker_pid)


def _spawn(command: list[str], *, env: dict[str, str], log_name: str) -> subprocess.Popen[str]:
    log_path = _log_dir() / log_name
    logger.info("Starting process: %s", " ".join(command))
    with log_path.open("a", encoding="utf-8") as log_handle:
        return subprocess.Popen(
            command,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            env=env,
            text=True,
        )


def _script_command(script_name: str, *args: str) -> list[str]:
    return [
        sys.executable,
        str(Path(__file__).resolve().parent / script_name),
        *args,
    ]


def _audio_pipe_path() -> Path:
    return Path(settings.LIVECOMM_AUDIO_PIPE)


def _chromium_command(frame_url: str) -> list[str]:
    user_data_dir = Path(settings.TEMP_DIR) / "chromium-profile"
    user_data_dir.mkdir(parents=True, exist_ok=True)
    return [
        settings.LIVESTREAM_CHROMIUM_BIN,
        "--kiosk",
        "--start-fullscreen",
        "--window-position=0,0",
        f"--window-size={settings.LIVESTREAM_FRAME_WIDTH},{settings.LIVESTREAM_FRAME_HEIGHT}",
        "--no-sandbox",
        "--disable-dev-shm-usage",
        "--disable-gpu",
        "--disable-extensions",
        "--disable-background-networking",
        "--disable-component-update",
        "--disable-infobars",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-session-crashed-bubble",
        "--autoplay-policy=no-user-gesture-required",
        f"--user-data-dir={user_data_dir}",
        frame_url,
    ]


def _ffmpeg_command(display: str) -> list[str]:
    command = [
        settings.LIVESTREAM_FFMPEG_BIN,
        "-y",
        "-video_size",
        f"{settings.LIVESTREAM_FRAME_WIDTH}x{settings.LIVESTREAM_FRAME_HEIGHT}",
        "-framerate",
        str(settings.LIVESTREAM_FRAME_RATE),
        "-f",
        "x11grab",
        "-i",
        display,
    ]
    if settings.LIVECOMM_ENABLED:
        command.extend(
            [
                "-thread_queue_size",
                "512",
                "-f",
                "s16le",
                "-ar",
                "44100",
                "-ac",
                "2",
                "-i",
                str(_audio_pipe_path()),
            ]
        )
    elif settings.LIVESTREAM_AUDIO_FILE:
        command.extend(["-stream_loop", "-1", "-i", settings.LIVESTREAM_AUDIO_FILE])
    else:
        command.extend(["-f", "lavfi", "-i", "anullsrc=r=44100:cl=stereo"])
    command.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            settings.LIVESTREAM_FFMPEG_PRESET,
            "-pix_fmt",
            "yuv420p",
            "-r",
            str(settings.LIVESTREAM_FRAME_RATE),
            "-b:v",
            settings.LIVESTREAM_VIDEO_BITRATE,
            "-c:a",
            "aac",
            "-b:a",
            settings.LIVESTREAM_AUDIO_BITRATE,
            "-ar",
            "44100",
            "-f",
            "flv",
            _rtmp_url(),
        ]
    )
    return command


def _spawn_mixer(*, fixture_id: int, env: dict[str, str]) -> subprocess.Popen[str]:
    return _spawn(
        _script_command(
            "live_audio_mixer.py",
            "--fixture-id",
            str(fixture_id),
            "--pipe-path",
            str(_audio_pipe_path()),
        ),
        env=env,
        log_name="commentary_mixer.log",
    )


def _spawn_commentary_worker(*, fixture_id: int, env: dict[str, str]) -> subprocess.Popen[str]:
    return _spawn(
        _script_command("live_commentary_worker.py", "--fixture-id", str(fixture_id)),
        env=env,
        log_name="commentary_worker.log",
    )


def ensure_commentary_worker(fixture_id: int) -> None:
    if not settings.LIVECOMM_ENABLED:
        return
    state = load_state()
    if not state or state.fixture_id != fixture_id or _pid_running(state.commentary_worker_pid):
        return
    env = os.environ.copy()
    env["DISPLAY"] = state.display
    worker = _spawn_commentary_worker(fixture_id=fixture_id, env=env)
    time.sleep(2)
    if worker.poll() is not None:
        logger.warning("Commentary worker exited immediately; check livestream/commentary_worker.log")
        return
    state.commentary_worker_pid = worker.pid
    _write_state(state)
    logger.info("Commentary worker restarted for fixture %s", fixture_id)


def start_encoder(fixture_id: int) -> EncoderState:
    existing = load_state()
    if existing and is_running():
        if existing.fixture_id == fixture_id:
            logger.info("Encoder already running for fixture %s", fixture_id)
            return existing
        raise EncoderError(
            f"Encoder already running for fixture {existing.fixture_id}; stop it before starting fixture {fixture_id}"
        )
    if existing:
        logger.warning("Found stale/partial encoder state for fixture %s; cleaning it up before restart", existing.fixture_id)
        stop_encoder()

    frame_url = _frame_url(fixture_id)
    display = settings.LIVESTREAM_DISPLAY
    env = os.environ.copy()
    env["DISPLAY"] = display

    xvfb = _spawn(
        [
            settings.LIVESTREAM_XVFB_BIN,
            display,
            "-screen",
            "0",
            f"{settings.LIVESTREAM_FRAME_WIDTH}x{settings.LIVESTREAM_FRAME_HEIGHT}x24",
        ],
        env=env,
        log_name="xvfb.log",
    )
    time.sleep(2)
    if xvfb.poll() is not None:
        raise EncoderError("Xvfb exited immediately; check livestream/xvfb.log")

    chromium = _spawn(_chromium_command(frame_url), env=env, log_name="chromium.log")
    time.sleep(5)
    if chromium.poll() is not None:
        xvfb.terminate()
        raise EncoderError("Chromium exited immediately; check livestream/chromium.log")

    mixer_pid = 0
    if settings.LIVECOMM_ENABLED:
        mixer = _spawn_mixer(fixture_id=fixture_id, env=env)
        time.sleep(2)
        if mixer.poll() is not None:
            chromium.terminate()
            xvfb.terminate()
            raise EncoderError("Commentary mixer exited immediately; check livestream/commentary_mixer.log")
        mixer_pid = mixer.pid

    ffmpeg = _spawn(_ffmpeg_command(display), env=env, log_name="ffmpeg.log")
    time.sleep(5)
    if ffmpeg.poll() is not None:
        if settings.LIVECOMM_ENABLED and mixer_pid:
            os.kill(mixer_pid, signal.SIGTERM)
        chromium.terminate()
        xvfb.terminate()
        raise EncoderError("FFmpeg exited immediately; check livestream/ffmpeg.log")

    commentary_worker_pid = 0
    if settings.LIVECOMM_ENABLED:
        worker = _spawn_commentary_worker(fixture_id=fixture_id, env=env)
        time.sleep(2)
        if worker.poll() is None:
            commentary_worker_pid = worker.pid
        else:
            logger.warning("Commentary worker exited immediately; stream will continue without spoken commentary")

    state = EncoderState(
        fixture_id=fixture_id,
        frame_url=frame_url,
        display=display,
        xvfb_pid=xvfb.pid,
        chromium_pid=chromium.pid,
        mixer_pid=mixer_pid,
        commentary_worker_pid=commentary_worker_pid,
        ffmpeg_pid=ffmpeg.pid,
        audio_pipe_path=str(_audio_pipe_path()) if settings.LIVECOMM_ENABLED else "",
        started_at=int(time.time()),
    )
    _write_state(state)
    logger.info("Encoder started for fixture %s", fixture_id)
    return state


def _terminate_pid(pid: int, *, name: str) -> None:
    if not _pid_running(pid):
        return
    logger.info("Stopping %s pid=%s", name, pid)
    os.kill(pid, signal.SIGTERM)
    for _ in range(20):
        if not _pid_running(pid):
            return
        time.sleep(0.5)
    os.kill(pid, signal.SIGKILL)


def stop_encoder() -> None:
    state = load_state()
    if not state:
        logger.info("Encoder state file not found; nothing to stop")
        return
    _terminate_pid(state.ffmpeg_pid, name="ffmpeg")
    if state.commentary_worker_pid:
        _terminate_pid(state.commentary_worker_pid, name="commentary_worker")
    if state.mixer_pid:
        _terminate_pid(state.mixer_pid, name="commentary_mixer")
    _terminate_pid(state.chromium_pid, name="chromium")
    _terminate_pid(state.xvfb_pid, name="xvfb")
    if state.audio_pipe_path:
        try:
            Path(state.audio_pipe_path).unlink()
        except FileNotFoundError:
            pass
    try:
        _state_path().unlink()
    except FileNotFoundError:
        pass
    logger.info("Encoder stopped")
