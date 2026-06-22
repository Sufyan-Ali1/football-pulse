from __future__ import annotations

import hashlib
import json
import logging
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from clients.groq_client import get_groq_client
from config import settings

logger = logging.getLogger(__name__)

LIVE_STATUSES = {"1H", "2H", "ET", "BT", "P", "INT", "SUSP"}
FINISHED_STATUSES = {"FT", "AET", "PEN"}
_EVENT_PRIORITY = {
    "goal": 100,
    "card:red": 96,
    "penalty": 94,
    "var": 92,
    "substitution": 72,
}
_groq = get_groq_client()


@dataclass(slots=True)
class MatchDossier:
    fixture_id: int
    generated_at: int
    home_team_story: str
    away_team_story: str
    key_players: list[dict[str, str]]
    matchup_angles: list[str]
    humor_seeds: list[str]
    fallback_topics: list[str]
    standings_story: str = ""


@dataclass(slots=True)
class CommentaryIntent:
    intent_id: str
    intent_type: str
    priority: int
    target_duration_seconds: int
    dedupe_key: str
    payload: dict[str, Any]
    expires_at: int


@dataclass(slots=True)
class CommentaryClip:
    clip_id: str
    fixture_id: int
    intent_type: str
    priority: int
    estimated_duration_seconds: int
    text: str
    audio_path: str
    created_at: int
    dedupe_key: str
    expires_at: int


@dataclass(slots=True)
class CommentaryState:
    fixture_id: int = 0
    processed_event_keys: list[str] = field(default_factory=list)
    emitted_markers: list[str] = field(default_factory=list)
    last_commentary_at: int = 0
    last_scoreline: str = ""
    recent_lines: list[str] = field(default_factory=list)
    recent_topics: list[str] = field(default_factory=list)
    recent_entities: list[str] = field(default_factory=list)
    recent_jokes: list[str] = field(default_factory=list)
    last_event_at: int = 0
    commentary_pressure: int = 0
    dossier: MatchDossier | None = None

    def processed_set(self) -> set[str]:
        return set(self.processed_event_keys)

    def marker_set(self) -> set[str]:
        return set(self.emitted_markers)


def state_file_path(fixture_id: int) -> Path:
    return Path(settings.LIVECOMM_STATE_DIR) / f"fixture_{fixture_id}.json"


def load_state(path_or_fixture: Path | int | str) -> CommentaryState:
    path = state_file_path(path_or_fixture) if isinstance(path_or_fixture, int) else Path(path_or_fixture)
    if not path.exists():
        return CommentaryState()
    data = json.loads(path.read_text(encoding="utf-8"))
    dossier = data.get("dossier")
    if dossier:
        data["dossier"] = MatchDossier(**dossier)
    return CommentaryState(**data)


def save_state(path_or_fixture: Path | int | str, state: CommentaryState) -> None:
    path = state_file_path(path_or_fixture) if isinstance(path_or_fixture, int) else Path(path_or_fixture)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = asdict(state)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def event_fingerprint(event: dict[str, Any]) -> str:
    parts = [
        str(event.get("type") or "").strip().lower(),
        str(event.get("detail") or "").strip().lower(),
        str(event.get("team_id") or ""),
        str(event.get("player") or "").strip().lower(),
        str(event.get("assist") or "").strip().lower(),
        str(event.get("elapsed") or ""),
        str(event.get("extra") or ""),
    ]
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:24]


def refresh_dossier(data: dict[str, Any], state: CommentaryState, now_ts: int | None = None) -> CommentaryState:
    now_ts = now_ts or int(time.time())
    if state.dossier and state.dossier.fixture_id == data["fixture"]["id"]:
        if now_ts - state.dossier.generated_at < settings.LIVECOMM_DOSSIER_MAX_AGE_SECONDS:
            return state
    state.dossier = build_dossier(data, now_ts)
    return state


