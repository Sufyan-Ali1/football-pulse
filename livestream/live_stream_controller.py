from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from clients.api_football import ApiFootballClient, ApiFootballError
from config import settings
from publish.livestream import (
    LiveStreamError,
    bind_broadcast_to_stream,
    create_broadcast,
    delete_broadcast,
    find_reusable_broadcast,
    get_broadcast,
    stream_health,
    transition_broadcast,
)
from livestream.stream_encoder import (
    EncoderError,
    ensure_commentary_worker,
    is_commentary_worker_running,
    is_running,
    start_encoder,
    stop_encoder,
)

logger = logging.getLogger("live_stream_controller")

LIVE_STATUSES = {"1H", "HT", "2H", "ET", "BT", "P", "INT", "SUSP"}
FINISHED_STATUSES = {"FT", "AET", "PEN"}


@dataclass(slots=True)
class ControllerState:
    fixture_id: int
    broadcast_id: str
    title: str
    live_started: bool = False
    finished_detected_at: int | None = None
    completed: bool = False


def _state_path() -> Path:
    return Path(settings.LIVESTREAM_CONTROLLER_STATE_FILE)


def _save_state(state: ControllerState) -> None:
    path = _state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(state), indent=2), encoding="utf-8")


def _load_state() -> ControllerState | None:
    path = _state_path()
    if not path.exists():
        return None
    return ControllerState(**json.loads(path.read_text(encoding="utf-8")))


def _clear_state() -> None:
    try:
        _state_path().unlink()
    except FileNotFoundError:
        pass


def _setup_logging() -> None:
    Path(settings.LIVESTREAM_LOG_DIR).mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(Path(settings.LIVESTREAM_LOG_DIR) / "controller.log", encoding="utf-8"),
        ],
    )


def _api() -> ApiFootballClient:
    return ApiFootballClient(cache_seconds=max(5, settings.LIVESTREAM_POLL_SECONDS))


def _parse_match_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None


def _fixture_title(fixture: dict[str, Any]) -> str:
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    return f"{home} vs {away} | FIFA World Cup 2026 Live"


def _fixture_description(fixture: dict[str, Any]) -> str:
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    venue = fixture["venue"]["name"] or "Venue TBC"
    round_name = fixture["league"]["round"] or "World Cup"
    kickoff = fixture["date"]
    team_tags = " ".join(filter(None, (_team_hashtag(home), _team_hashtag(away))))
    hashtags = f"#fifaworldcup2026 #fifaworldcup #worldcup2026 #livestream #livefootball #livescore {team_tags}".strip()
    return (
        f"Automated live scoreboard stream for {home} vs {away}.\n\n"
        f"Competition: {fixture['league']['name']}\n"
        f"Round: {round_name}\n"
        f"Venue: {venue}\n"
        f"Kickoff: {kickoff}\n\n"
        f"{settings.BRAND_NAME} - {settings.BRAND_TAGLINE}\n\n"
        f"{hashtags}"
    )


def _team_hashtag(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9]+", "", str(name or "").strip())
    return f"#{cleaned}" if cleaned else ""


def _fixture_tags(fixture: dict[str, Any]) -> list[str]:
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    round_name = fixture["league"]["round"] or "World Cup"
    brand = (settings.BRAND_NAME or "").strip()
    tags = [
        "fifaworldcup2026",
        "fifa",
        "fifaworldcup",
        "worldcup2026",
        f"{home} vs {away}",
        home,
        away,
        "footballlive",
        "livescore",
        "worldcuplive",
        "livestream",
        "livestreaming",
        "livefootball",
        "livefootballmatchtoday",
        "footballscoreboard",
        "matchstats",
        round_name,
    ]
    if brand:
        tags.append(brand)
    return tags


def _select_candidate(fixtures: list[dict[str, Any]], now: datetime) -> dict[str, Any] | None:
    live = [f for f in fixtures if (f["status"]["short"] or "").upper() in LIVE_STATUSES]
    if live:
        live.sort(key=lambda row: row["date"] or "")
        return live[0]

    upcoming: list[tuple[datetime, dict[str, Any]]] = []
    for fixture in fixtures:
        status = (fixture["status"]["short"] or "").upper()
        if status not in {"NS", "TBD"}:
            continue
        kickoff = _parse_match_time(fixture["date"])
        if kickoff is None:
            continue
        delta = (kickoff - now).total_seconds()
        if 0 <= delta <= settings.LIVESTREAM_PREMATCH_LEAD_SECONDS:
            upcoming.append((kickoff, fixture))
    upcoming.sort(key=lambda pair: pair[0])
    return upcoming[0][1] if upcoming else None


