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
    stats_insights: dict[str, Any] = field(default_factory=dict)
    top_players: list[dict[str, Any]] = field(default_factory=list)
    player_of_match: dict[str, Any] = field(default_factory=dict)
    lineups_summary: dict[str, Any] = field(default_factory=dict)
    standings: dict[str, Any] | None = None
    standings_summary: dict[str, Any] = field(default_factory=dict)
    knockout_message: str = ""
    standings_error: str = ""
    match_result_type: str = ""
    result_tags: list[str] = field(default_factory=list)

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
            "stats_insights": self.stats_insights,
            "top_players": self.top_players,
            "player_of_match": self.player_of_match,
            "lineups_summary": self.lineups_summary,
            "standings": self.standings,
            "standings_summary": self.standings_summary,
            "knockout_message": self.knockout_message,
            "standings_error": self.standings_error,
            "match_result_type": self.match_result_type,
            "result_tags": self.result_tags,
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
        "elapsed": _safe_int(event.get("elapsed")),
        "extra": _safe_int(event.get("extra")),
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


def _event_identity(event: dict[str, Any]) -> tuple[Any, ...]:
    return (
        event.get("elapsed"),
        event.get("extra"),
        event.get("team"),
        event.get("player"),
        event.get("type"),
        event.get("detail"),
    )


def _dedupe_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[Any, ...]] = set()
    unique: list[dict[str, Any]] = []
    for event in events:
        key = _event_identity(event)
        if key in seen:
            continue
        seen.add(key)
        unique.append(event)
    return unique


def _append_derived_event(events: list[dict[str, Any]], event: dict[str, Any], importance: str) -> None:
    key = _event_identity(event)
    for existing in events:
        if _event_identity(existing) != key:
            continue
        tags = list(existing.get("importance_tags") or [])
        if not tags and existing.get("importance"):
            tags.append(existing["importance"])
        if importance not in tags:
            tags.append(importance)
        existing["importance_tags"] = tags
        # Keep the primary label stable for narration, but expose all tags.
        existing["importance"] = tags[0]
        return

    item = dict(event)
    item["importance"] = importance
    item["importance_tags"] = [importance]
    events.append(item)


def _safe_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        value = value.strip().replace("%", "")
        try:
            return int(float(value))
        except ValueError:
            return 0
    return 0


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _safe_percent(value: Any) -> float:
    if isinstance(value, str):
        value = value.strip().replace("%", "")
    return _safe_float(value)


def _is_defensive_position(position: str) -> bool:
    return position.upper() in {"G", "GK", "D", "DEF"}


def _player_score(player: dict[str, Any]) -> float:
    rating = _safe_float(player.get("rating"))
    goals = _safe_int(player.get("goals"))
    assists = _safe_int(player.get("assists"))
    shots_on = _safe_int(player.get("shots_on"))
    saves = _safe_int(player.get("saves"))
    tackles = _safe_int(player.get("tackles"))
    interceptions = _safe_int(player.get("interceptions"))
    key_passes = _safe_int(player.get("key_passes"))
    penalty_saved = _safe_int(player.get("penalty_saved"))
    clean_sheet_bonus = 3 if player.get("clean_sheet") and _is_defensive_position(player.get("position") or "") else 0
    return (
        rating * 5
        + goals * 10
        + assists * 7
        + shots_on * 2
        + key_passes * 2
        + saves * 3
        + penalty_saved * 6
        + tackles * 2
        + interceptions * 2
        + clean_sheet_bonus
    )


def _team_goals_against(team_name: str, home_team: str, away_team: str, home_goals: int | None, away_goals: int | None) -> int:
    if team_name == home_team:
        return _safe_int(away_goals)
    if team_name == away_team:
        return _safe_int(home_goals)
    return 0


def _top_players(
    players: list[dict[str, Any]],
    *,
    home_team: str,
    away_team: str,
    home_goals: int | None,
    away_goals: int | None,
    limit: int = 3,
) -> list[dict[str, Any]]:
    flattened: list[dict[str, Any]] = []
    for team in players:
        team_name = team.get("team_name") or ""
        goals_against = _team_goals_against(team_name, home_team, away_team, home_goals, away_goals)
        for player in team.get("players") or []:
            name = player.get("name") or ""
            if not name:
                continue
            position = player.get("pos") or ""
            item = {
                "name": name,
                "team": team_name,
                "position": position,
                "minutes": player.get("minutes"),
                "rating": player.get("rating"),
                "goals": player.get("goals_total") or 0,
                "assists": player.get("assists") or 0,
                "shots_total": player.get("shots_total") or 0,
                "shots_on": player.get("shots_on") or 0,
                "saves": player.get("saves") or 0,
                "passes_total": player.get("passes_total") or 0,
                "key_passes": player.get("key_passes") or 0,
                "pass_accuracy": player.get("pass_accuracy") or "",
                "tackles": player.get("tackles") or 0,
                "blocks": player.get("blocks") or 0,
                "interceptions": player.get("interceptions") or 0,
                "duels_won": player.get("duels_won") or 0,
                "dribbles_success": player.get("dribbles_success") or 0,
                "penalty_saved": player.get("penalty_saved") or 0,
                "clean_sheet": goals_against == 0 and _is_defensive_position(position),
                "yellow": player.get("yellow") or 0,
                "red": player.get("red") or 0,
            }
            item["motm_score"] = round(_player_score(item), 2)
            flattened.append(item)
    return sorted(flattened, key=lambda player: (player["motm_score"], _safe_float(player.get("rating"))), reverse=True)[:limit]