def build_dossier(data: dict[str, Any], now_ts: int | None = None) -> MatchDossier:
    now_ts = now_ts or int(time.time())
    fixture = data["fixture"]
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    round_name = fixture["league"]["round"] or fixture["league"]["name"] or "World Cup"
    lineups = data.get("lineups") or []
    players = data.get("players") or []
    standings = data.get("standings")

    lineup_summary = []
    for lineup in lineups:
        starters = [player["name"] for player in lineup.get("start_xi", [])[:5] if player.get("name")]
        lineup_summary.append(
            {
                "team": lineup.get("team_name"),
                "formation": lineup.get("formation") or "",
                "coach": lineup.get("coach") or "",
                "starters": starters,
            }
        )

    player_summary = []
    for team in players:
        team_name = team.get("team_name") or ""
        for player in team.get("players", [])[:8]:
            if player.get("name"):
                player_summary.append(
                    {
                        "team": team_name,
                        "name": player.get("name") or "",
                        "pos": player.get("pos") or "",
                        "rating": str(player.get("rating") or ""),
                        "goals": str(player.get("goals_total") or ""),
                        "shots": str(player.get("shots_total") or ""),
                    }
                )

    prompt = (
        "You are preparing a live football commentary dossier for an always-on scoreboard stream.\n"
        "Use football knowledge and the supplied fixture context to create evergreen, match-relevant talking points.\n"
        "Rules:\n"
        "- Do not invent current-match live incidents.\n"
        "- Keep every item safe to say before or during a match even if the feed is quiet.\n"
        "- Humor should be light, playful, and family-safe.\n"
        "- Avoid defamation, abuse, or edgy jokes.\n"
        "Return JSON with keys: home_team_story, away_team_story, key_players, matchup_angles, humor_seeds, fallback_topics, standings_story.\n"
        f"Fixture: {home} vs {away}\n"
        f"Tournament round: {round_name}\n"
        f"Lineups: {json.dumps(lineup_summary, ensure_ascii=False)}\n"
        f"Players: {json.dumps(player_summary[:12], ensure_ascii=False)}\n"
        f"Standings: {json.dumps(standings or {}, ensure_ascii=False)}\n"
    )

    default = MatchDossier(
        fixture_id=int(fixture["id"]),
        generated_at=now_ts,
        home_team_story=f"{home} are in a major World Cup night and the spotlight is firmly on how they control the tempo.",
        away_team_story=f"{away} have a chance to shape this match with discipline, transitions, and moments from their key players.",
        key_players=default_key_players(data),
        matchup_angles=[
            f"The pace of the match between {home} and {away}.",
            f"Which midfield can control possession between {home} and {away}.",
            f"Whether the bigger chances begin to arrive as the game settles.",
        ],
        humor_seeds=[
            "The scoreboard host is still waiting for somebody to test the goalkeeper properly.",
            "At the moment this match is simmering rather than boiling.",
            "The tactics board is getting more work than the net so far.",
        ],
        fallback_topics=[
            f"What the result could mean for {home}.",
            f"What the result could mean for {away}.",
            "How World Cup group games can swing on one moment.",
            "Why substitutions often decide tense tournament matches.",
        ],
        standings_story=build_standings_story(data),
    )

    try:
        response = _groq.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=800,
            temperature=0.8,
            response_format={"type": "json_object"},
        )
        raw = str(response.choices[0].message.content or "").strip()
        payload = json.loads(raw)
        return MatchDossier(
            fixture_id=default.fixture_id,
            generated_at=now_ts,
            home_team_story=str(payload.get("home_team_story") or default.home_team_story).strip(),
            away_team_story=str(payload.get("away_team_story") or default.away_team_story).strip(),
            key_players=_coerce_key_players(payload.get("key_players"), default.key_players),
            matchup_angles=_coerce_str_list(payload.get("matchup_angles"), default.matchup_angles),
            humor_seeds=_coerce_str_list(payload.get("humor_seeds"), default.humor_seeds),
            fallback_topics=_coerce_str_list(payload.get("fallback_topics"), default.fallback_topics),
            standings_story=str(payload.get("standings_story") or default.standings_story).strip(),
        )
    except Exception as exc:
        logger.warning("Live commentary dossier build failed for fixture %s: %s", fixture["id"], exc)
        return default


