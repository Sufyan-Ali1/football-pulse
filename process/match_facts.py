"""Deterministic post-match fact extraction from API-Football payloads."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


FINISHED_STATUSES = {"FT", "AET", "PEN"}


@dataclass
class MatchFacts:
    fixture_id: int
    competition: str
    competition_type: str
    round_name: str
    season: int | None
    match_date: str
    venue: str
    home_team: str
    away_team: str
    home_team_id: int | None
    away_team_id: int | None
    home_goals: int | None
    away_goals: int | None
    status: str
    winner: str
    first_half_goals: dict[str, int] = field(default_factory=dict)
    second_half_goals: dict[str, int] = field(default_factory=dict)
    goals: list[dict[str, Any]] = field(default_factory=list)
    yellow_cards: list[dict[str, Any]] = field(default_factory=list)
    red_cards: list[dict[str, Any]] = field(default_factory=list)
    penalties: list[dict[str, Any]] = field(default_factory=list)
    substitutions: list[dict[str, Any]] = field(default_factory=list)
    important_events: list[dict[str, Any]] = field(default_factory=list)
    statistics: dict[str, dict[str, str]] = field(default_factory=dict)
    top_players: list[dict[str, Any]] = field(default_factory=list)
    standings: dict[str, Any] | None = None
    standings_error: str = ""

    @property
    def scoreline(self) -> str:
        return f"{self.home_goals}-{self.away_goals}"

    def to_dict(self) -> dict[str, Any]:
        return {
            "fixture_id": self.fixture_id,
            "competition": self.competition,
            "competition_type": self.competition_type,
            "round_name": self.round_name,
            "season": self.season,
            "match_date": self.match_date,
            "venue": self.venue,
            "home_team": self.home_team,
            "away_team": self.away_team,
            "home_team_id": self.home_team_id,
            "away_team_id": self.away_team_id,
            "home_goals": self.home_goals,
            "away_goals": self.away_goals,
            "final_score": self.scoreline,
            "status": self.status,
            "winner": self.winner,
            "first_half_goals": self.first_half_goals,
            "second_half_goals": self.second_half_goals,
            "goals": self.goals,
            "yellow_cards": self.yellow_cards,
            "red_cards": self.red_cards,
            "penalties": self.penalties,
            "substitutions": self.substitutions,
            "important_events": self.important_events,
            "statistics": self.statistics,
            "top_players": self.top_players,
            "standings": self.standings,
            "standings_error": self.standings_error,
        }


def is_finished_fixture(fixture: dict[str, Any]) -> bool:
    return str((fixture.get("status") or {}).get("short") or "").upper() in FINISHED_STATUSES


def _event_minute(event: dict[str, Any]) -> str:
    elapsed = event.get("elapsed")
    extra = event.get("extra")
    if elapsed is None:
        return ""
    return f"{elapsed}+{extra}'" if extra else f"{elapsed}'"


def _event_sort_key(event: dict[str, Any]) -> tuple[int, int]:
    elapsed = event.get("elapsed")
    extra = event.get("extra")
    return (
        int(elapsed) if isinstance(elapsed, int) else 999,
        int(extra) if isinstance(extra, int) else 0,
    )


def _team_key(team: str, home_team: str, away_team: str) -> str:
    if team == home_team:
        return "home"
    if team == away_team:
        return "away"
    return "unknown"


def _normalize_event(event: dict[str, Any], home_team: str, away_team: str) -> dict[str, Any]:
    return {
        "minute": _event_minute(event),
        "elapsed": event.get("elapsed"),
        "extra": event.get("extra"),
        "team": event.get("team") or "",
        "team_key": _team_key(event.get("team") or "", home_team, away_team),
        "player": event.get("player") or "",
        "assist": event.get("assist") or "",
        "type": event.get("type") or "",
        "detail": event.get("detail") or "",
        "comments": event.get("comments") or "",
    }


def _is_goal(event: dict[str, Any]) -> bool:
    if str(event.get("type") or "").lower() != "goal":
        return False
    detail = str(event.get("detail") or "").lower()
    return "missed" not in detail and "shootout" not in detail


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for event in events:
        key = (
            event.get("elapsed"),
            event.get("extra"),
            event.get("team"),
            event.get("player"),
            event.get("type"),
            event.get("detail"),
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


def _safe_int(value: Any) -> int:
    return value if isinstance(value, int) else 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _player_score(player: dict[str, Any]) -> tuple[float, int, int, int, int]:
    return (
        _safe_float(player.get("rating")),
        _safe_int(player.get("goals")),
        _safe_int(player.get("assists")),
        _safe_int(player.get("shots_on")),
        _safe_int(player.get("minutes")),
    )


def _top_players(players: list[dict[str, Any]], limit: int = 3) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for team in players:
        team_name = team.get("team_name") or ""
        for player in team.get("players") or []:
            name = player.get("name") or ""
            if not name:
                continue
            flattened.append(
                {
                    "name": name,
                    "team": team_name,
                    "position": player.get("pos") or "",
                    "minutes": player.get("minutes"),
                    "rating": player.get("rating"),
                    "goals": player.get("goals_total") or 0,
                    "assists": player.get("assists") or 0,
                    "shots_on": player.get("shots_on") or 0,
                    "yellow": player.get("yellow") or 0,
                    "red": player.get("red") or 0,
                }
            )
    return sorted(flattened, key=_player_score, reverse=True)[:limit]


def _winner(fixture: dict[str, Any], home_team: str, away_team: str) -> str:
    teams = fixture.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    if home.get("winner") is True:
        return home_team
    if away.get("winner") is True:
        return away_team
    goals = fixture.get("goals") or {}
    home_goals = goals.get("home")
    away_goals = goals.get("away")
    if isinstance(home_goals, int) and isinstance(away_goals, int):
        if home_goals > away_goals:
            return home_team
        if away_goals > home_goals:
            return away_team
        return "Draw"
    return ""


def extract_match_facts(data: dict[str, Any]) -> MatchFacts:
    fixture = data.get("fixture") or {}
    league = fixture.get("league") or {}
    teams = fixture.get("teams") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    goals = fixture.get("goals") or {}
    venue = fixture.get("venue") or {}
    status = fixture.get("status") or {}

    home_team = home.get("name") or "Home Team"
    away_team = away.get("name") or "Away Team"
    normalized_events = [
        _normalize_event(event, home_team, away_team)
        for event in sorted(data.get("events") or [], key=_event_sort_key)
    ]

    match_goals = [event for event in normalized_events if _is_goal(event)]
    first_half = {"home": 0, "away": 0}
    second_half = {"home": 0, "away": 0}
    for goal in match_goals:
        key = goal["team_key"]
        if key not in first_half:
            continue
        elapsed = goal.get("elapsed")
        if isinstance(elapsed, int) and elapsed <= 45:
            first_half[key] += 1
        else:
            second_half[key] += 1

    red_cards = [
        event for event in normalized_events
        if str(event.get("type") or "").lower() == "card"
        and "red" in str(event.get("detail") or "").lower()
    ]
    yellow_cards = [
        event for event in normalized_events
        if str(event.get("type") or "").lower() == "card"
        and "yellow" in str(event.get("detail") or "").lower()
    ]
    penalties = [
        event for event in normalized_events
        if "penalty" in str(event.get("detail") or "").lower()
    ]
    substitutions = [
        event for event in normalized_events
        if str(event.get("type") or "").lower() == "subst"
    ]
    important_events = _dedupe_events([
        event for event in normalized_events
        if event in red_cards
        or event in penalties
        or (event in match_goals and isinstance(event.get("elapsed"), int) and event["elapsed"] >= 80)
    ])

    return MatchFacts(
        fixture_id=int(fixture.get("id") or 0),
        competition=league.get("name") or "",
        competition_type=league.get("type") or "",
        round_name=league.get("round") or "",
        season=league.get("season"),
        match_date=fixture.get("date") or "",
        venue=", ".join(part for part in [venue.get("name"), venue.get("city")] if part),
        home_team=home_team,
        away_team=away_team,
        home_team_id=home.get("id"),
        away_team_id=away.get("id"),
        home_goals=goals.get("home"),
        away_goals=goals.get("away"),
        status=status.get("short") or "",
        winner=_winner(fixture, home_team, away_team),
        first_half_goals=first_half,
        second_half_goals=second_half,
        goals=match_goals,
        yellow_cards=yellow_cards,
        red_cards=red_cards,
        penalties=penalties,
        substitutions=substitutions,
        important_events=important_events,
        statistics=data.get("statistics") or {},
        top_players=_top_players(data.get("players") or []),
        standings=data.get("standings"),
        standings_error=data.get("standings_error") or "",
    )