def _lineups_summary(lineups: list[dict[str, Any]], home_team: str, away_team: str) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for lineup in lineups:
        team_name = lineup.get("team_name") or ""
        key = _team_key(team_name, home_team, away_team)
        if key == "unknown":
            continue
        summary[key] = {
            "team": team_name,
            "formation": lineup.get("formation") or "",
            "coach": lineup.get("coach") or "",
            "starting_xi": [
                {
                    "name": player.get("name") or "",
                    "number": player.get("number"),
                    "position": player.get("pos") or "",
                }
                for player in (lineup.get("start_xi") or [])[:11]
                if player.get("name")
            ],
        }
    return summary


def _standings_summary(
    standings: dict[str, Any] | None,
    home_team_id: int | None,
    away_team_id: int | None,
    home_team: str,
    away_team: str,
) -> dict[str, Any]:
    if not standings:
        return {}
    rows = standings.get("rows") or []
    by_id = {row.get("team_id"): row for row in rows if row.get("team_id") is not None}
    home_row = by_id.get(home_team_id) or next((row for row in rows if row.get("team_name") == home_team), None)
    away_row = by_id.get(away_team_id) or next((row for row in rows if row.get("team_name") == away_team), None)
    return {
        "title": standings.get("title") or "",
        "group": standings.get("group") or "",
        "leader": rows[0] if rows else None,
        "home": home_row,
        "away": away_row,
        "rows": rows,
    }


def _numeric_stat(statistics: dict[str, dict[str, str]], team: str, key: str) -> float:
    return _safe_percent((statistics.get(team) or {}).get(key))


def _leader(statistics: dict[str, dict[str, str]], home_team: str, away_team: str, key: str) -> str:
    home_value = _numeric_stat(statistics, home_team, key)
    away_value = _numeric_stat(statistics, away_team, key)
    if home_value > away_value:
        return home_team
    if away_value > home_value:
        return away_team
    return "Level"


def _stats_insights(
    statistics: dict[str, dict[str, str]],
    home_team: str,
    away_team: str,
    home_goals: int | None,
    away_goals: int | None,
) -> dict[str, Any]:
    if not statistics:
        return {}
    home_shots = _numeric_stat(statistics, home_team, "shots")
    away_shots = _numeric_stat(statistics, away_team, "shots")
    home_sot = _numeric_stat(statistics, home_team, "shots_on_goal")
    away_sot = _numeric_stat(statistics, away_team, "shots_on_goal")
    home_goal_rate = (_safe_int(home_goals) / home_sot) if home_sot else 0
    away_goal_rate = (_safe_int(away_goals) / away_sot) if away_sot else 0
    dominant_scores = {
        home_team: int(_leader(statistics, home_team, away_team, "possession") == home_team)
        + int(home_shots > away_shots)
        + int(home_sot > away_sot),
        away_team: int(_leader(statistics, home_team, away_team, "possession") == away_team)
        + int(away_shots > home_shots)
        + int(away_sot > home_sot),
    }
    dominant_team = max(dominant_scores, key=dominant_scores.get) if max(dominant_scores.values()) else "Level"
    clinical_team = "Level"
    if home_goal_rate > away_goal_rate:
        clinical_team = home_team
    elif away_goal_rate > home_goal_rate:
        clinical_team = away_team
    return {
        "dominant_team": dominant_team,
        "clinical_team": clinical_team,
        "possession_leader": _leader(statistics, home_team, away_team, "possession"),
        "shot_leader": _leader(statistics, home_team, away_team, "shots"),
        "shots_on_target_leader": _leader(statistics, home_team, away_team, "shots_on_goal"),
        "corner_leader": _leader(statistics, home_team, away_team, "corners"),
        "passing_leader": _leader(statistics, home_team, away_team, "pass_accuracy"),
    }


def _score_progression(match_goals: list[dict[str, Any]]) -> list[dict[str, Any]]:
    score = {"home": 0, "away": 0}
    progression = []
    for goal in match_goals:
        key = goal.get("team_key")
        if key in score:
            score[key] += 1
        item = dict(goal)
        item["score_after_goal"] = f"{score['home']}-{score['away']}"
        item["score_home"] = score["home"]
        item["score_away"] = score["away"]
        progression.append(item)
    return progression