def select_intents(data: dict[str, Any], state: CommentaryState, queue_depth: int = 0, now_ts: int | None = None) -> list[CommentaryIntent]:
    now_ts = now_ts or int(time.time())
    fixture = data["fixture"]
    status = (fixture["status"]["short"] or "").upper()
    intents: list[CommentaryIntent] = []
    if status not in LIVE_STATUSES and status not in FINISHED_STATUSES and status not in {"NS", "TBD"}:
        return intents

    state = refresh_dossier(data, state, now_ts)
    scoreline = current_scoreline(fixture)
    minute = int(fixture["status"].get("elapsed") or 0)
    processed = state.processed_set()
    markers = state.marker_set()

    for event in reversed(data.get("events") or []):
        key = event_fingerprint(event)
        if key in processed:
            continue
        event_kind = classify_event(event)
        if not event_kind:
            continue
        intents.append(
            CommentaryIntent(
                intent_id=f"event_{key}",
                intent_type="event_reaction",
                priority=_EVENT_PRIORITY.get(event_kind, 90),
                target_duration_seconds=9 if event_kind == "substitution" else 12,
                dedupe_key=key,
                payload={
                    "fixture": fixture,
                    "event": normalize_commentary_event(event),
                    "event_kind": event_kind,
                    "scoreline": scoreline,
                    "statistics": summarize_statistics(data.get("statistics") or {}, fixture),
                    "recent_events": recent_event_summaries(data.get("events") or [], limit=4),
                    "dossier": dossier_payload(state.dossier),
                },
                expires_at=now_ts + settings.LIVECOMM_EVENT_FOLLOWUP_SECONDS,
            )
        )

    if status in {"NS", "TBD"}:
        intents.extend(prematch_intents(data, state, markers, scoreline, now_ts))
    elif status == "HT":
        marker = f"halftime:{fixture['id']}:{scoreline}"
        if marker not in markers:
            intents.append(
                CommentaryIntent(
                    intent_id=marker,
                    intent_type="halftime_summary",
                    priority=85,
                    target_duration_seconds=14,
                    dedupe_key=marker,
                    payload=build_state_payload(data, "halftime", state),
                    expires_at=now_ts + 600,
                )
            )
    elif status in LIVE_STATUSES:
        if minute <= 3:
            intents.extend(kickoff_intents(data, state, markers, scoreline, now_ts))
        if data.get("events") and now_ts - state.last_event_at <= settings.LIVECOMM_EVENT_FOLLOWUP_SECONDS:
            intents.extend(event_followup_intents(data, state, minute, scoreline, now_ts))
        if (
            queue_depth < 2
            or now_ts - state.last_commentary_at >= settings.LIVECOMM_MIN_GAP_SECONDS
            or now_ts - state.last_commentary_at >= settings.LIVECOMM_MAX_SILENCE_SECONDS
        ):
            intents.extend(continuity_intents(data, state, minute, scoreline, now_ts))
    elif status in FINISHED_STATUSES:
        marker = f"fulltime:{fixture['id']}:{scoreline}"
        if marker not in markers:
            intents.append(
                CommentaryIntent(
                    intent_id=marker,
                    intent_type="fulltime_wrap",
                    priority=88,
                    target_duration_seconds=14,
                    dedupe_key=marker,
                    payload=build_state_payload(data, "fulltime", state),
                    expires_at=now_ts + 1800,
                )
            )

    unique: dict[str, CommentaryIntent] = {}
    for intent in intents:
        if intent.expires_at <= now_ts:
            continue
        if intent.dedupe_key in unique and unique[intent.dedupe_key].priority >= intent.priority:
            continue
        unique[intent.dedupe_key] = intent

    selected = sorted(unique.values(), key=lambda item: (-item.priority, item.intent_id))
    limit = max(settings.LIVECOMM_MAX_QUEUE_DEPTH, 6 if status in LIVE_STATUSES else settings.LIVECOMM_MAX_QUEUE_DEPTH)
    return selected[:limit]