def _load_today_fixtures() -> list[dict[str, Any]]:
    return _api().fixtures_for_date(
        match_date=date.today().isoformat(),
        league=settings.LIVESTREAM_TARGET_LEAGUE_ID,
        season=settings.LIVESTREAM_TARGET_SEASON,
        timezone=settings.LIVE_SCORE_TIMEZONE,
    )


def _ensure_broadcast(state: ControllerState | None, fixture: dict[str, Any]) -> ControllerState:
    if state and state.fixture_id == fixture["id"] and state.broadcast_id:
        try:
            current = get_broadcast(state.broadcast_id)
        except Exception:
            current = None
        if current and current.life_cycle_status != "complete":
            return state

    title = _fixture_title(fixture)
    start_time = _parse_match_time(fixture["date"]) or datetime.now(UTC)
    broadcast = find_reusable_broadcast(title=title, start_time=start_time)
    if broadcast is not None:
        details = get_broadcast(broadcast.broadcast_id)
        if details.life_cycle_status == "complete":
            broadcast = None
    if broadcast is None:
        broadcast = create_broadcast(
            title=title,
            description=_fixture_description(fixture),
            start_time=start_time,
            tags=_fixture_tags(fixture),
        )
    if not broadcast.bound_stream_id:
        broadcast = bind_broadcast_to_stream(broadcast.broadcast_id)
    next_state = ControllerState(
        fixture_id=int(fixture["id"]),
        broadcast_id=broadcast.broadcast_id,
        title=title,
        live_started=broadcast.life_cycle_status == "live",
    )
    _save_state(next_state)
    return next_state


def _transition_live(state: ControllerState) -> ControllerState:
    if not is_running():
        start_encoder(state.fixture_id)
    status = stream_health()
    if status not in {"active", "ready"}:
        raise LiveStreamError(f"YouTube stream is not ingesting yet (stream status={status})")
    details = get_broadcast(state.broadcast_id)
    if details.life_cycle_status == "live":
        state.live_started = True
        _save_state(state)
        return state
    if details.life_cycle_status == "testing":
        transition_broadcast(state.broadcast_id, "live")
        state.live_started = True
        _save_state(state)
        return state
    if details.life_cycle_status == "complete":
        raise LiveStreamError(f"Broadcast {state.broadcast_id} is already complete and cannot transition to live")
    try:
        transition_broadcast(state.broadcast_id, "testing")
    except Exception as exc:
        logger.warning("Broadcast testing transition failed: %s", exc)
    transition_broadcast(state.broadcast_id, "live")
    state.live_started = True
    _save_state(state)
    return state


def _ensure_live_encoder(state: ControllerState, fixture: dict[str, Any]) -> ControllerState:
    short = (fixture["status"]["short"] or "").upper()
    if short not in LIVE_STATUSES or not state.live_started:
        return state
    if is_running():
        if settings.LIVECOMM_ENABLED and not is_commentary_worker_running():
            logger.warning("Commentary worker is not healthy during live fixture %s; restarting worker", fixture["id"])
            ensure_commentary_worker(state.fixture_id)
        return state

    logger.warning(
        "Encoder stack is not healthy during live fixture %s (%s); restarting encoder",
        fixture["id"],
        short,
    )
    stop_encoder()
    start_encoder(state.fixture_id)

    details = get_broadcast(state.broadcast_id)
    if details.life_cycle_status == "live":
        return state
    if details.life_cycle_status == "testing":
        transition_broadcast(state.broadcast_id, "live")
        return state
    if details.life_cycle_status == "complete":
        raise LiveStreamError(f"Broadcast {state.broadcast_id} completed while fixture is still live")

    try:
        transition_broadcast(state.broadcast_id, "testing")
    except Exception as exc:
        logger.warning("Broadcast testing transition failed after encoder restart: %s", exc)
    transition_broadcast(state.broadcast_id, "live")
    return state