def _result_tags(
    match_goals: list[dict[str, Any]],
    winner: str,
    home_team: str,
    away_team: str,
    home_goals: int | None,
    away_goals: int | None,
    red_cards: list[dict[str, Any]],
) -> list[str]:
    if winner == "Draw":
        return ["draw"]
    tags: list[str] = []
    goal_diff = abs(_safe_int(home_goals) - _safe_int(away_goals))
    if goal_diff >= 3:
        tags.append("dominant_win")
    if _safe_int(home_goals) == 0 or _safe_int(away_goals) == 0:
        tags.append("clean_sheet")
    progression = _score_progression(match_goals)
    winner_key = _team_key(winner, home_team, away_team)
    if any(
        (winner_key == "home" and item["score_home"] < item["score_away"])
        or (winner_key == "away" and item["score_away"] < item["score_home"])
        for item in progression
    ):
        tags.append("comeback")
    if progression:
        last_lead_goal = None
        for item in progression:
            if winner_key == "home" and item["score_home"] > item["score_away"]:
                last_lead_goal = item
            elif winner_key == "away" and item["score_away"] > item["score_home"]:
                last_lead_goal = item
        if last_lead_goal and _safe_int(last_lead_goal.get("elapsed")) >= 85:
            tags.append("late_winner")
    if red_cards:
        tags.append("red_card")
    return tags or ["narrow_win"]


def _primary_result_type(tags: list[str]) -> str:
    for tag in ["comeback", "late_winner", "dominant_win", "draw", "red_card", "clean_sheet", "narrow_win"]:
        if tag in tags:
            return tag
    return tags[0] if tags else ""


def _derived_important_events(
    match_goals: list[dict[str, Any]],
    red_cards: list[dict[str, Any]],
    penalties: list[dict[str, Any]],
    winner: str,
    home_team: str,
    away_team: str,
) -> list[dict[str, Any]]:
    derived: list[dict[str, Any]] = []
    progression = _score_progression(match_goals)
    if progression:
        _append_derived_event(derived, progression[0], "opening_goal")
    winner_key = _team_key(winner, home_team, away_team)
    winning_goal = None
    for index, item in enumerate(progression):
        if winner_key == "home" and item["score_home"] > item["score_away"]:
            if all(later["score_home"] > later["score_away"] for later in progression[index:]):
                winning_goal = item
                break
        if winner_key == "away" and item["score_away"] > item["score_home"]:
            if all(later["score_away"] > later["score_home"] for later in progression[index:]):
                winning_goal = item
                break
    if winning_goal:
        _append_derived_event(derived, winning_goal, "winning_goal")
    for item in progression:
        if item.get("extra") and _safe_int(item.get("elapsed")) <= 45:
            _append_derived_event(derived, item, "first_half_stoppage_goal")
        if abs(_safe_int(item.get("score_home")) - _safe_int(item.get("score_away"))) >= 3:
            _append_derived_event(derived, item, "game_killing_goal")
    for event in red_cards:
        _append_derived_event(derived, event, "red_card")
    for event in penalties:
        _append_derived_event(derived, event, "penalty_event")
    for item in progression:
        if _safe_int(item.get("elapsed")) >= 80:
            _append_derived_event(derived, item, "late_goal")
    return _dedupe_events(sorted(derived, key=_event_sort_key))


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
    winner = _winner(fixture, home_team, away_team)
    important_events = _derived_important_events(
        match_goals,
        red_cards,
        penalties,
        winner,
        home_team,
        away_team,
    )
    statistics = data.get("statistics") or {}
    top_players = _top_players(
        data.get("players") or [],
        home_team=home_team,
        away_team=away_team,
        home_goals=goals.get("home"),
        away_goals=goals.get("away"),
    )
    result_tags = _result_tags(
        match_goals,
        winner,
        home_team,
        away_team,
        goals.get("home"),
        goals.get("away"),
        red_cards,
    )
    standings = data.get("standings")

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
        winner=winner,
        first_half_goals=first_half,
        second_half_goals=second_half,
        goals=match_goals,
        yellow_cards=yellow_cards,
        red_cards=red_cards,
        penalties=penalties,
        substitutions=substitutions,
        important_events=important_events,
        statistics=statistics,
        stats_insights=_stats_insights(statistics, home_team, away_team, goals.get("home"), goals.get("away")),
        top_players=top_players,
        player_of_match=top_players[0] if top_players else {},
        lineups_summary=_lineups_summary(data.get("lineups") or [], home_team, away_team),
        standings=standings,
        standings_summary=_standings_summary(
            standings,
            home.get("id"),
            away.get("id"),
            home_team,
            away_team,
        ),
        knockout_message=data.get("knockout_message") or "",
        standings_error=data.get("standings_error") or "",
        match_result_type=_primary_result_type(result_tags),
        result_tags=result_tags,
    )