def prematch_intents(data: dict[str, Any], state: CommentaryState, markers: set[str], scoreline: str, now_ts: int) -> list[CommentaryIntent]:
    fixture = data["fixture"]
    intents: list[CommentaryIntent] = []
    minute_marker = f"prematch_intro:{fixture['id']}"
    if minute_marker not in markers:
        intents.append(
            CommentaryIntent(
                intent_id=minute_marker,
                intent_type="prematch_intro",
                priority=70,
                target_duration_seconds=11,
                dedupe_key=minute_marker,
                payload=build_state_payload(data, "prematch_intro", state),
                expires_at=now_ts + 1800,
            )
        )
    lineup_marker = f"lineup_analysis:{fixture['id']}"
    if lineup_marker not in markers and (data.get("lineups") or []):
        intents.append(
            CommentaryIntent(
                intent_id=lineup_marker,
                intent_type="lineup_analysis",
                priority=68,
                target_duration_seconds=12,
                dedupe_key=lineup_marker,
                payload=build_state_payload(data, "lineup_analysis", state),
                expires_at=now_ts + 1800,
            )
        )
    return intents


def kickoff_intents(data: dict[str, Any], state: CommentaryState, markers: set[str], scoreline: str, now_ts: int) -> list[CommentaryIntent]:
    fixture = data["fixture"]
    intents: list[CommentaryIntent] = []
    kickoff_marker = f"kickoff_intro:{fixture['id']}"
    if kickoff_marker not in markers:
        intents.append(
            CommentaryIntent(
                intent_id=kickoff_marker,
                intent_type="kickoff_intro",
                priority=80,
                target_duration_seconds=8,
                dedupe_key=kickoff_marker,
                payload=build_state_payload(data, "kickoff_intro", state),
                expires_at=now_ts + 300,
            )
        )
    return intents


def event_followup_intents(
    data: dict[str, Any],
    state: CommentaryState,
    minute: int,
    scoreline: str,
    now_ts: int,
) -> list[CommentaryIntent]:
    fixture = data["fixture"]
    events = recent_event_summaries(data.get("events") or [], limit=2)
    if not events:
        return []
    latest = events[-1]
    seed = f"{latest.get('team', '')}:{latest.get('player', '')}:{latest.get('minute', '')}:{scoreline}"
    return [
        CommentaryIntent(
            intent_id=f"event_followup_{fixture['id']}_{hashlib.sha256(seed.encode('utf-8')).hexdigest()[:10]}",
            intent_type="event_followup",
            priority=78,
            target_duration_seconds=10,
            dedupe_key=f"event_followup:{fixture['id']}:{seed}",
            payload={
                **build_state_payload(data, "event_followup", state),
                "latest_event": latest,
                "match_minute": minute,
            },
            expires_at=now_ts + settings.LIVECOMM_EVENT_FOLLOWUP_SECONDS,
        )
    ]


def continuity_intents(data: dict[str, Any], state: CommentaryState, minute: int, scoreline: str, now_ts: int) -> list[CommentaryIntent]:
    fixture = data["fixture"]
    topics = topic_rotation(data, state, minute)
    intents: list[CommentaryIntent] = []
    for idx, topic in enumerate(topics[:4]):
        dedupe = f"{topic['type']}:{fixture['id']}:{topic['seed']}"
        intents.append(
            CommentaryIntent(
                intent_id=f"{topic['type']}_{topic['seed']}",
                intent_type=topic["type"],
                priority=topic["priority"] - idx,
                target_duration_seconds=topic["duration"],
                dedupe_key=dedupe,
                payload={
                    **build_state_payload(data, topic["type"], state),
                    "topic_seed": topic["seed"],
                    "topic_label": topic["label"],
                    "topic_entity": topic.get("entity", ""),
                },
                expires_at=now_ts + 90,
            )
        )
    return intents


