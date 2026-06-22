"""
API-Football client for live score dashboards.

Only read endpoints are used. Responses are normalized so the browser UI does
not depend directly on API-Football's nested payload shape.
"""
from __future__ import annotations

import re
import time
from datetime import date
from typing import Any

import requests

from config import settings


class ApiFootballError(RuntimeError):
    pass


class ApiFootballClient:
    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        cache_seconds: int | None = None,
    ) -> None:
        self.api_key = api_key or settings.API_FOOTBALL_KEY
        self.base_url = (base_url or settings.API_FOOTBALL_BASE_URL).rstrip("/")
        self.cache_seconds = cache_seconds or settings.LIVE_SCORE_POLL_SECONDS
        self._cache: dict[tuple[str, tuple[tuple[str, Any], ...]], tuple[float, Any]] = {}
        if not self.api_key:
            raise ApiFootballError("API_FOOTBALL_KEY is not set")

    def _get(self, path: str, params: dict[str, Any] | None = None) -> Any:
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        key = (path, tuple(sorted(params.items())))
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and now - cached[0] < self.cache_seconds:
            return cached[1]

        resp = requests.get(
            f"{self.base_url}/{path.lstrip('/')}",
            params=params,
            headers={"x-apisports-key": self.api_key},
            timeout=20,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("errors"):
            raise ApiFootballError(str(data["errors"]))
        response = data.get("response", [])
        self._cache[key] = (now, response)
        return response

    def fixtures_for_date(
        self,
        match_date: str | None = None,
        league: int | None = None,
        season: int | None = None,
        timezone: str = "UTC",
    ) -> list[dict[str, Any]]:
        rows = self._get(
            "fixtures",
            {
                "date": match_date or date.today().isoformat(),
                "league": league,
                "season": season,
                "timezone": timezone,
            },
        )
        return [normalize_fixture(row) for row in rows]

    def fixture(self, fixture_id: int) -> dict[str, Any]:
        rows = self._get("fixtures", {"id": fixture_id})
        if not rows:
            raise ApiFootballError(f"Fixture not found: {fixture_id}")
        return normalize_fixture(rows[0])

    def events(self, fixture_id: int) -> list[dict[str, Any]]:
        rows = self._get("fixtures/events", {"fixture": fixture_id})
        return [normalize_event(row) for row in rows]

    def statistics(self, fixture_id: int) -> dict[str, dict[str, str]]:
        rows = self._get("fixtures/statistics", {"fixture": fixture_id})
        return normalize_statistics(rows)

    def lineups(self, fixture_id: int) -> list[dict[str, Any]]:
        rows = self._get("fixtures/lineups", {"fixture": fixture_id})
        return [normalize_lineup(row) for row in rows]

    def fixture_players(self, fixture_id: int) -> list[dict[str, Any]]:
        rows = self._get("fixtures/players", {"fixture": fixture_id})
        return [normalize_fixture_players(row) for row in rows]

    def standings(self, league_id: int, season: int) -> list[dict[str, Any]]:
        rows = self._get("standings", {"league": league_id, "season": season})
        return normalize_standings(rows)

    def live_match(self, fixture_id: int) -> dict[str, Any]:
        fixture = self.fixture(fixture_id)
        events = self.events(fixture_id)
        statistics = self.statistics(fixture_id)
        try:
            lineups = self.lineups(fixture_id)
        except Exception:
            lineups = []
        try:
            players = self.fixture_players(fixture_id)
        except Exception:
            players = []
        goal_scorers = summarize_goal_scorers(events, fixture)

        standings = None
        knockout_message = ""
        standings_error = ""
        league_id = fixture["league"]["id"]
        season = fixture["league"]["season"]
        round_name = fixture["league"]["round"]
        if league_id and season:
            try:
                if is_group_round(round_name):
                    standings = select_group_standings(
                        self.standings(int(league_id), int(season)),
                        round_name,
                        fixture["teams"]["home"]["id"],
                        fixture["teams"]["away"]["id"],
                    )
                else:
                    knockout_message = knockout_advance_message(round_name)
            except Exception as exc:
                standings = None
                standings_error = str(exc)

        return {
            "fixture": fixture,
            "events": events,
            "statistics": statistics,
            "lineups": lineups,
            "players": players,
            "goal_scorers": goal_scorers,
            "standings": standings,
            "knockout_message": knockout_message,
            "standings_error": standings_error,
            "updated_at": int(time.time()),
        }


def normalize_fixture(row: dict[str, Any]) -> dict[str, Any]:
    fixture = row.get("fixture") or {}
    status = fixture.get("status") or {}
    league = row.get("league") or {}
    teams = row.get("teams") or {}
    goals = row.get("goals") or {}
    venue = fixture.get("venue") or {}
    home = teams.get("home") or {}
    away = teams.get("away") or {}
    return {
        "id": fixture.get("id"),
        "date": fixture.get("date"),
        "timezone": fixture.get("timezone"),
        "venue": {
            "name": venue.get("name") or "",
            "city": venue.get("city") or "",
        },
        "status": {
            "long": status.get("long") or "",
            "short": status.get("short") or "",
            "elapsed": status.get("elapsed"),
        },
        "league": {
            "id": league.get("id"),
            "name": league.get("name") or "",
            "country": league.get("country") or "",
            "logo": league.get("logo") or "",
            "round": league.get("round") or "",
            "season": league.get("season"),
            "type": league.get("type") or "",
        },
        "teams": {
            "home": {
                "id": home.get("id"),
                "name": home.get("name") or "",
                "logo": home.get("logo") or "",
                "winner": home.get("winner"),
            },
            "away": {
                "id": away.get("id"),
                "name": away.get("name") or "",
                "logo": away.get("logo") or "",
                "winner": away.get("winner"),
            },
        },
        "goals": {
            "home": goals.get("home"),
            "away": goals.get("away"),
        },
    }


def normalize_event(row: dict[str, Any]) -> dict[str, Any]:
    time_data = row.get("time") or {}
    team = row.get("team") or {}
    player = row.get("player") or {}
    assist = row.get("assist") or {}
    return {
        "elapsed": time_data.get("elapsed"),
        "extra": time_data.get("extra"),
        "team": team.get("name") or "",
        "team_id": team.get("id"),
        "player": player.get("name") or "",
        "assist": assist.get("name") or "",
        "type": row.get("type") or "",
        "detail": row.get("detail") or "",
        "comments": row.get("comments") or "",
    }


def normalize_statistics(rows: list[dict[str, Any]]) -> dict[str, dict[str, str]]:
    wanted = {
        "Ball Possession": "possession",
        "Total Shots": "shots",
        "Shots on Goal": "shots_on_goal",
        "Corner Kicks": "corners",
        "Fouls": "fouls",
        "Yellow Cards": "yellow_cards",
        "Red Cards": "red_cards",
        "Offsides": "offsides",
        "Passes %": "pass_accuracy",
        "Pass Accuracy": "pass_accuracy",
        "Passes accurate": "passes_accurate",
    }
    result: dict[str, dict[str, str]] = {}
    for row in rows:
        team = (row.get("team") or {}).get("name") or ""
        stats: dict[str, str] = {}
        for entry in row.get("statistics") or []:
            label = wanted.get(entry.get("type"))
            if label:
                stats[label] = "" if entry.get("value") is None else str(entry.get("value"))
        if team:
            result[team] = stats
    return result


def normalize_lineup(row: dict[str, Any]) -> dict[str, Any]:
    team = row.get("team") or {}
    coach = row.get("coach") or {}
    start_xi = row.get("startXI") or []
    substitutes = row.get("substitutes") or []
    return {
        "team_id": team.get("id"),
        "team_name": team.get("name") or "",
        "formation": row.get("formation") or "",
        "coach": coach.get("name") or "",
        "start_xi": [
            {
                "id": (item.get("player") or {}).get("id"),
                "name": (item.get("player") or {}).get("name") or "",
                "number": (item.get("player") or {}).get("number"),
                "pos": (item.get("player") or {}).get("pos") or "",
                "grid": (item.get("player") or {}).get("grid") or "",
            }
            for item in start_xi
        ],
        "substitutes": [
            {
                "id": (item.get("player") or {}).get("id"),
                "name": (item.get("player") or {}).get("name") or "",
                "number": (item.get("player") or {}).get("number"),
                "pos": (item.get("player") or {}).get("pos") or "",
            }
            for item in substitutes
        ],
    }


def normalize_fixture_players(rows: dict[str, Any]) -> dict[str, Any]:
    team = rows.get("team") or {}
    players = []
    for item in rows.get("players") or []:
        player = item.get("player") or {}
        statistics = (item.get("statistics") or [{}])[0] or {}
        games = statistics.get("games") or {}
        shots = statistics.get("shots") or {}
        goals = statistics.get("goals") or {}
        cards = statistics.get("cards") or {}
        players.append(
            {
                "id": player.get("id"),
                "name": player.get("name") or "",
                "number": player.get("number"),
                "pos": player.get("pos") or games.get("position") or "",
                "minutes": games.get("minutes"),
                "rating": games.get("rating"),
                "captain": games.get("captain"),
                "shots_total": shots.get("total"),
                "shots_on": shots.get("on"),
                "goals_total": goals.get("total"),
                "assists": goals.get("assists"),
                "yellow": cards.get("yellow"),
                "red": cards.get("red"),
            }
        )
    return {
        "team_id": team.get("id"),
        "team_name": team.get("name") or "",
        "players": players,
    }


def normalize_standings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: list[dict[str, Any]] = []
    for row in rows:
        league = row.get("league") or {}
        for table in league.get("standings") or []:
            normalized_rows = []
            group_name = ""
            for item in table:
                group_name = extract_group_name(item, league) or group_name
                team = item.get("team") or {}
                all_stats = item.get("all") or {}
                normalized_rows.append(
                    {
                        "rank": item.get("rank"),
                        "team_id": team.get("id"),
                        "team_name": team.get("name") or "",
                        "team_logo": team.get("logo") or "",
                        "points": item.get("points"),
                        "goals_diff": item.get("goalsDiff"),
                        "played": all_stats.get("played"),
                        "win": all_stats.get("win"),
                        "draw": all_stats.get("draw"),
                        "lose": all_stats.get("lose"),
                    }
                )
            if normalized_rows:
                groups.append(
                    {
                        "group": group_name or "Standings",
                        "rows": normalized_rows,
                    }
                )
    return groups


def extract_group_name(item: dict[str, Any], league: dict[str, Any]) -> str:
    candidates = [
        item.get("group"),
        item.get("description"),
        item.get("stage"),
        league.get("round"),
        league.get("name"),
    ]
    for value in candidates:
        if not value:
            continue
        match = re.search(r"\bgroup\s+([a-z0-9]+)\b", str(value), re.IGNORECASE)
        if match:
            return f"Group {match.group(1).upper()}"
    for value in candidates:
        if value and str(value).strip():
            return str(value).strip()
    return ""


def is_group_round(round_name: str) -> bool:
    return bool(round_name and re.search(r"\bgroup\b", round_name, re.IGNORECASE))


def select_group_standings(
    groups: list[dict[str, Any]],
    round_name: str,
    home_team_id: int | None,
    away_team_id: int | None,
) -> dict[str, Any] | None:
    if not groups:
        return None

    target = simplify_group_name(round_name)
    if target and not is_generic_group_name(target):
        for group in groups:
            group_name = group.get("group", "")
            if is_generic_group_name(group_name):
                continue
            if simplify_group_name(group_name) == target:
                return {
                    "title": format_group_title(group_name),
                    "group": group_name,
                    "rows": group["rows"],
                }

    wanted_ids = {team_id for team_id in (home_team_id, away_team_id) if team_id}
    for group in groups:
        if is_generic_group_name(group.get("group", "")):
            continue
        member_ids = {row.get("team_id") for row in group["rows"]}
        if wanted_ids and wanted_ids.issubset(member_ids):
            return {
                "title": format_group_title(group["group"]),
                "group": group["group"],
                "rows": group["rows"],
            }

    if target:
        for group in groups:
            if simplify_group_name(group.get("group", "")) == target:
                return {
                    "title": format_group_title(group["group"]),
                    "group": group["group"],
                    "rows": group["rows"],
                }

    for group in groups:
        member_ids = {row.get("team_id") for row in group["rows"]}
        if wanted_ids and wanted_ids.issubset(member_ids):
            return {
                "title": format_group_title(group["group"]),
                "group": group["group"],
                "rows": group["rows"],
            }
    return None


def simplify_group_name(value: str) -> str:
    if not value:
        return ""
    match = re.search(r"group\s+([a-z0-9]+)", value, re.IGNORECASE)
    if match:
        return f"group {match.group(1).upper()}"
    return value.strip().lower()


def is_generic_group_name(value: str) -> bool:
    simplified = simplify_group_name(value)
    return simplified in {"group STAGE", "group stage", "stage"}


def format_group_title(group: str) -> str:
    match = re.search(r"group\s+([a-z0-9]+)", group, re.IGNORECASE)
    if match and match.group(1).lower() == "stage":
        return "Group Stage Table"
    if match:
        return f"Group {match.group(1).upper()} Table"
    return group or "Group Table"


def knockout_advance_message(round_name: str) -> str:
    name = (round_name or "").lower()
    if "round of 16" in name:
        return "Winner advances to Quarter-Final"
    if "quarter" in name:
        return "Winner advances to Semi-Final"
    if "semi" in name:
        return "Winner advances to Final"
    if "final" in name:
        return "Winner lifts the FIFA World Cup trophy"
    if "third" in name:
        return "Winner claims third place"
    return ""


def summarize_goal_scorers(events: list[dict[str, Any]], fixture: dict[str, Any]) -> dict[str, list[dict[str, str]]]:
    home_name = fixture["teams"]["home"]["name"]
    away_name = fixture["teams"]["away"]["name"]
    result = {"home": [], "away": []}
    for event in events:
        if (event.get("type") or "").lower() != "goal":
            continue
        detail = (event.get("detail") or "").lower()
        if "missed" in detail or "shootout" in detail:
            continue

        suffix = " (OG)" if "own goal" in detail else ""
        player = (event.get("player") or "Goal") + suffix
        minute = format_event_minute(event)
        item = {"player": player.strip(), "minute": minute}
        team_name = event.get("team") or ""
        if team_name == home_name:
            result["home"].append(item)
        elif team_name == away_name:
            result["away"].append(item)
    return result


def format_event_minute(event: dict[str, Any]) -> str:
    elapsed = event.get("elapsed")
    extra = event.get("extra")
    if elapsed is None:
        return ""
    minute = str(elapsed)
    if extra:
        minute = f"{minute}+{extra}"
    return f"{minute}'"
