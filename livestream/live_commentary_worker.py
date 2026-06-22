from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clients.api_football import ApiFootballClient, ApiFootballError
from clients.tts import get_tts_provider
from config import settings
from core.live_commentary import (
    CommentaryClip,
    FINISHED_STATUSES,
    load_state,
    mark_intent_emitted,
    queue_clip,
    refresh_dossier,
    save_state,
    select_intents,
    should_emit_intent,
    write_commentary,
)

logger = logging.getLogger("live_commentary_worker")


def _setup_logging() -> None:
    Path(settings.LIVESTREAM_LOG_DIR).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(Path(settings.LIVESTREAM_LOG_DIR) / "commentary_worker.log", encoding="utf-8"),
        ],
    )


def _state_path(fixture_id: int) -> Path:
    return Path(settings.LIVECOMM_STATE_DIR) / f"fixture_{fixture_id}.json"


def _clip_dir(fixture_id: int) -> Path:
    return Path(settings.LIVECOMM_QUEUE_DIR) / f"fixture_{fixture_id}"


def _provider():
    return get_tts_provider(settings.LIVECOMM_PROVIDER)


def _api() -> ApiFootballClient:
    return ApiFootballClient(cache_seconds=max(5, settings.LIVECOMM_LOOP_SECONDS))


def _queue_depth(queue_dir: Path) -> int:
    if not queue_dir.exists():
        return 0
    return len(list(queue_dir.glob("*.json")))


def _queued_audio_seconds(queue_dir: Path) -> int:
    total = 0
    for meta_path in queue_dir.glob("*.json"):
        try:
            payload = json.loads(meta_path.read_text(encoding="utf-8"))
            total += int(payload.get("estimated_duration_seconds") or 0)
        except Exception:
            continue
    return total


def run_worker(fixture_id: int) -> None:
    _setup_logging()
    queue_dir = _clip_dir(fixture_id)
    state_path = _state_path(fixture_id)
    state = load_state(state_path)
    state.fixture_id = fixture_id
    provider = _provider()
    queue_dir.mkdir(parents=True, exist_ok=True)

    logger.info("Starting live commentary worker for fixture %s", fixture_id)

    while True:
        try:
            data = _api().live_match(fixture_id)
            state = refresh_dossier(data, state)
            status = (data["fixture"]["status"]["short"] or "").upper()
            depth = _queue_depth(queue_dir)
            queued_seconds = _queued_audio_seconds(queue_dir)
            if depth >= settings.LIVECOMM_MAX_QUEUE_DEPTH and queued_seconds >= settings.LIVECOMM_TARGET_QUEUE_SECONDS:
                time.sleep(max(1, settings.LIVECOMM_LOOP_SECONDS))
                continue
            intents = select_intents(data, state, queue_depth=depth)
            for intent in intents:
                if (
                    not should_emit_intent(intent, state)
                    and depth > 0
                    and queued_seconds >= settings.LIVECOMM_TARGET_QUEUE_SECONDS
                ):
                    continue
                clip_id = f"{int(time.time())}_{intent.intent_type}_{intent.dedupe_key[:8]}"
                line = write_commentary(intent, state)
                if not line:
                    continue
                audio_path = queue_dir / f"{clip_id}.mp3"
                provider.synthesize(line, audio_path, language=settings.LIVECOMM_LANGUAGE)
                clip = CommentaryClip(
                    clip_id=clip_id,
                    fixture_id=fixture_id,
                    intent_type=intent.intent_type,
                    priority=intent.priority,
                    estimated_duration_seconds=intent.target_duration_seconds,
                    text=line,
                    audio_path=str(audio_path),
                    created_at=int(time.time()),
                    dedupe_key=intent.dedupe_key,
                    expires_at=intent.expires_at,
                )
                queue_clip(queue_dir, clip)
                logger.info("Queued commentary clip %s | %s", clip_id, line)
                state = mark_intent_emitted(state, intent, line)
                save_state(state_path, state)
                depth += 1
                queued_seconds += intent.target_duration_seconds
                if status in FINISHED_STATUSES:
                    break
            if status in FINISHED_STATUSES and not intents:
                logger.info("Fixture %s finished and no new commentary intents remain; worker exiting", fixture_id)
                return
        except (ApiFootballError, Exception) as exc:
            logger.exception("Commentary worker cycle failed for fixture %s: %s", fixture_id, exc)
        time.sleep(max(1, settings.LIVECOMM_LOOP_SECONDS))


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate live spoken commentary clips for one fixture.")
    parser.add_argument("--fixture-id", required=True, type=int)
    args = parser.parse_args()
    run_worker(args.fixture_id)


if __name__ == "__main__":
    main()