def topic_rotation(data: dict[str, Any], state: CommentaryState, minute: int) -> list[dict[str, Any]]:
    fixture = data["fixture"]
    dossier = state.dossier or build_dossier(data)
    stats = summarize_statistics(data.get("statistics") or {}, fixture)
    players = standout_players(data)
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]

    candidates: list[dict[str, Any]] = []
    phase = match_phase(minute, (fixture["status"]["short"] or "").upper())
    if phase == "opening":
        candidates.extend(
            [
                {"type": "early_match_scene_setter", "label": "Opening match scene", "seed": f"opening-{minute}", "priority": 74, "duration": 8},
                {"type": "lineup_analysis", "label": "Opening lineup look", "seed": f"lineup-{minute}", "priority": 71, "duration": 9},
                {"type": "kickoff_vibe", "label": "Kickoff energy", "seed": f"kickoff-vibe-{minute}", "priority": 70, "duration": 8},
            ]
        )
    if stats:
        candidates.append({"type": "stat_based_analysis", "label": "Live stats read", "seed": f"stats-{minute}", "priority": 70, "duration": 9})
        candidates.append({"type": "momentum_summary", "label": "Momentum summary", "seed": f"momentum-{minute}", "priority": 69, "duration": 9})
        candidates.append({"type": "tactical_read", "label": "Tactical read", "seed": f"tactics-{minute}", "priority": 68, "duration": 9})
        candidates.append({"type": "pressure_watch", "label": "Pressure watch", "seed": f"pressure-{minute}", "priority": 67, "duration": 8})
    if players:
        for player in players[:3]:
            candidates.append(
                {
                    "type": "player_spotlight",
                    "label": f"Player spotlight {player['name']}",
                    "seed": f"player-{player['name']}-{minute}",
                    "entity": player["name"],
                    "priority": 68,
                    "duration": 8,
                }
            )
    for player in default_key_players(data)[:2]:
        if not player.get("name"):
            continue
        candidates.append(
            {
                "type": "player_story",
                "label": f"Player story {player['name']}",
                "seed": f"story-{player['name']}-{minute}",
                "entity": player["name"],
                "priority": 66,
                "duration": 8,
            }
        )
    candidates.append({"type": "team_storyline", "label": home, "seed": f"team-{home}-{minute}", "entity": home, "priority": 66, "duration": 9})
    candidates.append({"type": "team_storyline", "label": away, "seed": f"team-{away}-{minute}", "entity": away, "priority": 65, "duration": 9})
    if dossier.standings_story:
        candidates.append({"type": "tournament_context", "label": "Tournament stakes", "seed": f"stakes-{minute}", "priority": 64, "duration": 8})
    for idx, topic in enumerate(dossier.matchup_angles[:2]):
        candidates.append({"type": "tournament_context", "label": topic, "seed": f"angle-{idx}-{minute}", "priority": 63 - idx, "duration": 8})
    for idx, topic in enumerate(dossier.fallback_topics[:2]):
        candidates.append({"type": "continuity_filler", "label": topic, "seed": f"filler-{idx}-{minute}", "priority": 58 - idx, "duration": 7})
    for idx, topic in enumerate(dossier.humor_seeds[:2]):
        candidates.append({"type": "humor_banter", "label": topic, "seed": f"joke-{idx}-{minute}", "priority": 57 - idx, "duration": 7})
    candidates.append({"type": "narrative_bridge", "label": "Narrative bridge", "seed": f"bridge-{minute}", "priority": 56, "duration": 7})

    filtered: list[dict[str, Any]] = []
    used_types = set(state.recent_topics[-3:])
    used_entities = set(entity.casefold() for entity in state.recent_entities[-4:])
    used_jokes = set(j.casefold() for j in state.recent_jokes[-3:])
    for candidate in candidates:
        candidate_type = candidate["type"]
        entity = str(candidate.get("entity") or "").casefold()
        label = str(candidate.get("label") or "")
        if candidate_type in used_types:
            continue
        if entity and entity in used_entities:
            continue
        if candidate_type == "humor_banter" and label.casefold() in used_jokes:
            continue
        filtered.append(candidate)
    return filtered or candidates


def should_emit_intent(intent: CommentaryIntent, state: CommentaryState, now_ts: int | None = None) -> bool:
    now_ts = now_ts or int(time.time())
    if intent.intent_type in {"event_reaction", "event_followup", "kickoff_intro", "halftime_summary", "fulltime_wrap"}:
        return True
    return now_ts - state.last_commentary_at >= max(2, settings.LIVECOMM_MIN_GAP_SECONDS)