def _complete_broadcast(state: ControllerState) -> bool:
    details = get_broadcast(state.broadcast_id)
    if details.life_cycle_status == "complete":
        stop_encoder()
        _clear_state()
        return True
    if details.life_cycle_status in {"created", "ready"}:
        if is_running():
            stop_encoder()
        try:
            delete_broadcast(state.broadcast_id)
        except Exception as exc:
            logger.warning("Could not delete non-started broadcast %s: %s", state.broadcast_id, exc)
        _clear_state()
        return True
    if details.life_cycle_status != "complete":
        details = transition_broadcast(state.broadcast_id, "complete")
    if details.life_cycle_status != "complete":
        raise LiveStreamError(
            f"Broadcast {state.broadcast_id} did not reach complete state (current={details.life_cycle_status})"
        )
    stop_encoder()
    _clear_state()
    return True


def _handle_fixture(state: ControllerState | None, fixture: dict[str, Any]) -> ControllerState:
    short = (fixture["status"]["short"] or "").upper()
    state = _ensure_broadcast(state, fixture)

    if short in LIVE_STATUSES and not state.live_started:
        logger.info("Fixture %s is live (%s); starting broadcast", fixture["id"], short)
        state = _transition_live(state)
    state = _ensure_live_encoder(state, fixture)

    if short in FINISHED_STATUSES:
        now_ts = int(time.time())
        if state.finished_detected_at is None:
            state.finished_detected_at = now_ts
            _save_state(state)
            logger.info("Fixture %s finished (%s); grace timer started", fixture["id"], short)
        elif now_ts - state.finished_detected_at >= settings.LIVESTREAM_POSTMATCH_GRACE_SECONDS:
            logger.info("Fixture %s grace complete; completing broadcast", fixture["id"])
            if _complete_broadcast(state):
                return ControllerState(fixture_id=0, broadcast_id="", title="", completed=True)
    else:
        if state.finished_detected_at is not None:
            state.finished_detected_at = None
            _save_state(state)

    return state


def run_controller(*, once: bool = False, fixture_id_override: int | None = None) -> None:
    _setup_logging()
    logger.info(
        "Starting livestream controller for league=%s season=%s poll=%ss",
        settings.LIVESTREAM_TARGET_LEAGUE_ID,
        settings.LIVESTREAM_TARGET_SEASON,
        settings.LIVESTREAM_POLL_SECONDS,
    )
    state = _load_state()
    override_fixture_id = fixture_id_override or (settings.LIVESTREAM_FIXTURE_ID or None)
    if override_fixture_id:
        logger.info("Fixture override enabled: fixture_id=%s", override_fixture_id)

    while True:
        try:
            now = datetime.now(UTC)
            fixtures = _load_today_fixtures()
            if override_fixture_id:
                fixture = _api().fixture(int(override_fixture_id))
            elif state and state.fixture_id:
                fixture = _api().fixture(state.fixture_id)
            else:
                fixture = _select_candidate(fixtures, now)

            if fixture:
                state = _handle_fixture(None if state and state.completed else state, fixture)
                if state.completed:
                    state = None
            else:
                if state and state.fixture_id and not state.completed:
                    fixture = _api().fixture(state.fixture_id)
                    state = _handle_fixture(state, fixture)
                    if state.completed:
                        state = None
                else:
                    logger.info("No target fixture found for %s", date.today().isoformat())
        except (ApiFootballError, LiveStreamError, EncoderError, Exception) as exc:
            logger.exception("Controller cycle failed: %s", exc)

        if once:
            return
        time.sleep(max(5, settings.LIVESTREAM_POLL_SECONDS))


def main() -> None:
    parser = argparse.ArgumentParser(description="Automate FIFA World Cup livestream start/stop.")
    parser.add_argument("--once", action="store_true", help="Run one controller cycle and exit.")
    parser.add_argument("--fixture-id", type=int, help="Force one specific fixture ID for testing/override.")
    args = parser.parse_args()
    run_controller(once=args.once, fixture_id_override=args.fixture_id)


if __name__ == "__main__":
    main()