def mark_intent_emitted(state: CommentaryState, intent: CommentaryIntent, line: str, now_ts: int | None = None) -> CommentaryState:
    now_ts = now_ts or int(time.time())
    processed = state.processed_set()
    markers = state.marker_set()
    if intent.intent_type == "event_reaction":
        processed.add(intent.dedupe_key)
        state.last_event_at = now_ts
    else:
        markers.add(intent.dedupe_key)
    state.processed_event_keys = sorted(processed)[-800:]
    state.emitted_markers = sorted(markers)[-800:]
    state.last_commentary_at = now_ts
    state.last_scoreline = intent.payload.get("scoreline") or state.last_scoreline
    state.recent_lines = (state.recent_lines + [line])[-10:]
    state.recent_topics = (state.recent_topics + [intent.intent_type])[-10:]
    topic_entity = str(intent.payload.get("topic_entity") or "").strip()
    if topic_entity:
        state.recent_entities = (state.recent_entities + [topic_entity])[-10:]
    if intent.intent_type == "humor_banter":
        topic_label = str(intent.payload.get("topic_label") or "").strip()
        if topic_label:
            state.recent_jokes = (state.recent_jokes + [topic_label])[-10:]
    state.commentary_pressure = 0
    return state


def dossier_payload(dossier: MatchDossier | None) -> dict[str, Any]:
    if not dossier:
        return {}
    return {
        "home_team_story": dossier.home_team_story,
        "away_team_story": dossier.away_team_story,
        "key_players": dossier.key_players[:5],
        "matchup_angles": dossier.matchup_angles[:4],
        "humor_seeds": dossier.humor_seeds[:3],
        "fallback_topics": dossier.fallback_topics[:4],
        "standings_story": dossier.standings_story,
    }


def build_state_payload(data: dict[str, Any], mode: str, state: CommentaryState) -> dict[str, Any]:
    fixture = data["fixture"]
    return {
        "fixture": fixture,
        "mode": mode,
        "scoreline": current_scoreline(fixture),
        "statistics": summarize_statistics(data.get("statistics") or {}, fixture),
        "goal_scorers": data.get("goal_scorers") or {},
        "recent_events": recent_event_summaries(data.get("events") or [], limit=6),
        "lineups": compact_lineups(data.get("lineups") or []),
        "standings_story": build_standings_story(data),
        "dossier": dossier_payload(state.dossier),
    }


def write_commentary(intent: CommentaryIntent, state: CommentaryState) -> str:
    payload = json.dumps(intent.payload, ensure_ascii=False)
    tone_rules = (
        "Tone: sound like a sharp live football host with natural rhythm, personality, and variety.\n"
        "Be funny, high-energy, opinionated, and engaging, but still coherent and safe for a broad audience.\n"
        "Humor must be light and playful, not abusive, offensive, or fabricated as live fact.\n"
    )
    prompt = (
        "You are the live host for a football scoreboard stream.\n"
        "Write a spoken commentary clip in English.\n"
        f"{tone_rules}"
        "Rules:\n"
        "- Use supplied live facts as current-match truth.\n"
        "- You may use dossier context and general football knowledge as background color, tactical interpretation, player context, tournament stakes, and entertaining banter.\n"
        "- Do not claim unseen live micro-events as facts. No invented passes, tackles, shots, saves, crowd reactions, or referee actions unless provided in the feed.\n"
        "- Do not sound templated. Every clip should feel freshly phrased and stream-specific.\n"
        "- Make the line feel spoken, not written: rhythm, punch, emphasis, and natural host energy.\n"
        "- 1 to 4 sentences maximum.\n"
        "- For event commentary, react to the event and then expand with smart football context.\n"
        "- For filler commentary, keep viewers engaged with football analysis, player narratives, tactical reads, stakes, humor, or momentum talk.\n"
        "- It is acceptable to speculate about pressure, rhythm, danger, or game state if it is clearly grounded in the supplied score, time, stats, lineups, and dossier.\n"
        "- Avoid saying you do not know something; pivot naturally into safe football context.\n"
        "- No profanity.\n"
        f"- Commentary type: {intent.intent_type}\n"
        f"- Target duration: about {intent.target_duration_seconds} seconds\n"
        f"- Avoid repeating these recent lines: {json.dumps(state.recent_lines[-4:], ensure_ascii=False)}\n"
        f"- Current topic label: {intent.payload.get('topic_label', '')}\n"
        f"- Match data: {payload}\n"
        "Return plain text only."
    )
    try:
        response = _groq.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=260,
            temperature=1.05,
        )
        text = str(response.choices[0].message.content or "").strip()
        text = re.sub(r"\s+", " ", text)
        if text:
            return text
    except Exception as exc:
        logger.warning("Live commentary writer failed for %s: %s", intent.intent_id, exc)
    return fallback_commentary(intent, state)


def fallback_commentary(intent: CommentaryIntent, state: CommentaryState) -> str:
    payload = intent.payload
    fixture = payload["fixture"]
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    scoreline = payload.get("scoreline") or current_scoreline(fixture)
    if intent.intent_type == "event_reaction":
        event = payload["event"]
        minute = event.get("minute") or "this moment"
        player = event.get("player") or "A player"
        team = event.get("team") or "the team"
        detail = event.get("detail") or event.get("type") or "major event"
        return f"{team} have the headline moment in the {minute}, with {player} right in the middle of it. The live feed has that down as {detail}."
    if intent.intent_type == "kickoff_intro":
        return f"We are underway between {home} and {away}, and this one already feels like it could swing on a single big moment."
    if intent.intent_type == "prematch_intro":
        return f"This is {home} against {away}, and there is real World Cup tension around this one before a ball has even been properly kicked."
    if intent.intent_type == "lineup_analysis":
        return f"The lineups are in, and now it is all about whether the big names for {home} and {away} can actually take control on the pitch."
    if intent.intent_type == "halftime_summary":
        return f"It is half-time between {home} and {away}, with the score sitting at {scoreline}. The next phase of this match is where the nerves really start to bite."
    if intent.intent_type == "fulltime_wrap":
        return f"That is full-time between {home} and {away}, and the final score is {scoreline}. Tournament football always finds a way to turn the pressure right to the end."
    topic = str(payload.get("topic_label") or "").strip()
    if topic:
        return f"{home} against {away} is still locked into this contest at {scoreline}. Right now the big talking point is {topic.lower()}."
    return f"{home} and {away} are still trading tension at {scoreline}, and this is the kind of match where one clean moment can rewrite everything."


def queue_clip(queue_dir: Path, clip: CommentaryClip) -> Path:
    queue_dir.mkdir(parents=True, exist_ok=True)
    meta_path = queue_dir / f"{clip.clip_id}.json"
    meta_path.write_text(json.dumps(asdict(clip), indent=2), encoding="utf-8")
    return meta_path


def current_scoreline(fixture: dict[str, Any]) -> str:
    return f"{fixture['teams']['home']['name']} {fixture['goals']['home'] or 0}-{fixture['goals']['away'] or 0} {fixture['teams']['away']['name']}"


def classify_event(event: dict[str, Any]) -> str:
    event_type = str(event.get("type") or "").strip().lower()
    detail = str(event.get("detail") or "").strip().lower()
    comments = str(event.get("comments") or "").strip().lower()
    haystack = " ".join([event_type, detail, comments])
    if "goal" in event_type and "missed" not in detail and "shootout" not in detail:
        return "goal"
    if "penalty" in haystack:
        return "penalty"
    if "var" in haystack:
        return "var"
    if "red" in detail:
        return "card:red"
    if "subst" in event_type or "substitution" in detail:
        return "substitution"
    return ""


def normalize_commentary_event(event: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": event.get("type") or "",
        "detail": event.get("detail") or "",
        "team": event.get("team") or "",
        "player": event.get("player") or "",
        "assist": event.get("assist") or "",
        "minute": format_event_minute(event),
    }


def recent_event_summaries(events: list[dict[str, Any]], limit: int = 5) -> list[dict[str, str]]:
    picked: list[dict[str, str]] = []
    for event in reversed(events):
        if not classify_event(event):
            continue
        picked.append(normalize_commentary_event(event))
        if len(picked) >= limit:
            break
    picked.reverse()
    return picked


def summarize_statistics(statistics: dict[str, dict[str, str]], fixture: dict[str, Any]) -> list[dict[str, str]]:
    home = fixture["teams"]["home"]["name"]
    away = fixture["teams"]["away"]["name"]
    home_stats = statistics.get(home, {})
    away_stats = statistics.get(away, {})
    labels = [
        ("possession", "possession"),
        ("shots", "shots"),
        ("shots_on_goal", "shots_on_target"),
        ("corners", "corners"),
        ("fouls", "fouls"),
        ("yellow_cards", "yellow_cards"),
        ("red_cards", "red_cards"),
    ]
    rows: list[dict[str, str]] = []
    for source_key, label in labels:
        home_value = str(home_stats.get(source_key, "")).strip()
        away_value = str(away_stats.get(source_key, "")).strip()
        if not home_value and not away_value:
            continue
        rows.append({"label": label, "home": home_value or "-", "away": away_value or "-"})
    return rows


def compact_lineups(lineups: list[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for lineup in lineups:
        result.append(
            {
                "team_name": lineup.get("team_name") or "",
                "formation": lineup.get("formation") or "",
                "coach": lineup.get("coach") or "",
                "start_xi": [player.get("name") for player in lineup.get("start_xi", [])[:6] if player.get("name")],
            }
        )
    return result


def default_key_players(data: dict[str, Any]) -> list[dict[str, str]]:
    lineups = data.get("lineups") or []
    picks: list[dict[str, str]] = []
    for lineup in lineups:
        for player in lineup.get("start_xi", [])[:4]:
            name = player.get("name") or ""
            if not name:
                continue
            picks.append({"name": name, "team": lineup.get("team_name") or "", "reason": f"Starter for {lineup.get('team_name') or 'the team'}"})
    return picks[:6]


def standout_players(data: dict[str, Any]) -> list[dict[str, str]]:
    players = data.get("players") or []
    picked: list[dict[str, str]] = []
    for team in players:
        team_name = team.get("team_name") or ""
        ranked = sorted(
            team.get("players", []),
            key=lambda item: (
                _as_float(item.get("rating")),
                _as_float(item.get("goals_total")),
                _as_float(item.get("shots_total")),
                _as_float(item.get("minutes")),
            ),
            reverse=True,
        )
        for player in ranked[:3]:
            if player.get("name"):
                picked.append({"name": player["name"], "team": team_name, "pos": player.get("pos") or ""})
    return picked[:6]


def build_standings_story(data: dict[str, Any]) -> str:
    standings = data.get("standings")
    fixture = data["fixture"]
    if standings and standings.get("rows"):
        rows = standings["rows"][:4]
        leader = rows[0]["team_name"] if rows else ""
        return f"{leader} currently sit at the top of {standings.get('title') or 'the group table'}."
    round_name = fixture["league"].get("round") or fixture["league"].get("name") or "World Cup"
    return f"This match sits inside {round_name}, where the pressure builds quickly over a single result."


def match_phase(minute: int, status: str) -> str:
    if status == "HT":
        return "halftime"
    if minute <= 12:
        return "opening"
    if minute >= 75:
        return "closing"
    return "middle"


def format_event_minute(event: dict[str, Any]) -> str:
    elapsed = event.get("elapsed")
    extra = event.get("extra")
    if elapsed is None:
        return ""
    minute = str(elapsed)
    if extra:
        minute = f"{minute}+{extra}"
    return f"{minute}'"


def _coerce_key_players(value: Any, default: list[dict[str, str]]) -> list[dict[str, str]]:
    if not isinstance(value, list):
        return default
    result: list[dict[str, str]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        if not name:
            continue
        result.append(
            {
                "name": name,
                "team": str(item.get("team") or "").strip(),
                "reason": str(item.get("reason") or "").strip(),
            }
        )
    return result[:6] or default


def _coerce_str_list(value: Any, default: list[str]) -> list[str]:
    if not isinstance(value, list):
        return default
    items = [str(item).strip() for item in value if str(item).strip()]
    return items[:6] or default


def _as_float(value: Any) -> float:
    try:
        return float(str(value).strip())
    except Exception:
        return 0.0
