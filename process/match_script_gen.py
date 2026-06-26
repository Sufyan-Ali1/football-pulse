"""Section-wise script generation for post-match videos."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from clients.groq_client import get_groq_client
from config import settings
from core.types import NewsItem, Script, VideoMetadata
from process.match_facts import MatchFacts

logger = logging.getLogger(__name__)

_SECTION_SPECS = [
    ("opening_hook", "Write an energetic opening hook for a YouTube match summary. Use exactly 2 complete sentences and target 70-85 words. Include preferred_score_phrase exactly once anywhere in the hook. Naturally weave hook_moments_for_narration into the narrative, including player names, without copying those phrases verbatim. Rephrase naturally while preserving all factual details. Avoid repeating the same player name unnecessarily within a sentence. Mention group_name or clean_sheet only if present. Create excitement and curiosity without bullet points, labels, headline-style writing, or information absent from the JSON."),
    ("match_result", "Set the match context and confirmed result in one sentence targeting 38-52 words. Include competition, round or group if available, teams, final score, winner or draw, and venue. Do not discuss points, qualification, table impact, tactics, or goal details."),
    ("first_half", "Summarize the first half in 35-70 words using only first-half goals, cards, penalties, and turning points."),
    ("second_half", "Summarize the second half in 35-70 words using only second-half goals, substitutions, cards, penalties, and turning points."),
    ("goals_recap", "Narrate every goal chronologically with minute, scorer, and assist if available."),
    ("turning_points", "Explain the listed deterministic turning points. If none are provided, return an empty string."),
    ("top_performers", "Discuss the player of the match and listed top players using only objective stats."),
    ("stats_analysis", "Explain the available team statistics and deterministic insights such as dominance and clinical finishing."),
    ("standings_impact", "Explain what the result means for the group/table or knockout round using only standings_summary or knockout_message. If unavailable, return an empty string."),
    ("closing", "Close with a short assessment. Do not invent next fixtures, quotes, or milestones."),
]

_SECTION_LABELS = {
    "opening_hook": "Opening Hook",
    "match_result": "Match Result",
    "first_half": "First Half",
    "second_half": "Second Half",
    "goals_recap": "Goals Recap",
    "turning_points": "Turning Points",
    "top_performers": "Top Performers",
    "stats_analysis": "Match Stats",
    "standings_impact": "Standings Impact",
    "closing": "Final Word",
}


def _debug_enabled() -> bool:
    return bool(getattr(settings, "POST_MATCH_VERBOSE_LOGS", False))


def _debug_dir(fixture_id: int | str) -> Path:
    base = Path(getattr(settings, "POST_MATCH_DEBUG_DIR", settings.TEMP_DIR / "post_match_debug")) / str(fixture_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _debug_slug(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    return safe[:120] or "artifact"


def _write_debug_artifact(fixture_id: int | str, name: str, payload) -> Path | None:
    if not _debug_enabled():
        return None
    path = _debug_dir(fixture_id) / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}_{_debug_slug(name)}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    logger.info("Post-match debug artifact saved: %s", path)
    return path


def _word_count(text: str) -> int:
    return len(text.split())


def _safe_float_local(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _sentence_count(text: str) -> int:
    return len(_sentence_parts(text))


def _sentence_parts(text: str) -> list[str]:
    stripped = text.strip()
    if not stripped:
        return []
    return [part.strip() for part in re.split(r"(?<=[.!?])\s+(?=[A-ZÀ-Ý])", stripped) if part.strip()]


def _estimate_duration(wc: int) -> int:
    return round(wc / 2.5)


def _section_temperature(section: str) -> float:
    return {
        "opening_hook": 0.25,
        "first_half": 0.2,
        "second_half": 0.2,
        "goals_recap": 0.0,
        "turning_points": 0.0,
        "top_performers": 0.1,
        "stats_analysis": 0.0,
        "standings_impact": 0.0,
        "closing": 0.25,
    }.get(section, 0.2)


def _section_max_tokens(section: str) -> int:
    if section == "match_result":
        return 100
    if section in {"first_half", "second_half"}:
        return 180
    if section == "goals_recap":
        return 180
    if section == "closing":
        return 80
    return 700


def _preferred_score_phrase(facts: MatchFacts) -> str:
    if facts.winner == "Draw":
        return f"{facts.home_team} and {facts.away_team} drew {facts.scoreline}"
    if facts.winner == facts.home_team:
        return f"{facts.home_team} beat {facts.away_team} {facts.home_goals}-{facts.away_goals}"
    if facts.winner == facts.away_team:
        return f"{facts.away_team} beat {facts.home_team} {facts.away_goals}-{facts.home_goals}"
    return f"{facts.home_team} vs {facts.away_team} finished {facts.scoreline}"


def _venue_short(facts: MatchFacts) -> str:
    return facts.venue.split(",")[0].strip() if facts.venue else ""


def _narrative_minute(event: dict[str, Any]) -> str:
    elapsed = event.get("elapsed")
    extra = event.get("extra")
    if not isinstance(elapsed, int):
        return str(event.get("minute") or "").strip()
    if extra:
        return f"first-half stoppage time" if elapsed <= 45 else f"{elapsed}+{extra} minutes"
    return f"{elapsed} minutes"


def _required_hook_moments(facts: MatchFacts) -> list[str]:
    moments: list[str] = []
    priority = {
        "opening_goal": 0,
        "winning_goal": 1,
        "game_killing_goal": 2,
        "first_half_stoppage_goal": 3,
        "late_goal": 4,
    }
    sorted_events = sorted(
        facts.important_events,
        key=lambda event: min(priority.get(tag, 99) for tag in (event.get("importance_tags") or [event.get("importance")])),
    )
    for event in sorted_events[:3]:
        player = event.get("player")
        minute = _narrative_minute(event)
        importance = str(event.get("importance") or "").replace("_", " ")
        if player and minute:
            moments.append(f"{player} {importance} at {minute}")
    if not moments:
        for goal in facts.goals[:2]:
            player = goal.get("player")
            minute = _narrative_minute(goal)
            if player and minute:
                moments.append(f"{player} goal at {minute}")
    return moments


def _hook_moments_for_narration(facts: MatchFacts) -> list[str]:
    moments: list[str] = []
    seen: set[tuple[str, str]] = set()
    priority = {
        "late_winner": 0,
        "comeback_goal": 1,
        "equalizer": 2,
        "red_card": 3,
        "winning_goal": 4,
        "opening_goal": 5,
        "first_half_stoppage_goal": 6,
        "game_killing_goal": 7,
    }
    sorted_events = sorted(
        facts.important_events,
        key=lambda event: min(priority.get(tag, 99) for tag in (event.get("importance_tags") or [event.get("importance")])),
    )
    for event in sorted_events:
        player = event.get("player")
        minute = _narrative_minute(event)
        if not player or not minute:
            continue
        key = (str(player), str(minute))
        if key in seen:
            continue
        seen.add(key)
        tags = set(event.get("importance_tags") or [event.get("importance")])
        if "opening_goal" in tags:
            moments.append(f"{player} opened the scoring after {minute}")
        elif "first_half_stoppage_goal" in tags:
            moments.append(f"{player} doubled the lead in first-half stoppage time")
        elif "game_killing_goal" in tags:
            moments.append(f"{player} sealed victory after {minute}")
        elif "winning_goal" in tags:
            moments.append(f"{player} scored the decisive goal after {minute}")
        elif "red_card" in tags:
            moments.append(f"{player} was sent off after {minute}")
        elif "late_goal" in tags:
            moments.append(f"{player} struck late after {minute}")
        if len(moments) >= 3:
            break
    return moments


def _human_label(value: str) -> str:
    return str(value or "").replace("_", " ").strip()


def _group_name(facts: MatchFacts) -> str | None:
    return (facts.standings_summary or {}).get("group") or None


def _winner_confirmation_phrase(facts: MatchFacts) -> str:
    if facts.winner == "Draw":
        return "with the match officially ending in a draw at full time"
    if facts.winner:
        return f"with {facts.winner} officially confirmed as the match winners at full time"
    return "with the result officially confirmed at full time"


def _closing_assessment_phrase(facts: MatchFacts) -> str:
    result_type = str(facts.match_result_type or "").strip()
    winner = str(facts.winner or "").strip()
    if winner == "Draw":
        return f"{facts.home_team} and {facts.away_team} finished on level terms"
    if result_type == "dominant_win" and winner:
        return f"{winner} completed a dominant performance"
    if result_type == "comeback" and winner:
        return f"{winner} completed the comeback"
    if result_type == "late_winner" and winner:
        return f"{winner} left it late to settle the match"
    if result_type == "narrow_win" and winner:
        return f"{winner} edged a tight contest"
    if winner:
        return f"{winner} closed out the result"
    return "The match finished with the result confirmed"


def _match_context_phrase(facts: MatchFacts) -> str:
    context_parts = [facts.competition]
    group_or_round = _group_name(facts) or facts.round_name
    if group_or_round:
        context_parts.append(group_or_round)
    context = " ".join(part for part in context_parts if part).strip()
    venue = _venue_short(facts) or facts.venue
    if context and venue:
        return f"{context} at {venue}"
    return context or venue or "the match"


def _first_half_score_phrase(facts: MatchFacts) -> str:
    home = int((facts.first_half_goals or {}).get("home") or 0)
    away = int((facts.first_half_goals or {}).get("away") or 0)
    if home > away:
        return f"{facts.home_team} led {facts.away_team} {home}-{away} at half time"
    if away > home:
        return f"{facts.away_team} led {facts.home_team} {away}-{home} at half time"
    return f"{facts.home_team} and {facts.away_team} were level {home}-{away} at half time"


def _first_half_events_for_narration(facts: MatchFacts) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for event in facts.goals + facts.important_events + facts.red_cards + facts.penalties:
        elapsed = event.get("elapsed")
        if not isinstance(elapsed, int) or elapsed > 45:
            continue
        minute = _narrative_minute(event)
        player = str(event.get("player") or "").strip()
        team = str(event.get("team") or "").strip()
        assist = str(event.get("assist") or "").strip()
        is_goal = str(event.get("type") or "").lower() == "goal"
        detail = "" if is_goal else str(event.get("detail") or event.get("type") or "").strip()
        key = (player, team, minute, detail)
        if key in seen:
            continue
        seen.add(key)
        if not player and not detail:
            continue
        phrase = ""
        if str(event.get("type") or "").lower() == "goal":
            if not events:
                phrase = f"{player} opened the scoring for {team} after {minute}"
            else:
                phrase = f"{player} doubled {team}'s lead in {minute}"
            if assist:
                phrase += f" from {assist}'s assist"
        else:
            phrase = f"{detail} involving {player} after {minute}".strip()
        events.append(
            {
                "minute": minute,
                "player": player,
                "team": team,
                "assist": assist,
                "detail": detail,
                "phrase": phrase,
            }
        )
    return events


def _first_half_word_bounds(event_count: int) -> tuple[int, int]:
    if event_count <= 1:
        return 20, 70
    if event_count == 2:
        return 30, 70
    return 40, 85


def _second_half_word_bounds(event_count: int) -> tuple[int, int]:
    if event_count <= 1:
        return 16, 70
    if event_count == 2:
        return 30, 70
    return 40, 85


def _event_fact_summary(events: list[dict[str, str]]) -> str:
    summaries = []
    for index, event in enumerate(events, start=1):
        parts = [f"event {index}"]
        for key in ("player", "team", "minute", "assist", "detail"):
            value = str(event.get(key) or "").strip()
            if value:
                parts.append(f"{key}: {value}")
        summaries.append(", ".join(parts))
    return "; ".join(summaries)


def _second_half_score_phrase(facts: MatchFacts) -> str:
    home = int((facts.second_half_goals or {}).get("home") or 0)
    away = int((facts.second_half_goals or {}).get("away") or 0)
    if home > away:
        return f"{facts.home_team} won the second half {home}-{away}"
    if away > home:
        return f"{facts.away_team} won the second half {away}-{home}"
    return f"{facts.home_team} and {facts.away_team} drew the second half {home}-{away}"


def _second_half_events_for_narration(facts: MatchFacts) -> list[dict[str, str]]:
    events: list[dict[str, str]] = []
    seen: set[tuple[str, str, str, str]] = set()
    for event in facts.goals + facts.important_events + facts.red_cards + facts.penalties:
        elapsed = event.get("elapsed")
        if isinstance(elapsed, int) and elapsed <= 45:
            continue
        minute = _narrative_minute(event)
        player = str(event.get("player") or "").strip()
        team = str(event.get("team") or "").strip()
        assist = str(event.get("assist") or "").strip()
        is_goal = str(event.get("type") or "").lower() == "goal"
        detail = "" if is_goal else str(event.get("detail") or event.get("type") or "").strip()
        key = (player, team, minute, detail)
        if key in seen:
            continue
        seen.add(key)
        if not player and not detail:
            continue
        events.append(
            {
                "minute": minute,
                "player": player,
                "team": team,
                "assist": assist,
                "detail": detail,
            }
        )
    return events


def _goals_for_narration(facts: MatchFacts) -> list[dict[str, str]]:
    goals: list[dict[str, str]] = []
    for goal in sorted(facts.goals, key=lambda item: (int(item.get("elapsed") or 0), int(item.get("extra") or 0))):
        detail = str(goal.get("detail") or "").strip()
        if detail.lower() == "normal goal":
            detail = ""
        goals.append(
            {
                "minute": _narrative_minute(goal),
                "player": str(goal.get("player") or "").strip(),
                "team": str(goal.get("team") or "").strip(),
                "assist": str(goal.get("assist") or "").strip(),
                "detail": detail,
            }
        )
    return goals


def _goals_recap_word_bounds(goal_count: int) -> tuple[int, int]:
    if goal_count <= 1:
        return 16, 42
    if goal_count == 2:
        return 28, 58
    return 30, 78


def _goals_recap_sentence_bounds(goal_count: int) -> tuple[int, int]:
    if goal_count <= 1:
        return 1, 1
    if goal_count <= 4:
        return 2, 2
    return 2, 3


def _top_performers_word_bounds(player_count: int) -> tuple[int, int]:
    if player_count <= 1:
        return 18, 45
    if player_count == 2:
        return 32, 72
    return 48, 110


def _top_performers_sentence_bounds(player_count: int) -> tuple[int, int]:
    count = max(1, min(player_count, 3))
    return count, count


def _performers_for_narration(facts: MatchFacts) -> list[dict[str, Any]]:
    performers: list[dict[str, Any]] = []
    player_of_match_name = str((facts.player_of_match or {}).get("name") or "").strip()
    for player in facts.top_players[:3]:
        performer = {
            "name": str(player.get("name") or "").strip(),
            "team": str(player.get("team") or "").strip(),
            "position": str(player.get("position") or "").strip(),
            "rating": str(player.get("rating") or "").strip(),
            "minutes": int(player.get("minutes") or 0),
            "goals": int(player.get("goals") or 0),
            "assists": int(player.get("assists") or 0),
            "shots_on": int(player.get("shots_on") or 0),
            "saves": int(player.get("saves") or 0),
            "key_passes": int(player.get("key_passes") or 0),
            "tackles": int(player.get("tackles") or 0),
            "interceptions": int(player.get("interceptions") or 0),
            "clean_sheet": bool(player.get("clean_sheet")),
            "yellow": int(player.get("yellow") or 0),
            "red": int(player.get("red") or 0),
            "is_player_of_match": str(player.get("name") or "").strip() == player_of_match_name,
        }
        performers.append(performer)
    return performers


def _primary_performer_metric(performer: dict[str, Any]) -> tuple[str, int | bool] | None:
    metric_order: list[tuple[str, int | bool]] = [
        ("goals", int(performer.get("goals") or 0)),
        ("assists", int(performer.get("assists") or 0)),
        ("saves", int(performer.get("saves") or 0)),
        ("shots_on", int(performer.get("shots_on") or 0)),
        ("key_passes", int(performer.get("key_passes") or 0)),
        ("tackles", int(performer.get("tackles") or 0)),
        ("interceptions", int(performer.get("interceptions") or 0)),
        ("clean_sheet", bool(performer.get("clean_sheet"))),
        ("minutes", int(performer.get("minutes") or 0)),
    ]
    for name, value in metric_order:
        if isinstance(value, bool):
            if value:
                return name, value
        elif value > 0:
            return name, value
    return None


def _stats_analysis_word_bounds(stat_count: int) -> tuple[int, int]:
    if stat_count <= 2:
        return 24, 70
    if stat_count <= 4:
        return 34, 95
    return 42, 115


def _stats_analysis_sentence_bounds(stat_count: int) -> tuple[int, int]:
    if stat_count <= 2:
        return 1, 2
    if stat_count <= 4:
        return 2, 3
    return 3, 4


def _stats_points_for_narration(
    statistics: dict[str, dict[str, str]],
    home_team: str,
    away_team: str,
) -> list[dict[str, str]]:
    points: list[dict[str, str]] = []
    for key in ("possession", "shots", "shots_on_goal", "pass_accuracy", "corners"):
        home_value = str((statistics.get(home_team) or {}).get(key) or "").strip()
        away_value = str((statistics.get(away_team) or {}).get(key) or "").strip()
        if not home_value and not away_value:
            continue
        if key == "shots_on_goal":
            label = "shots on target"
        elif key == "pass_accuracy":
            label = "pass accuracy"
        else:
            label = key.replace("_", " ")
        points.append(
            {
                "label": label,
                "home_team": home_team,
                "away_team": away_team,
                "home_value": home_value,
                "away_value": away_value,
            }
        )
    return points


def _stat_label_pattern(label: str) -> str:
    escaped = re.escape(label.lower())
    if label.lower() == "shots":
        return r"\bshots\b(?!\s+on\s+target)"
    return rf"\b{escaped}\b"


def _compact_facts_for_section(facts: MatchFacts, section: str) -> dict[str, Any]:
    base = {
        "competition": facts.competition,
        "competition_type": facts.competition_type,
        "round_name": facts.round_name,
        "home_team": facts.home_team,
        "away_team": facts.away_team,
        "final_score": facts.scoreline,
        "winner": facts.winner,
        "venue": facts.venue,
        "status": facts.status,
        "preferred_score_phrase": _preferred_score_phrase(facts),
        "match_result_type": _human_label(facts.match_result_type),
        "result_tags": [_human_label(tag) for tag in facts.result_tags],
    }
    if section == "opening_hook":
        return {
            "competition": facts.competition,
            "preferred_score_phrase": _preferred_score_phrase(facts),
            "match_result_type": _human_label(facts.match_result_type),
            "group_name": _group_name(facts),
            "clean_sheet": "clean sheet" in [_human_label(tag) for tag in facts.result_tags],
            "hook_moments_for_narration": _hook_moments_for_narration(facts),
            "venue_short": _venue_short(facts),
        }
    elif section == "match_result":
        return {
            "match_context_phrase": _match_context_phrase(facts),
            "preferred_score_phrase": _preferred_score_phrase(facts),
            "winner_confirmation_phrase": _winner_confirmation_phrase(facts),
        }
    elif section == "first_half":
        first_half_events = _first_half_events_for_narration(facts)
        min_words, max_words = _first_half_word_bounds(len(first_half_events))
        return {
            "first_half_score_phrase": _first_half_score_phrase(facts),
            "first_half_events_for_narration": first_half_events,
            "min_words": min_words,
            "max_words": max_words,
        }
    elif section == "second_half":
        second_half_events = _second_half_events_for_narration(facts)
        min_words, max_words = _second_half_word_bounds(len(second_half_events))
        return {
            "second_half_score_phrase": _second_half_score_phrase(facts),
            "second_half_events_for_narration": second_half_events,
            "min_words": min_words,
            "max_words": max_words,
        }
    elif section == "goals_recap":
        goals = _goals_for_narration(facts)
        min_words, max_words = _goals_recap_word_bounds(len(goals))
        return {
            "goals_for_narration": goals,
            "goal_count": len(goals),
            "min_words": min_words,
            "max_words": max_words,
            "sentence_count_min": _goals_recap_sentence_bounds(len(goals))[0],
            "sentence_count_max": _goals_recap_sentence_bounds(len(goals))[1],
        }
    elif section == "turning_points":
        base["turning_points"] = facts.important_events
        base["red_cards"] = facts.red_cards
        base["penalties"] = facts.penalties
    elif section == "top_performers":
        performers = _performers_for_narration(facts)
        min_words, max_words = _top_performers_word_bounds(len(performers))
        sentence_min, sentence_max = _top_performers_sentence_bounds(len(performers))
        return {
            "performers_for_narration": performers,
            "player_count": len(performers),
            "min_words": min_words,
            "max_words": max_words,
            "sentence_count_min": sentence_min,
            "sentence_count_max": sentence_max,
        }
    elif section == "stats_analysis":
        stat_points = _stats_points_for_narration(facts.statistics, facts.home_team, facts.away_team)
        min_words, max_words = _stats_analysis_word_bounds(len(stat_points))
        sentence_min, sentence_max = _stats_analysis_sentence_bounds(len(stat_points))
        return {
            "home_team": facts.home_team,
            "away_team": facts.away_team,
            "stat_points_for_narration": stat_points,
            "stats_insights": facts.stats_insights,
            "min_words": min_words,
            "max_words": max_words,
            "sentence_count_min": sentence_min,
            "sentence_count_max": sentence_max,
        }
    elif section == "standings_impact":
        base["standings_summary"] = facts.standings_summary
        base["knockout_message"] = facts.knockout_message
        base["standings_error"] = facts.standings_error
    elif section == "closing":
        potm = facts.player_of_match or {}
        base = {
            "home_team": facts.home_team,
            "away_team": facts.away_team,
            "closing_assessment_phrase": _closing_assessment_phrase(facts),
            "player_of_match_name": str(potm.get("name") or "").strip(),
            "player_of_match_team": str(potm.get("team") or "").strip(),
            "min_words": 10,
            "max_words": 24 if potm else 18,
            "sentence_count_min": 1,
            "sentence_count_max": 1,
        }
    else:
        base["goals"] = facts.goals
        base["turning_points"] = facts.important_events
        base["lineups_summary"] = facts.lineups_summary
    return base


def _section_prompt(section: str, instruction: str, payload: dict[str, Any]) -> str:
    if section == "opening_hook":
        return (
            "You are an elite football commentator writing the opening hook for a YouTube match summary video.\n"
            "Every factual statement must be directly supported by the JSON. Never invent facts, statistics, injuries, records, quotes, tactics, or future fixtures.\n"
            "Write a natural, dramatic hook, not a short headline and not a list.\n"
            "Your output is invalid if it is under 35 words.\n"
            "Requirements:\n"
            "- Exactly 2 complete sentences.\n"
            "- Target 70 to 85 words total; never return fewer than 60 words.\n"
            "- Sentence 1 must be 32 to 42 words and cover match context, venue, result, and match_result_type.\n"
            "- Sentence 2 must be 32 to 42 words and cover the goal narrative and clean_sheet if present.\n"
            "- Include preferred_score_phrase exactly once anywhere in the hook.\n"
            "- Naturally weave all hook_moments_for_narration into the narrative when there are 3 or fewer, including player names.\n"
            "- Do not copy hook_moments_for_narration verbatim; rephrase naturally while preserving factual details.\n"
            "- Avoid repeating the same player name unnecessarily within a sentence.\n"
            "- Mention group_name or clean_sheet only if present in the JSON.\n"
            "- Do not use label-style phrases like 'key moments:' or bullet points.\n\n"
            "Example style only, do not copy facts from this example:\n"
            "{\"text\":\"A commanding night at Stadium One saw Team A beat Team B 3-0 in a dominant cup display that quickly became one-sided. Player One struck early and added another before halftime, then Player Two sealed the clean sheet with a decisive second-half finish.\"}\n\n"
            f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Return valid JSON only: {\"text\":\"...\"}"
        )
    if section == "match_result":
        return (
            "You are a precise football commentator writing the match result section of a post-match YouTube script.\n"
            "Every factual statement must be directly supported by the JSON. Never invent points, qualification impact, standings impact, tactics, quotes, injuries, records, goal details, or future fixtures.\n"
            "This section sets context only; deeper story and table impact are handled later.\n"
            "Requirements:\n"
            "- Exactly 1 complete sentence.\n"
            "- Length: 28 to 40 words.\n"
            "- The sentence MUST begin exactly with: \"In {match_context_phrase},\"\n"
            "- Include preferred_score_phrase exactly once.\n"
            "- Include winner_confirmation_phrase exactly once.\n"
            "- Introduce the competition context naturally.\n"
            "- Do not say 'all three points', 'top of the group', 'qualified', 'eliminated', or any table-impact claim.\n"
            "- Do not mention scorers, assists, tactics, or statistics.\n\n"
            "- End the sentence with a period.\n\n"
            f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Return valid JSON only: {\"text\":\"...\"}"
        )
    if section == "first_half":
        return (
            "You are a football commentator writing the first-half story for a post-match YouTube script.\n"
            "Every factual statement must be directly supported by the JSON. Never introduce events, players, statistics, or details not present in the JSON.\n"
            "Requirements:\n"
            "- Exactly 2 complete sentences.\n"
            "- Length: min_words to max_words from the JSON.\n"
            "- Sentence 1 must include first_half_score_phrase exactly once.\n"
            "- Sentence 2 must cover every event in first_half_events_for_narration exactly once.\n"
            "- Sentence 2 must narrate events in chronological order.\n"
            "- Preserve all player names, assist names, and special minute wording exactly as provided.\n"
            "- Do not convert first-half stoppage time into '45th minute'.\n"
            "- Do not add subjective descriptions or qualitative assessments unless explicitly present in the JSON.\n"
            "- Do not add filler phrases that do not introduce factual information.\n"
            "- Avoid unnecessary repetition of player names while preserving factual accuracy.\n"
            "- Keep the tone energetic, factual, and suitable for spoken football commentary.\n\n"
            "- End the final sentence with a period.\n\n"
            f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Return valid JSON only: {\"text\":\"...\"}"
        )
    if section == "second_half":
        return (
            "You are a football commentator writing the second-half story for a post-match YouTube script.\n"
            "Every factual statement must be directly supported by the JSON. Never introduce events, players, statistics, tactics, injuries, quotes, or details not present in the JSON.\n"
            "Requirements:\n"
            "- Exactly 2 complete sentences.\n"
            "- Length: min_words to max_words from the JSON.\n"
            "- Sentence 1 must include second_half_score_phrase exactly once.\n"
            "- Sentence 2 must mention every event in second_half_events_for_narration exactly once and no additional events.\n"
            "- Sentence 2 must narrate events in chronological order.\n"
            "- Preserve all player names, assist names, and special minute wording exactly as provided.\n"
            "- Rephrase naturally while preserving every factual detail from each event.\n"
            "- Do not add subjective descriptions, table impact, or qualitative assessments unless explicitly present in the JSON.\n"
            "- Do not add filler phrases that do not introduce factual information.\n"
            "- Repeat player names whenever necessary to preserve factual accuracy.\n"
            "- Keep the tone factual and suitable for spoken football commentary.\n\n"
            "- End the final sentence with a period.\n\n"
            f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Return valid JSON only: {\"text\":\"...\"}"
        )
    if section == "goals_recap":
        return (
            "You are a football commentator writing the goals recap section for a post-match YouTube script.\n"
            "Every factual statement must be directly supported by the JSON. Never introduce events, players, statistics, tactics, injuries, quotes, table impact, or details not present in the JSON.\n"
            "This section only recaps the goals; do not restate the final score or match result.\n"
            "Requirements:\n"
            "- Use sentence_count_min to sentence_count_max complete sentences from the JSON.\n"
            "- Length: min_words to max_words from the JSON.\n"
            "- Mention every goal in goals_for_narration exactly once and no additional goals or events.\n"
            "- The order of narration must exactly match the order of goals_for_narration in the JSON.\n"
            "- Each goal must be explicitly narrated with scorer, minute, team, and assist if provided. Multiple goals may appear in the same sentence if the JSON order is preserved.\n"
            "- For normal goals, use 'scored for {team}' instead of vague phrases like 'added a goal'.\n"
            "- Narrate every goal as an independent scoring event; do not summarize multiple goals by the same player into a single achievement.\n"
            "- Preserve all player names, team names, assist names, and special minute wording exactly as provided.\n"
            "- Mention an assist only when an assist name exists in the JSON.\n"
            "- If detail contains a special goal type such as Penalty or Own Goal, mention it naturally.\n"
            "- Rephrase naturally while preserving every factual detail from each goal.\n"
            "- Repeat player names whenever necessary to preserve factual clarity.\n"
            "- For numeric minute wording like '7 minutes', say 'after 7 minutes' or 'at 7 minutes'; never say 'in the 7 minutes'.\n"
            "- Do not say '45+3 minute', '45+3\\' minute', or '45th minute' when the JSON says first-half stoppage time.\n"
            "- Do not mention the running score or final score at any point.\n"
            "- Do not add filler intros such as 'let's take a look' or subjective phrases such as 'final nail in the coffin'.\n"
            "- Keep the tone factual and suitable for spoken football commentary.\n\n"
            "- End the final sentence with a period.\n\n"
            f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Return valid JSON only: {\"text\":\"...\"}"
        )
    if section == "top_performers":
        return (
            "You are a football commentator writing the top performers section for a post-match YouTube script.\n"
            "Every factual statement must be directly supported by the JSON. Never introduce tactics, quotes, injuries, table impact, records, future fixtures, or any stats not present in the JSON.\n"
            "This section only describes the listed performers using objective metrics.\n"
            "Requirements:\n"
            "- Use sentence_count_min to sentence_count_max complete sentences from the JSON.\n"
            "- Length: min_words to max_words from the JSON.\n"
            "- Mention performers_for_narration in the exact order shown in the JSON.\n"
            "- Every performer in performers_for_narration must be mentioned exactly once and no performer may be omitted.\n"
            "- Each performer must receive exactly one sentence.\n"
            "- Each sentence must include the performer's name and team.\n"
            "- Mention the rating only when it is present and greater than zero.\n"
            "- Each sentence must include at least one non-zero statistic when one exists in the JSON.\n"
            "- When goals or assists are non-zero, they must be mentioned.\n"
            "- If neither goals nor assists are available, mention the first available non-zero metric in this order: saves, shots_on, key_passes, tackles, interceptions, clean_sheet, minutes.\n"
            "- If no non-zero statistics exist for a performer, mention only the player's name, team, and rating if available.\n"
            "- Mention only non-zero statistics from the JSON.\n"
            "- Do not mention ratings that are empty, missing, null, or equal to zero.\n"
            "- The sentence describing the performer whose is_player_of_match value is true MUST contain the exact phrase 'player of the match' exactly once.\n"
            "- No other sentence may contain that phrase.\n"
            "- Preserve all player names and team names exactly as provided.\n"
            "- Vary sentence structure naturally while preserving factual accuracy.\n"
            "- Never infer or calculate statistics from the provided data.\n"
            "- Do not infer dominance, influence, importance, or overall performance quality from statistics.\n"
            "- Do not use subjective verbs such as impressed, starred, shined, excelled, dominated, inspired, or led.\n"
            "- Keep the wording factual; do not use filler praise such as 'what a performance', 'solid game', or 'standout' unless directly supported by the stats.\n"
            "- End the final sentence with a period.\n\n"
            f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Return valid JSON only: {\"text\":\"...\"}"
        )
    if section == "stats_analysis":
        return (
            "You are a football commentator writing the match statistics analysis section for a post-match YouTube script.\n"
            "Every factual statement must be directly supported by the JSON. Never introduce tactics, quotes, injuries, table impact, records, future fixtures, or any statistics not present in the JSON.\n"
            "This section explains the listed team statistics and deterministic insight flags only.\n"
            "Requirements:\n"
            "- Use sentence_count_min to sentence_count_max complete sentences from the JSON.\n"
            "- Multiple stat points may appear in the same sentence provided the JSON order is preserved.\n"
            "- Length: min_words to max_words from the JSON.\n"
            "- The order of narration must exactly match stat_points_for_narration in the JSON.\n"
            "- The total number of narrated statistic points must equal the number of elements in stat_points_for_narration.\n"
            "- Every stat point in stat_points_for_narration must be explicitly narrated exactly once and no stat point may be omitted or repeated.\n"
            "- Every narrated stat point must explicitly include its statistic label using the wording from the JSON.\n"
            "- Every narrated stat point must explicitly mention both teams and both statistic values exactly as provided in the JSON.\n"
            "- When multiple statistics are combined in one sentence, they must appear in the same left-to-right order as in stat_points_for_narration.\n"
            "- Preserve all team names, statistic labels, and statistic values exactly as provided.\n"
            "- Team names must be explicitly stated for every statistic point.\n"
            "- Do not replace team names with pronouns or shorthand such as they, the teams, both sides, or respectively.\n"
            "- Do not mention the final score, running score, goalscorers, or match result.\n"
            "- Never calculate or infer differences, totals, averages, margins, percentages, efficiency, or any derived statistic.\n"
            "- Do not use comparative or evaluative terms such as edged, comfortably, narrowly, superior, inferior, better, worse, or dominant unless explicitly allowed by stats_insights below.\n"
            "- Each insight from stats_insights may be mentioned at most once.\n"
            "- If stats_insights.dominant_team is not 'Level', the exact phrase 'dominant team' MUST appear exactly once and only as a standalone factual statement referring to that team.\n"
            "- If stats_insights.clinical_team is not 'Level', the exact phrase 'more clinical team' MUST appear exactly once and only as a standalone factual statement referring to that team.\n"
            "- Any stats_insights statement must appear only after all statistic points have been narrated.\n"
            "- Do not describe a team as leading a statistic unless explicitly supported by stats_insights.\n"
            "- Use grammatically correct singular and plural forms for all statistics.\n"
            "- Do not infer any other meaning beyond the provided stat points and stats_insights.\n"
            "- Keep the wording factual and do not use filler or subjective descriptions.\n"
            "- End the final sentence with a period.\n\n"
            f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Return valid JSON only: {\"text\":\"...\"}"
        )
    if section == "closing":
        return (
            "You are a football commentator writing the closing line of a post-match YouTube script.\n"
            "Every factual statement must be directly supported by the JSON. Never introduce standings impact, next fixtures, quotes, records, milestones, tactics, venue references, or any statistics not present in the JSON.\n"
            "This section should end the video briefly without repeating the scoreline or earlier analysis.\n"
            "Requirements:\n"
            "- Use sentence_count_min to sentence_count_max complete sentences from the JSON.\n"
            "- Length: min_words to max_words from the JSON.\n"
            "- Include the exact text from closing_assessment_phrase exactly once without rephrasing.\n"
            "- Treat closing_assessment_phrase as factual input from the JSON.\n"
            "- If player_of_match_name is present, mention player_of_match_name exactly once, mention player_of_match_team exactly once, and include the exact phrase 'player of the match' exactly once.\n"
            "- If player_of_match_name is empty, null, or missing, do not use the phrase 'player of the match'.\n"
            "- Do not mention player_of_match_name more than once.\n"
            "- Do not mention the final score, winning margin, venue, group, table, qualification, next fixture, or future outlook.\n"
            "- Do not repeat earlier match analysis or statistics.\n"
            "- Do not use filler phrases such as that's a wrap, full stop here, or what a night.\n"
            "- Keep the wording concise, factual, and suitable as a spoken final line.\n"
            "- End the sentence with a period.\n\n"
            f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "Return valid JSON only: {\"text\":\"...\"}"
        )
    return (
        "You are a football commentator writing one section of a post-match YouTube script.\n"
        "Every factual statement in the output must be directly supported by the JSON. "
        "Never infer, speculate, or introduce injuries, transfers, records, milestones, "
        "next fixtures, quotes, tactics, names, or statistics not explicitly present.\n"
        "If the facts are insufficient for this section, return an empty string.\n"
        "Keep wording natural and energetic, but factual.\n\n"
        f"Section: {section}\n"
        f"Instruction: {instruction}\n"
        f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return valid JSON only: {\"text\": \"...\"}"
    )


def _should_skip_section(facts: MatchFacts, section: str) -> bool:
    if section == "turning_points":
        return not facts.important_events and not facts.red_cards and not facts.penalties
    if section == "top_performers":
        return not facts.top_players
    if section == "stats_analysis":
        return not facts.statistics
    if section == "standings_impact":
        return not facts.standings_summary and not facts.knockout_message
    if section == "goals_recap":
        return not facts.goals
    return False


def _generate_section(section: str, instruction: str, facts: MatchFacts) -> str:
    payload = _compact_facts_for_section(facts, section)
    temperature = _section_temperature(section)
    max_tokens = _section_max_tokens(section)
    prompt = _section_prompt(section, instruction, payload)
    messages = [{"role": "user", "content": prompt}]
    _write_debug_artifact(
        facts.fixture_id,
        f"llm_{section}_request",
        {
            "section": section,
            "model": settings.GROQ_MODEL,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "messages": messages,
            "facts_payload": payload,
        },
    )
    groq_client = get_groq_client()
    max_attempts = 6 if section == "opening_hook" else 4 if section in {"match_result", "first_half", "second_half", "goals_recap", "top_performers", "stats_analysis", "closing"} else 1
    response = None
    raw_content = ""
    text = ""
    validation_error = ""
    current_prompt = prompt
    for attempt in range(1, max_attempts + 1):
        response = groq_client.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": current_prompt}],
            max_tokens=max_tokens,
            temperature=min(temperature, 0.2) if attempt > 1 else temperature,
            response_format={"type": "json_object"},
        )
        raw_content = response.choices[0].message.content
        data = json.loads(raw_content)
        text = str(data.get("text") or "").strip()
        validation_error = _section_validation_error(section, text, payload)
        if not validation_error:
            break
        _write_debug_artifact(
            facts.fixture_id,
            f"llm_{section}_invalid_response_attempt_{attempt}",
            {
                "section": section,
                "attempt": attempt,
                "model": settings.GROQ_MODEL,
                "raw_content": raw_content,
                "text": text,
                "validation_error": validation_error,
                "usage": getattr(response, "usage", None),
            },
        )
        current_prompt = _retry_prompt_for_section(prompt, section, payload, text, validation_error)

    _write_debug_artifact(
        facts.fixture_id,
        f"llm_{section}_response",
        {
            "section": section,
            "model": settings.GROQ_MODEL,
            "raw_content": raw_content,
            "usage": getattr(response, "usage", None),
        },
    )
    if validation_error:
        logger.warning("Match script section invalid after LLM retries (%s): %s", section, validation_error)
        if section in {"opening_hook", "match_result", "first_half", "second_half", "goals_recap", "top_performers", "stats_analysis", "closing"}:
            raise ValueError(validation_error)
    return text


def _retry_prompt_for_section(base_prompt: str, section: str, payload: dict[str, Any], previous_text: str, validation_error: str) -> str:
    if section == "stats_analysis":
        stat_facts = _event_fact_summary(payload.get("stat_points_for_narration", []))
        return (
            "You are repairing the match statistics analysis section of a football post-match YouTube script.\n"
            "Use only the JSON facts. Do not infer tactics, chances, quotes, injuries, records, or match result.\n\n"
            f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "The previous JSON text failed validation and cannot be used.\n"
            f"Validation error: {validation_error}\n"
            f"Previous text: {previous_text}\n\n"
            "Hard requirements:\n"
            f"- {payload.get('sentence_count_min') or 1} to {payload.get('sentence_count_max') or 4} complete sentences\n"
            "- multiple stat points may appear in the same sentence if JSON order is preserved\n"
            f"- {payload.get('min_words') or 24} to {payload.get('max_words') or 115} words\n"
            f"- mention every stat point exactly once in this order: {stat_facts}\n"
            "- the total number of narrated statistic points must equal the number of stat_points_for_narration entries\n"
            "- every stat point must explicitly include its statistic label using the JSON wording\n"
            "- every stat point must explicitly mention both teams and both values exactly as provided\n"
            "- when multiple statistics share a sentence, keep the same left-to-right JSON order\n"
            "- preserve team names, statistic labels, and statistic values exactly\n"
            "- team names must be stated for every stat point\n"
            "- do not use they, the teams, both sides, respectively, or other shorthand instead of team names\n"
            "- do not mention final score, running score, goalscorers, or match result\n"
            "- never calculate or infer differences, totals, margins, averages, or any derived statistic\n"
            "- do not use edged, comfortably, narrowly, superior, inferior, better, worse, or other evaluative comparison words\n"
            "- each insight from stats_insights may be mentioned at most once\n"
            "- if dominant_team is not Level, the exact phrase dominant team must appear exactly once and only as a standalone factual statement for that team\n"
            "- if clinical_team is not Level, the exact phrase more clinical team must appear exactly once and only as a standalone factual statement for that team\n"
            "- any stats_insights statement must appear only after all statistic points have been narrated\n"
            "- do not describe a team as leading a statistic unless explicitly supported by stats_insights\n"
            "- use grammatically correct singular and plural forms for all statistics\n"
            "- do not infer any other meaning beyond the provided stat points and stats_insights\n"
            "- no filler, no subjective descriptions, no tactics\n"
            "- end the final sentence with a period\n"
            "- return valid JSON only: {\"text\":\"...\"}"
        )
    if section == "closing":
        return (
            "You are repairing the closing line of a football post-match YouTube script.\n"
            "Use only the JSON facts. Do not invent standings impact, future fixtures, venue details, score repetition, or any extra commentary.\n\n"
            f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "The previous JSON text failed validation and cannot be used.\n"
            f"Validation error: {validation_error}\n"
            f"Previous text: {previous_text}\n\n"
            "Hard requirements:\n"
            f"- {payload.get('sentence_count_min') or 1} complete sentence\n"
            f"- {payload.get('min_words') or 14} to {payload.get('max_words') or 28} words\n"
            f"- include this exact phrase once without rephrasing: {payload.get('closing_assessment_phrase') or ''}\n"
            "- treat closing_assessment_phrase as factual input from the JSON\n"
            "- if player_of_match_name is present, include player_of_match_name exactly once, player_of_match_team exactly once, and the exact phrase player of the match exactly once\n"
            "- if player_of_match_name is absent, do not use the phrase player of the match\n"
            "- do not mention player_of_match_name more than once\n"
            "- do not mention score, venue, group, table, qualification, next fixture, or future outlook\n"
            "- do not repeat earlier match analysis or statistics\n"
            "- do not use filler phrases such as that's a wrap, full stop here, or what a night\n"
            "- end the sentence with a period\n"
            "- return valid JSON only: {\"text\":\"...\"}"
        )
    if section == "top_performers":
        performer_facts = _event_fact_summary(payload.get("performers_for_narration", []))
        return (
            "You are repairing the top performers section of a football post-match YouTube script.\n"
            "Use only the JSON facts. Do not infer tactics, dominance, quotes, injuries, or table impact.\n\n"
            f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "The previous JSON text failed validation and cannot be used.\n"
            f"Validation error: {validation_error}\n"
            f"Previous text: {previous_text}\n\n"
            "Hard requirements:\n"
            f"- {payload.get('sentence_count_min') or 1} to {payload.get('sentence_count_max') or 3} complete sentences\n"
            f"- {payload.get('min_words') or 18} to {payload.get('max_words') or 110} words\n"
            f"- mention performers in this exact order: {performer_facts}\n"
            "- every performer must be mentioned exactly once and no performer may be omitted\n"
            "- each performer must receive exactly one sentence\n"
            "- each sentence must include name and team\n"
            "- mention the rating only when it is present and greater than zero\n"
            "- each sentence must include at least one non-zero statistic when one exists in the JSON\n"
            "- when goals or assists are non-zero, they must be mentioned\n"
            "- if neither goals nor assists are available, mention the first available non-zero metric in this order: saves, shots_on, key_passes, tackles, interceptions, clean_sheet, minutes\n"
            "- if no non-zero statistics exist for a performer, mention only the player's name, team, and rating if available\n"
            "- mention only non-zero stats from the JSON\n"
            "- do not mention ratings that are empty, missing, null, or equal to zero\n"
            "- the sentence describing the performer whose is_player_of_match value is true must contain the exact phrase 'player of the match' exactly once\n"
            "- no other sentence may contain that phrase\n"
            "- preserve player names and team names exactly\n"
            "- vary sentence structure naturally while preserving factual accuracy\n"
            "- never infer or calculate statistics from the provided data\n"
            "- do not infer dominance, influence, importance, or overall performance quality from statistics\n"
            "- do not use subjective verbs such as impressed, starred, shined, excelled, dominated, inspired, or led\n"
            "- no filler praise like 'what a performance', 'solid game', or 'standout'\n"
            "- use spoken football commentary style, but stay factual\n"
            "- end the final sentence with a period\n"
            "- return valid JSON only: {\"text\":\"...\"}"
        )
    if section == "goals_recap":
        goal_facts = _event_fact_summary(payload.get("goals_for_narration", []))
        return (
            "You are repairing the goals recap section of a football post-match YouTube script.\n"
            "Use only the JSON facts. Do not infer match result, table impact, tactics, chances, pressure, injuries, or statistics.\n\n"
            f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "The previous JSON text failed validation and cannot be used.\n"
            f"Validation error: {validation_error}\n"
            f"Previous text: {previous_text}\n\n"
            "Hard requirements:\n"
            f"- {payload.get('sentence_count_min') or 1} to {payload.get('sentence_count_max') or 3} complete sentences\n"
            f"- {payload.get('min_words') or 30} to {payload.get('max_words') or 75} words\n"
            f"- mention every goal exactly once and no additional goals or events in this exact order: {goal_facts}\n"
            "- each goal must be explicitly narrated with scorer, minute, team, and assist if provided; multiple goals may appear in the same sentence if order is preserved\n"
            "- for normal goals, use 'scored for {team}' instead of vague phrases like 'added a goal'\n"
            "- narrate every goal as an independent scoring event; do not summarize multiple goals by the same player into a single achievement\n"
            "- preserve all listed player names, team names, assist names, and special minute wording exactly\n"
            "- mention an assist only when an assist name exists in the JSON\n"
            "- mention special goal detail only when detail is present in the JSON\n"
            "- repeat player names whenever necessary to preserve factual clarity\n"
            "- for numeric minute wording like '7 minutes', say 'after 7 minutes' or 'at 7 minutes'; never say 'in the 7 minutes'\n"
            "- do not mention the running score, final score, or match result\n"
            "- do not say '45+3 minute', \"45+3' minute\", or '45th minute' for first-half stoppage time\n"
            "- no filler intro, no subjective phrases, no table impact\n"
            "- use spoken football commentary style, but stay factual\n"
            "- end the final sentence with a period\n"
            "- return valid JSON only: {\"text\":\"...\"}"
        )
    if section == "second_half":
        event_facts = _event_fact_summary(payload.get("second_half_events_for_narration", []))
        return (
            "You are repairing the second-half story section of a football post-match YouTube script.\n"
            "Use only the JSON facts. Do not infer table impact, possession, pressure, chances, tactics, injuries, or statistics.\n\n"
            f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "The previous JSON text failed validation and cannot be used.\n"
            f"Validation error: {validation_error}\n"
            f"Previous text: {previous_text}\n\n"
            "Hard requirements:\n"
            "- exactly 2 complete sentences\n"
            f"- {payload.get('min_words') or 30} to {payload.get('max_words') or 70} words\n"
            f"- sentence 1 must include this exact phrase once: {payload.get('second_half_score_phrase') or ''}\n"
            f"- sentence 2 must mention every event exactly once and no additional events, in chronological order: {event_facts}\n"
            "- preserve all listed player names, assist names, and special minute wording exactly\n"
            "- rephrase naturally while preserving every factual detail from each event\n"
            "- do not add subjective descriptions, table impact, or filler phrases\n"
            "- repeat player names whenever necessary to preserve factual accuracy\n"
            "- use spoken football commentary style, but stay factual\n"
            "- end the final sentence with a period\n"
            "- return valid JSON only: {\"text\":\"...\"}"
        )
    if section == "first_half":
        event_phrases = "; ".join(event.get("phrase", "") for event in payload.get("first_half_events_for_narration", []))
        return (
            "You are repairing the first-half story section of a football post-match YouTube script.\n"
            "Use only the JSON facts. Do not infer possession, pressure, chances, tactics, injuries, or statistics.\n\n"
            f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "The previous JSON text failed validation and cannot be used.\n"
            f"Validation error: {validation_error}\n"
            f"Previous text: {previous_text}\n\n"
            "Hard requirements:\n"
            "- exactly 2 complete sentences\n"
            f"- {payload.get('min_words') or 30} to {payload.get('max_words') or 70} words\n"
            f"- sentence 1 must include this exact phrase once: {payload.get('first_half_score_phrase') or ''}\n"
            f"- sentence 2 must cover every event exactly once, in chronological order: {event_phrases}\n"
            "- preserve all listed player names, assist names, and special minute wording exactly\n"
            "- do not say '45th minute' for first-half stoppage time\n"
            "- do not add subjective descriptions, qualitative assessments, or filler phrases\n"
            "- avoid unnecessary repetition of player names while preserving factual accuracy\n"
            "- use spoken football commentary style, but stay factual\n"
            "- end the final sentence with a period\n"
            "- return valid JSON only: {\"text\":\"...\"}"
        )
    if section == "match_result":
        return (
            "You are repairing the match result section of a football post-match YouTube script.\n"
            "Use only the JSON facts. Do not infer table impact, points, qualification, tactics, scorers, or statistics.\n\n"
            f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
            "The previous JSON text failed validation and cannot be used.\n"
            f"Validation error: {validation_error}\n"
            f"Previous text: {previous_text}\n\n"
        "Hard requirements:\n"
        "- exactly 1 complete sentence\n"
        "- 28 to 40 words\n"
        f"- the sentence MUST begin exactly with: \"In {payload.get('match_context_phrase') or ''},\"\n"
        f"- include this exact phrase once: {payload.get('preferred_score_phrase') or ''}\n"
        f"- include this exact phrase once: {payload.get('winner_confirmation_phrase') or ''}\n"
        "- no points, standings impact, qualification, scorers, assists, tactics, or statistics\n"
        "- end with a period\n"
        "- return valid JSON only: {\"text\":\"...\"}"
        )
    if section != "opening_hook":
        return (
            f"{base_prompt}\n\n"
            "Your previous JSON text failed validation.\n"
            f"Validation error: {validation_error}\n"
            "Rewrite it and return valid JSON only."
        )
    preferred_score_phrase = payload.get("preferred_score_phrase") or ""
    narration_moments = payload.get("hook_moments_for_narration") or []
    decisive_text = "; ".join(narration_moments[:3])
    venue_short = payload.get("venue_short") or payload.get("venue") or ""
    competition = payload.get("competition") or "match"
    group_name = payload.get("group_name") or ""
    clean_sheet = "clean sheet" if payload.get("clean_sheet") else ""
    player_names = ", ".join(
        dict.fromkeys(
            moment.split(" ", 2)[0] + (" " + moment.split(" ", 2)[1] if len(moment.split(" ", 2)) > 1 else "")
            for moment in narration_moments[:3]
        )
    )
    return (
        "You are repairing an opening hook for a YouTube football match summary.\n"
        "Use only the facts in the JSON. Do not invent or infer anything.\n\n"
        f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "The previous JSON text failed validation and cannot be used.\n"
        f"Validation error: {validation_error}\n"
        f"Previous text: {previous_text}\n\n"
        "Rewrite the hook naturally from the JSON facts. Do not list events mechanically.\n\n"
        "Hard requirements:\n"
        "- exactly 2 complete sentences\n"
        "- target 70 to 85 words total; never return fewer than 60 words\n"
        "- sentence 1 must be 32 to 42 words and cover match context, venue, result, and match_result_type\n"
        "- sentence 2 must be 32 to 42 words and cover the goal narrative and clean_sheet if present\n"
        f"- include this exact phrase once: {preferred_score_phrase}\n"
        f"- include these details if available: {competition}, {venue_short}, {group_name}, {clean_sheet}\n"
        f"- naturally weave all of these hook moments into the narrative without copying them verbatim: {decisive_text}\n"
        f"- include these player names if provided: {player_names}\n"
        "- avoid repeating the same player name unnecessarily within a sentence\n"
        "- no comma-only headline, no fragments, no bullet points, no label-style phrasing like 'key moments:'\n"
        "- return valid JSON only: {\"text\":\"...\"}"
    )


def _section_validation_error(section: str, text: str, payload: dict[str, Any]) -> str:
    if not text:
        return ""
    if section == "closing":
        wc = _word_count(text)
        min_words = int(payload.get("min_words") or 14)
        max_words = int(payload.get("max_words") or 28)
        if wc < min_words or wc > max_words:
            return f"closing must be {min_words}-{max_words} words, got {wc}"
        sentences = _sentence_count(text)
        sentence_min = int(payload.get("sentence_count_min") or 1)
        sentence_max = int(payload.get("sentence_count_max") or 1)
        if sentences < sentence_min or sentences > sentence_max:
            return f"closing must be {sentence_min}-{sentence_max} sentences, got {sentences}"
        if not re.search(r"[.!?]$", text):
            return "closing must end with sentence punctuation"
        lowered = text.lower()
        banned = [
            "that's a wrap",
            "thats a wrap",
            "what a night",
            "full stop here",
            "next",
            "up next",
            "fixture",
            "stadium",
            "group",
            "table",
            "qualification",
            "qualify",
            "qualified",
            "top of",
            "0-",
            "1-",
            "2-",
            "3-",
            "4-",
            "5-",
        ]
        for phrase in banned:
            if phrase in lowered:
                return f"closing must not include unsupported phrase: {phrase}"
        closing_assessment_phrase = str(payload.get("closing_assessment_phrase") or "").strip()
        if closing_assessment_phrase and text.count(closing_assessment_phrase) != 1:
            return f"closing must include closing_assessment_phrase exactly once: {closing_assessment_phrase}"
        player_of_match_name = str(payload.get("player_of_match_name") or "").strip()
        player_of_match_team = str(payload.get("player_of_match_team") or "").strip()
        if player_of_match_name:
            if text.count(player_of_match_name) != 1:
                return f"closing must mention player_of_match_name exactly once: {player_of_match_name}"
            if player_of_match_team and player_of_match_team not in text:
                return f"closing must mention player_of_match_team: {player_of_match_team}"
            if lowered.count("player of the match") != 1:
                return "closing must include 'player of the match' exactly once"
        elif "player of the match" in lowered:
            return "closing must not mention player of the match when no player_of_match_name is present"
        return ""
    if section == "stats_analysis":
        wc = _word_count(text)
        min_words = int(payload.get("min_words") or 24)
        max_words = int(payload.get("max_words") or 115)
        if wc < min_words or wc > max_words:
            return f"stats_analysis must be {min_words}-{max_words} words, got {wc}"
        sentences = _sentence_count(text)
        sentence_min = int(payload.get("sentence_count_min") or 1)
        sentence_max = int(payload.get("sentence_count_max") or 4)
        if sentences < sentence_min or sentences > sentence_max:
            return f"stats_analysis must be {sentence_min}-{sentence_max} sentences, got {sentences}"
        if not re.search(r"[.!?]$", text):
            return "stats_analysis must end with sentence punctuation"
        lowered = text.lower()
        banned = [
            "0-",
            "1-",
            "2-",
            "3-",
            "final score",
            "scoreline",
            "full-time",
            "goalscorer",
            "won",
            "victory",
            "defeat",
            "unable to capitalize",
            "tactics",
            "formation",
            "deserved",
            "favored",
            "edged",
            "comfortably",
            "narrowly",
            "superior",
            "inferior",
            "better",
            "worse",
            "respectively",
            "the teams",
            "both sides",
        ]
        for phrase in banned:
            if phrase in lowered:
                return f"stats_analysis must not include unsupported phrase: {phrase}"
        stat_points = payload.get("stat_points_for_narration") or []
        positions: list[int] = []
        for point in stat_points:
            label = str(point.get("label") or "").strip()
            home_team = str(point.get("home_team") or "").strip()
            away_team = str(point.get("away_team") or "").strip()
            home_value = str(point.get("home_value") or "").strip()
            away_value = str(point.get("away_value") or "").strip()
            if label and len(re.findall(_stat_label_pattern(label), lowered)) < 1:
                return f"stats_analysis must include stat label: {label}"
            if home_team and text.count(home_team) < len(stat_points):
                return f"stats_analysis must include team name: {home_team}"
            if away_team and text.count(away_team) < len(stat_points):
                return f"stats_analysis must include team name: {away_team}"
            if home_value and home_value not in text:
                return f"stats_analysis must include stat value: {home_value}"
            if away_value and away_value not in text:
                return f"stats_analysis must include stat value: {away_value}"
            match = re.search(_stat_label_pattern(label), lowered)
            positions.append(match.start() if match else -1)
        if positions != sorted(positions):
            return "stats_analysis must mention stat points in the JSON order"
        insights = payload.get("stats_insights") or {}
        dominant_team = str(insights.get("dominant_team") or "").strip()
        clinical_team = str(insights.get("clinical_team") or "").strip()
        dominant_mentions = lowered.count("dominant")
        clinical_mentions = lowered.count("clinical")
        if dominant_team and dominant_team != "Level":
            if dominant_mentions != 1:
                return "stats_analysis must mention dominant insight exactly once"
            if dominant_team not in text:
                return "stats_analysis dominant insight must name the allowed team"
        elif dominant_mentions:
            return "stats_analysis must not mention dominant insight when dominant_team is Level"
        if clinical_team and clinical_team != "Level":
            if clinical_mentions != 1:
                return "stats_analysis must mention clinical insight exactly once"
            if clinical_team not in text:
                return "stats_analysis clinical insight must name the allowed team"
        elif clinical_mentions:
            return "stats_analysis must not mention clinical insight when clinical_team is Level"
        last_stat_pos = max(positions) if positions else -1
        first_insight_pos = min(
            pos
            for pos in (lowered.find("dominant team"), lowered.find("more clinical team"))
            if pos != -1
        ) if ("dominant team" in lowered or "more clinical team" in lowered) else -1
        if first_insight_pos != -1 and first_insight_pos < last_stat_pos:
            return "stats_analysis must place insight statements after all stat points"
        return ""
    if section == "top_performers":
        wc = _word_count(text)
        min_words = int(payload.get("min_words") or 18)
        max_words = int(payload.get("max_words") or 110)
        if wc < min_words or wc > max_words:
            return f"top_performers must be {min_words}-{max_words} words, got {wc}"
        sentences = _sentence_count(text)
        sentence_min = int(payload.get("sentence_count_min") or 1)
        sentence_max = int(payload.get("sentence_count_max") or 3)
        if sentences < sentence_min or sentences > sentence_max:
            return f"top_performers must be {sentence_min}-{sentence_max} sentences, got {sentences}"
        if not re.search(r"[.!?]$", text):
            return "top_performers must end with sentence punctuation"
        sentence_texts = _sentence_parts(text)
        performers = payload.get("performers_for_narration") or []
        if len(sentence_texts) != len(performers):
            return "top_performers must use one sentence per performer"
        lowered = text.lower()
        banned = [
            "what a performance",
            "solid game",
            "standout",
            "brilliant",
            "excellent",
            "superb",
            "dominant",
            "man of the match",
            "influential",
            "importance",
            "impressed",
            "starred",
            "shined",
            "excelled",
            "inspired",
            "led",
        ]
        for phrase in banned:
            if phrase in lowered:
                return f"top_performers must not include unsupported praise phrase: {phrase}"
        player_of_match_mentions = lowered.count("player of the match")
        expected_potm = 1 if any(bool(p.get("is_player_of_match")) for p in performers) else 0
        if player_of_match_mentions != expected_potm:
            return f"top_performers must mention 'player of the match' exactly {expected_potm} time(s)"
        name_positions: list[int] = []
        for sentence, performer in zip(sentence_texts, performers):
            name = str(performer.get("name") or "").strip()
            team = str(performer.get("team") or "").strip()
            rating = str(performer.get("rating") or "").strip()
            if name and name not in sentence:
                return f"top_performers sentence must include player name: {name}"
            if team and team not in sentence:
                return f"top_performers sentence must include team name: {team}"
            rating_value = _safe_float_local(rating)
            if rating and rating_value > 0 and rating not in sentence:
                return f"top_performers sentence must include rating: {rating}"
            if rating_value <= 0 and "rating" in sentence.lower():
                return f"top_performers sentence must not mention zero/empty rating for {name}"
            goals = int(performer.get("goals") or 0)
            assists = int(performer.get("assists") or 0)
            if goals > 0 and (str(goals) not in sentence or "goal" not in sentence.lower()):
                return f"top_performers sentence must include goals for {name}"
            if assists > 0 and (str(assists) not in sentence or "assist" not in sentence.lower()):
                return f"top_performers sentence must include assists for {name}"
            name_positions.append(text.find(name))
            stat_checks = []
            for field, phrase in (
                ("goals", "goal"),
                ("assists", "assist"),
                ("shots_on", "shot"),
                ("saves", "save"),
                ("key_passes", "key pass"),
                ("tackles", "tackle"),
                ("interceptions", "interception"),
            ):
                value = int(performer.get(field) or 0)
                if value > 0:
                    stat_checks.append(str(value) in sentence and phrase in sentence.lower())
            if bool(performer.get("clean_sheet")):
                stat_checks.append("clean sheet" in sentence.lower())
            if stat_checks and not any(stat_checks):
                return f"top_performers sentence must include at least one non-zero stat for {name}"
            if goals == 0 and assists == 0:
                primary_metric = _primary_performer_metric(performer)
                if primary_metric:
                    metric_name, metric_value = primary_metric
                    if metric_name == "saves" and (str(metric_value) not in sentence or "save" not in sentence.lower()):
                        return f"top_performers sentence must include saves for {name}"
                    if metric_name == "shots_on" and (str(metric_value) not in sentence or "shot" not in sentence.lower()):
                        return f"top_performers sentence must include shots on target for {name}"
                    if metric_name == "key_passes" and (str(metric_value) not in sentence or "key pass" not in sentence.lower()):
                        return f"top_performers sentence must include key passes for {name}"
                    if metric_name == "tackles" and (str(metric_value) not in sentence or "tackle" not in sentence.lower()):
                        return f"top_performers sentence must include tackles for {name}"
                    if metric_name == "interceptions" and (str(metric_value) not in sentence or "interception" not in sentence.lower()):
                        return f"top_performers sentence must include interceptions for {name}"
                    if metric_name == "clean_sheet" and "clean sheet" not in sentence.lower():
                        return f"top_performers sentence must include clean sheet for {name}"
                    if metric_name == "minutes" and (str(metric_value) not in sentence or "minute" not in sentence.lower()):
                        return f"top_performers sentence must include minutes for {name}"
        if name_positions != sorted(name_positions):
            return "top_performers must mention performers in the JSON order"
        return ""
    if section == "goals_recap":
        wc = _word_count(text)
        min_words = int(payload.get("min_words") or 30)
        max_words = int(payload.get("max_words") or 75)
        if wc < min_words or wc > max_words:
            return f"goals_recap must be {min_words}-{max_words} words, got {wc}"
        sentences = _sentence_count(text)
        sentence_min = int(payload.get("sentence_count_min") or 1)
        sentence_max = int(payload.get("sentence_count_max") or 3)
        if sentences < sentence_min or sentences > sentence_max:
            return f"goals_recap must be {sentence_min}-{sentence_max} sentences, got {sentences}"
        if not re.search(r"[.!?]$", text):
            return "goals_recap must end with sentence punctuation"
        lowered = text.lower()
        banned = [
            "let's take a look",
            "what a dominant",
            "dominant display",
            "sealed the deal",
            "final nail",
            "convincing win",
            "final score",
            "full-time",
            "three points",
            "qualified",
            "qualification",
            "eliminated",
            "standings",
            "table",
            "possession",
            "tactical",
            "tactics",
            "scored twice",
            "scored again",
            "two goals",
            "brace",
            "hat-trick",
            "hat trick",
            "added another",
            "added a goal",
            "completed a brace",
            "netted twice",
            "1-0",
            "2-0",
            "3-0",
            "1-1",
            "2-1",
            "3-1",
            "made it",
            "put brazil",
            "put scotland",
        ]
        for phrase in banned:
            if phrase in lowered:
                return f"goals_recap must not include unsupported/filler phrase: {phrase}"
        if re.search(r"\b45\+3['’]?\s*minute\b|\b45th minute\b", text, re.IGNORECASE):
            return "goals_recap must use first-half stoppage time wording"
        if re.search(r"\bin the \d+ minutes\b", text, re.IGNORECASE):
            return "goals_recap must not say 'in the X minutes'"
        goals = payload.get("goals_for_narration") or []
        positions: list[int] = []
        required_players = {str(goal.get("player") or "").strip() for goal in goals if goal.get("player")}
        required_assists = {str(goal.get("assist") or "").strip() for goal in goals if goal.get("assist")}
        for player in required_players:
            if player and player not in text:
                return f"goals_recap must include scorer: {player}"
        required_teams = {str(goal.get("team") or "").strip() for goal in goals if goal.get("team")}
        for team in required_teams:
            if team and team not in text:
                return f"goals_recap must include team: {team}"
        for assist in required_assists:
            if assist and assist not in text:
                return f"goals_recap must include assist: {assist}"
        for goal in goals:
            minute = goal.get("minute")
            detail = goal.get("detail")
            if minute and minute not in text:
                return f"goals_recap must include minute wording: {minute}"
            if detail and detail not in text:
                return f"goals_recap must include special goal detail: {detail}"
            if minute:
                positions.append(text.find(minute))
        if not any(goal.get("assist") for goal in goals) and re.search(r"\bassist(?:ed|s)?\b", lowered):
            return "goals_recap must not mention assists when no assist exists in JSON"
        if positions != sorted(positions):
            return "goals_recap must narrate goals in chronological order"
        return ""
    if section == "second_half":
        wc = _word_count(text)
        min_words = int(payload.get("min_words") or 30)
        max_words = int(payload.get("max_words") or 70)
        if wc < min_words or wc > max_words:
            return f"second_half must be {min_words}-{max_words} words, got {wc}"
        sentences = _sentence_count(text)
        if sentences != 2:
            return f"second_half must be exactly 2 sentences, got {sentences}"
        if not re.search(r"[.!?]$", text):
            return "second_half must end with sentence punctuation"
        sentence_texts = _sentence_parts(text)
        score_phrase = payload.get("second_half_score_phrase")
        if score_phrase and text.count(score_phrase) != 1:
            return f"second_half must include second_half_score_phrase exactly once: {score_phrase}"
        if score_phrase and score_phrase not in sentence_texts[0]:
            return "second_half sentence 1 must include second_half_score_phrase"
        lowered = text.lower()
        banned = [
            "possession",
            "pressed",
            "pressing",
            "chances",
            "shot",
            "shots",
            "tactical",
            "tactics",
            "dominated the ball",
            "controlled possession",
            "exciting second half",
            "dramatic second half",
            "tense second half",
            "entertaining second half",
            "lively contest",
            "action-packed half",
            "thrilling second half",
            "all three points",
            "qualified",
            "qualification",
            "eliminated",
            "standings",
            "table",
            "seal the win",
            "sealed the win",
        ]
        for phrase in banned:
            if phrase in lowered:
                return f"second_half must not include unsupported analysis: {phrase}"
        events = payload.get("second_half_events_for_narration") or []
        event_sentence = sentence_texts[1]
        unique_players = {str(event.get("player") or "").strip() for event in events if event.get("player")}
        for player_name in unique_players:
            if player_name and event_sentence.count(player_name) > 1:
                return f"second_half must avoid repeating player name unnecessarily: {player_name}"
        event_positions: list[int] = []
        for event in events:
            player = event.get("player")
            assist = event.get("assist")
            minute = event.get("minute")
            if player and player not in text:
                return f"second_half must include player: {player}"
            if player and player not in event_sentence:
                return f"second_half sentence 2 must include player: {player}"
            if assist and assist not in text:
                return f"second_half must include assist: {assist}"
            if assist and assist not in event_sentence:
                return f"second_half sentence 2 must include assist: {assist}"
            if minute and minute not in text:
                return f"second_half must include minute wording: {minute}"
            if minute and minute not in event_sentence:
                return f"second_half sentence 2 must include minute wording: {minute}"
            if minute:
                event_positions.append(event_sentence.find(minute))
        if event_positions != sorted(event_positions):
            return "second_half must narrate events in chronological order"
        return ""
    if section == "first_half":
        wc = _word_count(text)
        min_words = int(payload.get("min_words") or 30)
        max_words = int(payload.get("max_words") or 70)
        if wc < min_words or wc > max_words:
            return f"first_half must be {min_words}-{max_words} words, got {wc}"
        sentences = _sentence_count(text)
        if sentences != 2:
            return f"first_half must be exactly 2 sentences, got {sentences}"
        if not re.search(r"[.!?]$", text):
            return "first_half must end with sentence punctuation"
        sentence_texts = _sentence_parts(text)
        score_phrase = payload.get("first_half_score_phrase")
        if score_phrase and text.count(score_phrase) != 1:
            return f"first_half must include first_half_score_phrase exactly once: {score_phrase}"
        if score_phrase and score_phrase not in sentence_texts[0]:
            return "first_half sentence 1 must include first_half_score_phrase"
        lowered = text.lower()
        banned = [
            "possession",
            "pressed",
            "pressing",
            "chances",
            "shot",
            "shots",
            "tactical",
            "tactics",
            "dominated the ball",
            "controlled possession",
            "exciting first half",
            "exciting half",
            "dramatic first half",
            "dramatic half",
            "tense first half",
            "tense half",
            "entertaining first half",
            "entertaining half",
            "lively contest",
            "action-packed half",
            "thrilling first half",
            "thrilling half",
        ]
        for phrase in banned:
            if phrase in lowered:
                return f"first_half must not include unsupported analysis: {phrase}"
        events = payload.get("first_half_events_for_narration") or []
        event_positions: list[int] = []
        event_sentence = sentence_texts[1]
        unique_players = {str(event.get("player") or "").strip() for event in events if event.get("player")}
        for player_name in unique_players:
            if player_name and event_sentence.count(player_name) > 1:
                return f"first_half must avoid repeating player name unnecessarily: {player_name}"
        for event in events:
            player = event.get("player")
            assist = event.get("assist")
            minute = event.get("minute")
            phrase = event.get("phrase")
            if player and player not in text:
                return f"first_half must include player: {player}"
            if player and player not in event_sentence:
                return f"first_half sentence 2 must include player: {player}"
            if assist and assist not in text:
                return f"first_half must include assist: {assist}"
            if assist and assist not in event_sentence:
                return f"first_half sentence 2 must include assist: {assist}"
            if minute and minute not in text:
                return f"first_half must include minute wording: {minute}"
            if minute and minute not in event_sentence:
                return f"first_half sentence 2 must include minute wording: {minute}"
            if minute:
                event_positions.append(event_sentence.find(minute))
            if phrase and text.count(phrase) > 1:
                return f"first_half must not repeat event phrase: {phrase}"
            if minute == "first-half stoppage time" and re.search(r"\b45th minute\b|\b45th\b", text, re.IGNORECASE):
                return "first_half must not call first-half stoppage time the 45th minute"
        if event_positions != sorted(event_positions):
            return "first_half must narrate events in chronological order"
        return ""
    if section == "match_result":
        wc = _word_count(text)
        if wc < 24 or wc > 45:
            return f"match_result must be 24-45 words, got {wc}"
        sentences = _sentence_count(text)
        if sentences != 1:
            return f"match_result must be exactly 1 sentence, got {sentences}"
        if not re.search(r"[.!?]$", text):
            return "match_result must end with sentence punctuation"
        preferred_score_phrase = payload.get("preferred_score_phrase")
        if preferred_score_phrase and text.count(preferred_score_phrase) != 1:
            return f"match_result must include preferred_score_phrase exactly once: {preferred_score_phrase}"
        match_context_phrase = payload.get("match_context_phrase")
        if match_context_phrase and not text.startswith(f"In {match_context_phrase},"):
            return f"match_result must start with match_context_phrase: In {match_context_phrase},"
        winner_confirmation_phrase = payload.get("winner_confirmation_phrase")
        if winner_confirmation_phrase and text.count(winner_confirmation_phrase) != 1:
            return f"match_result must include winner_confirmation_phrase exactly once: {winner_confirmation_phrase}"
        banned = [
            "all three points",
            "three points",
            "top of",
            "qualified",
            "qualification",
            "eliminated",
            "standings",
            "table",
            "scored",
            "goal",
            "assist",
            "possession",
            "shots",
        ]
        lowered = text.lower()
        for phrase in banned:
            if phrase in lowered:
                return f"match_result must not include unsupported/detail phrase: {phrase}"
        return ""
    if section != "opening_hook":
        return ""
    wc = _word_count(text)
    if wc < 35 or wc > 65:
        return f"opening_hook must be 35-65 words, got {wc}"
    sentences = _sentence_count(text)
    if sentences != 2:
        return f"opening_hook must be exactly 2 sentences, got {sentences}"
    sentence_texts = _sentence_parts(text)
    for idx, sentence in enumerate(sentence_texts, start=1):
        sentence_wc = _word_count(sentence)
        if sentence_wc < 16 or sentence_wc > 35:
            return f"opening_hook sentence {idx} must be 16-35 words, got {sentence_wc}"
    preferred_score_phrase = payload.get("preferred_score_phrase")
    if preferred_score_phrase and text.count(preferred_score_phrase) != 1:
        return f"opening_hook must include preferred_score_phrase exactly: {preferred_score_phrase}"
    if re.search(r"\b[a-z]+_[a-z_]+\b", text):
        return "opening_hook must not include raw snake_case labels"
    if re.search(r"\b(key moments|turning points|decisive moments)\s*:", text, re.IGNORECASE):
        return "opening_hook must not use label-style phrasing"
    moments = payload.get("hook_moments_for_narration") or []
    if moments:
        copied = [moment for moment in moments[:3] if moment in text]
        if copied:
            return "opening_hook must not copy hook_moments_for_narration verbatim"
    player_names = []
    for moment in moments[:3]:
        parts = moment.split(" ", 2)
        if len(parts) >= 2:
            player_names.append(f"{parts[0]} {parts[1]}")
    if player_names:
        mentioned_players = sum(1 for name in dict.fromkeys(player_names) if name in text)
        if mentioned_players < min(2, len(set(player_names))):
            return "opening_hook must mention at least two hook player names"
        for sentence in sentence_texts:
            for name in set(player_names):
                if sentence.count(name) > 1:
                    return "opening_hook must avoid repeating the same player name within one sentence"
    return ""


def _fallback_section(section: str, facts: MatchFacts) -> str:
    if section == "opening_hook":
        if facts.winner and facts.winner != "Draw":
            result_style = "dominant" if facts.match_result_type == "dominant_win" else "decisive"
            venue = f" at {facts.venue.split(',')[0]}" if facts.venue else ""
            context = f" in a {result_style} {facts.competition} performance{venue}"
            group_name = _group_name(facts)
            if group_name:
                context += f", turning {group_name} into a statement night"
            first_goal = facts.goals[0] if facts.goals else {}
            second_goal = facts.goals[1] if len(facts.goals) > 1 else {}
            third_goal = facts.goals[2] if len(facts.goals) > 2 else {}
            moments = []
            if first_goal.get("player"):
                moments.append(f"{first_goal['player']} struck early")
            if second_goal.get("player") == first_goal.get("player"):
                moments.append("added another in first-half stoppage time")
            elif second_goal.get("player"):
                moments.append(f"{second_goal['player']} added another")
            if third_goal.get("player"):
                clean_sheet = " the clean sheet" if "clean_sheet" in facts.result_tags else " victory"
                moments.append(f"{third_goal['player']} sealed{clean_sheet} after {_narrative_minute(third_goal)}")
            if moments:
                if len(moments) == 1:
                    moment_text = moments[0]
                elif len(moments) == 2:
                    moment_text = " before ".join(moments)
                else:
                    moment_text = f"{moments[0]} and {moments[1]}, then {moments[2]}"
                return f"{_preferred_score_phrase(facts)}{context}. {moment_text}.".strip()
            return f"{_preferred_score_phrase(facts)}{context}. {facts.winner} controlled the result with a confirmed clean sheet and a composed full-time performance.".strip()
        return f"{facts.home_team} and {facts.away_team} finished level after a tense contest."
    if section == "match_result":
        context = _match_context_phrase(facts)
        if facts.winner == "Draw":
            return f"In {context}, {facts.home_team} and {facts.away_team} finished {facts.scoreline}, {_winner_confirmation_phrase(facts)}."
        result_style = facts.match_result_type.replace("_", " ") if facts.match_result_type else "confirmed"
        return f"In {context}, {_preferred_score_phrase(facts)} in a {result_style}, {_winner_confirmation_phrase(facts)}."
    if section == "first_half":
        score_phrase = _first_half_score_phrase(facts)
        events = _first_half_events_for_narration(facts)
        if not events:
            return f"{score_phrase}, with no first-half goals or major recorded incidents in the available match data."
        event_texts = [event["phrase"] for event in events if event.get("phrase")]
        if len(event_texts) == 1:
            story = event_texts[0]
        elif len(event_texts) == 2:
            first_event, second_event = events[0], events[1]
            if first_event.get("player") and first_event.get("player") == second_event.get("player"):
                second_assist = f" from {second_event['assist']}'s assist" if second_event.get("assist") else ""
                story = (
                    f"{event_texts[0]}, before he doubled {second_event.get('team')}'s lead "
                    f"in {second_event.get('minute')}{second_assist}"
                )
            else:
                story = f"{event_texts[0]}, before {event_texts[1]}"
        else:
            story = f"{', '.join(event_texts[:-1])}, before {event_texts[-1]}"
        return f"{score_phrase}. {story}."
    if section == "second_half":
        score_phrase = _second_half_score_phrase(facts)
        events = _second_half_events_for_narration(facts)
        if not events:
            return f"{score_phrase}. No second-half goals or major recorded incidents were available in the match data."
        event_texts = []
        for event in events:
            if event.get("player") and event.get("team") and event.get("minute"):
                assist = f" from {event['assist']}'s assist" if event.get("assist") else ""
                only = "only " if len(events) == 1 else ""
                event_texts.append(f"{event['player']} added {event['team']}'s {only}second-half goal after {event['minute']}{assist}")
        if len(event_texts) == 1:
            story = event_texts[0]
        elif len(event_texts) == 2:
            first_event, second_event = events[0], events[1]
            if first_event.get("player") and first_event.get("player") == second_event.get("player"):
                second_assist = f" from {second_event['assist']}'s assist" if second_event.get("assist") else ""
                story = (
                    f"{event_texts[0]}, before he added another for {second_event.get('team')} "
                    f"after {second_event.get('minute')}{second_assist}"
                )
            else:
                story = f"{event_texts[0]}, before {event_texts[1]}"
        else:
            story = f"{', '.join(event_texts[:-1])}, before {event_texts[-1]}"
        return f"{score_phrase}. {story}."
    if section == "goals_recap" and facts.goals:
        goals = _goals_for_narration(facts)
        lines = []
        for index, goal in enumerate(goals):
            player = goal.get("player") or "A scorer"
            team = goal.get("team") or "their team"
            minute = goal.get("minute") or "the recorded minute"
            assist = f" from {goal['assist']}'s assist" if goal.get("assist") else ""
            if index == 0:
                lines.append(f"{player} opened the scoring for {team} after {minute}{assist}")
            elif player == goals[index - 1].get("player"):
                lines.append(f"{player} scored for {team} in {minute}{assist}")
            else:
                lines.append(f"{player} scored for {team} after {minute}{assist}")
        if len(lines) == 1:
            return f"{lines[0]}. No other goals were listed in the match data."
        if len(lines) <= 4:
            midpoint = max(1, (len(lines) + 1) // 2)
            first_sentence = ", then ".join(lines[:midpoint])
            second_sentence = ", then ".join(lines[midpoint:])
            return f"{first_sentence}. {second_sentence}."
        first_sentence = ", then ".join(lines[:2])
        second_sentence = ", then ".join(lines[2:4])
        third_sentence = ", then ".join(lines[4:])
        return f"{first_sentence}. {second_sentence}. {third_sentence}."
    if section == "top_performers" and facts.top_players:
        performers = _performers_for_narration(facts)
        lines = []
        for performer in performers:
            name = performer.get("name") or "A player"
            team = performer.get("team") or "their team"
            rating = performer.get("rating") or ""
            parts = [f"{name}"]
            if performer.get("is_player_of_match"):
                parts.append(f"was the player of the match for {team}")
            else:
                parts.append(f"was one of the key performers for {team}")
            if rating:
                parts.append(f"with a {rating} rating")
            stats: list[str] = []
            if int(performer.get("goals") or 0) > 0:
                goals = int(performer["goals"])
                stats.append(f"{goals} goal" if goals == 1 else f"{goals} goals")
            if int(performer.get("assists") or 0) > 0:
                assists = int(performer["assists"])
                stats.append(f"{assists} assist" if assists == 1 else f"{assists} assists")
            if int(performer.get("shots_on") or 0) > 0:
                shots_on = int(performer["shots_on"])
                stats.append(f"{shots_on} shot on target" if shots_on == 1 else f"{shots_on} shots on target")
            if int(performer.get("saves") or 0) > 0:
                saves = int(performer["saves"])
                stats.append(f"{saves} save" if saves == 1 else f"{saves} saves")
            if int(performer.get("key_passes") or 0) > 0:
                key_passes = int(performer["key_passes"])
                stats.append(f"{key_passes} key pass" if key_passes == 1 else f"{key_passes} key passes")
            if int(performer.get("tackles") or 0) > 0:
                tackles = int(performer["tackles"])
                stats.append(f"{tackles} tackle" if tackles == 1 else f"{tackles} tackles")
            if int(performer.get("interceptions") or 0) > 0:
                interceptions = int(performer["interceptions"])
                stats.append(f"{interceptions} interception" if interceptions == 1 else f"{interceptions} interceptions")
            if bool(performer.get("clean_sheet")):
                stats.append("a clean sheet")
            if stats:
                parts.append("after recording " + ", ".join(stats))
            lines.append(" ".join(parts) + ".")
        return " ".join(lines)
    if section == "stats_analysis" and facts.statistics:
        points = _stats_points_for_narration(facts.statistics, facts.home_team, facts.away_team)
        if not points:
            return ""
        phrases = []
        for point in points:
            phrases.append(
                f"For {point['label']}, {point['home_team']} had {point['home_value']} and {point['away_team']} had {point['away_value']}"
            )
        insights = facts.stats_insights or {}
        stat_sentences: list[str] = []
        if len(phrases) <= 2:
            stat_sentences.append("; ".join(phrases) + ".")
        elif len(phrases) <= 4:
            stat_sentences.append("; ".join(phrases[:2]) + ".")
            stat_sentences.append("; ".join(phrases[2:]) + ".")
        else:
            stat_sentences.append("; ".join(phrases[:2]) + ".")
            stat_sentences.append("; ".join(phrases[2:4]) + ".")
            stat_sentences.append(phrases[4] + ".")
        insight_bits = []
        if str(insights.get("dominant_team") or "") not in {"", "Level"}:
            insight_bits.append(f"{insights['dominant_team']} were the dominant team")
        if str(insights.get("clinical_team") or "") not in {"", "Level"}:
            insight_bits.append(f"{insights['clinical_team']} were the more clinical team")
        if insight_bits:
            stat_sentences.append(" and ".join(insight_bits) + ".")
        return " ".join(piece.strip() for piece in stat_sentences if piece.strip())
    if section == "closing":
        assessment = _closing_assessment_phrase(facts)
        player_name = str((facts.player_of_match or {}).get("name") or "").strip()
        player_team = str((facts.player_of_match or {}).get("team") or "").strip()
        if player_name:
            if player_team:
                return f"{assessment}, with {player_name} of {player_team} named player of the match."
            return f"{assessment}, with {player_name} named player of the match."
        return f"{assessment}."
    return ""


def _generate_section_texts(facts: MatchFacts) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    for section, instruction in _SECTION_SPECS:
        if _should_skip_section(facts, section):
            continue
        try:
            text = _generate_section(section, instruction, facts)
        except Exception as exc:
            logger.warning("Match script section failed (%s): %s", section, exc)
            _write_debug_artifact(
                facts.fixture_id,
                f"llm_{section}_fallback",
                {"section": section, "error_type": type(exc).__name__, "error": str(exc)},
            )
            text = _fallback_section(section, facts)
        if text:
            _write_debug_artifact(facts.fixture_id, f"section_{section}_text", {"section": section, "text": text})
            sections.append((section, text))

    if not sections:
        sections = [
            ("opening_hook", _fallback_section("opening_hook", facts)),
            ("match_result", _fallback_section("match_result", facts)),
            ("closing", _fallback_section("closing", facts)),
        ]
    return [(section, text) for section, text in sections if text]


def _make_match_script(
    facts: MatchFacts,
    text: str,
    selected_clip_ids: list[str],
    *,
    news_id: str,
    script_format: str,
    panel_label: str,
) -> Script:
    wc = _word_count(text)
    estimated_duration = _estimate_duration(wc)
    return Script(
        news_id=news_id,
        script_type="tactical",
        format=script_format,
        text=text,
        word_count=wc,
        estimated_duration_seconds=estimated_duration,
        selected_clip_ids=selected_clip_ids,
        display_headline=f"{facts.home_team.upper()} {facts.scoreline} {facts.away_team.upper()}",
        panel_label=panel_label,
        display_points=build_display_points(facts),
    )


def generate_match_script(facts: MatchFacts, clips: list | None = None) -> Script:
    sections = _generate_section_texts(facts)
    text = "\n\n".join(section_text for _, section_text in sections).strip()
    wc = _word_count(text)
    estimated_duration = _estimate_duration(wc)
    script = _make_match_script(
        facts,
        text,
        select_match_clip_ids(facts, clips or [], estimated_duration),
        news_id=f"match_{facts.fixture_id}",
        script_format="match",
        panel_label="MATCH STATS",
    )
    logger.info("Match script generated for fixture %s: %d words", facts.fixture_id, wc)
    _write_debug_artifact(
        facts.fixture_id,
        "script_selected_clips",
        {
            "selected_clip_ids": script.selected_clip_ids,
            "estimated_duration_seconds": estimated_duration,
            "word_count": wc,
        },
    )
    return script


def generate_match_script_parts(facts: MatchFacts, clips: list | None = None) -> list[Script]:
    sections = _generate_section_texts(facts)
    available_clips = clips or []
    used_clip_ids: set[str] = set()
    scripts: list[Script] = []

    for index, (section, text) in enumerate(sections, start=1):
        wc = _word_count(text)
        estimated_duration = _estimate_duration(wc)
        selected_clip_ids = select_match_clip_ids(
            facts,
            available_clips,
            estimated_duration,
            exclude_clip_ids=used_clip_ids,
        )
        used_clip_ids.update(selected_clip_ids)
        scripts.append(
            _make_match_script(
                facts,
                text,
                selected_clip_ids,
                news_id=f"match_{facts.fixture_id}_{index:02d}_{section}",
                script_format="match_part",
                panel_label=_SECTION_LABELS.get(section, "Match Summary").upper(),
            )
        )

    logger.info(
        "Match script parts generated for fixture %s: %d part(s), %d total words",
        facts.fixture_id,
        len(scripts),
        sum(script.word_count for script in scripts),
    )
    _write_debug_artifact(
        facts.fixture_id,
        "script_parts",
        [
            {
                "news_id": script.news_id,
                "panel_label": script.panel_label,
                "word_count": script.word_count,
                "estimated_duration_seconds": script.estimated_duration_seconds,
                "selected_clip_ids": script.selected_clip_ids,
                "text": script.text,
            }
            for script in scripts
        ],
    )
    return scripts


def combine_match_script_parts(facts: MatchFacts, scripts: list[Script]) -> Script:
    text = "\n\n".join(script.text for script in scripts if script.text).strip()
    selected_clip_ids = sorted({clip_id for script in scripts for clip_id in script.selected_clip_ids})
    return _make_match_script(
        facts,
        text,
        selected_clip_ids,
        news_id=f"match_{facts.fixture_id}",
        script_format="match",
        panel_label="MATCH STATS",
    )


def build_display_points(facts: MatchFacts) -> list[str]:
    points = [f"Final score: {facts.home_team} {facts.scoreline} {facts.away_team}"]
    if facts.winner and facts.winner != "Draw":
        points.append(f"Winner: {facts.winner}")
    elif facts.winner == "Draw":
        points.append("Result: Draw")
    if facts.goals:
        scorers = ", ".join(
            f"{goal.get('player')} {goal.get('minute')}"
            for goal in facts.goals[:3]
            if goal.get("player")
        )
        if scorers:
            points.append(f"Goals: {scorers}")
    if len(points) < 3 and facts.statistics:
        points.append("Stats: possession, shots and discipline reviewed")
    return points[:3]


def _clip_duration_seconds(clip: dict) -> float:
    duration = clip["duration"]
    if isinstance(duration, (int, float)) and duration > 0:
        return float(duration)
    return 6.0


def _match_terms(facts: MatchFacts) -> set[str]:
    text = " ".join(
        [
            facts.home_team,
            facts.away_team,
            facts.competition,
            facts.round_name,
            "football soccer match goal stadium highlights",
        ]
    ).lower()
    return {term for term in re.findall(r"[a-z0-9']+", text) if len(term) >= 3}


def _clip_score(clip: dict, terms: set[str]) -> tuple[int, float]:
    clip_text = " ".join([clip["description"] or "", clip["keywords"] or ""]).lower()
    clip_terms = {term for term in re.findall(r"[a-z0-9']+", clip_text) if len(term) >= 3}
    return len(terms & clip_terms), _clip_duration_seconds(clip)


def select_match_clip_ids(
    facts: MatchFacts,
    clips: list,
    target_duration_seconds: int,
    exclude_clip_ids: set[str] | None = None,
) -> list[str]:
    if not clips or target_duration_seconds <= 0:
        return []
    exclude_clip_ids = exclude_clip_ids or set()
    terms = _match_terms(facts)
    ranked = sorted(clips, key=lambda clip: _clip_score(clip, terms), reverse=True)
    selected: list[str] = []
    total_duration = 0.0
    for clip in ranked:
        clip_id = str(clip["id"])
        if clip_id in selected or clip_id in exclude_clip_ids:
            continue
        selected.append(clip_id)
        total_duration += _clip_duration_seconds(clip)
        if total_duration >= target_duration_seconds:
            break
    logger.info(
        "Match clip coverage for fixture %s: %.1fs / target %ss using %d clip(s)",
        facts.fixture_id,
        total_duration,
        target_duration_seconds,
        len(selected),
    )
    return selected


def build_match_news_item(facts: MatchFacts) -> NewsItem:
    headline = f"{facts.home_team} {facts.scoreline} {facts.away_team}: Full Match Summary"
    body = json.dumps(facts.to_dict(), ensure_ascii=False)
    return NewsItem(
        id=f"match_{facts.fixture_id}",
        headline=headline,
        body=body,
        url="",
        source="API-Football",
        source_type="rss",
        timestamp=datetime.now(timezone.utc),
    )


def build_match_metadata(facts: MatchFacts) -> VideoMetadata:
    title = f"{facts.home_team} {facts.scoreline} {facts.away_team}: Match Summary & Stats"
    if len(title) > 95:
        title = f"{facts.home_team} vs {facts.away_team}: Match Summary"[:95]
    goal_lines = [
        f"- {goal.get('minute')} {goal.get('player')} ({goal.get('team')})"
        for goal in facts.goals
        if goal.get("player")
    ]
    description_parts = [
        f"{facts.home_team} vs {facts.away_team} finished {facts.scoreline} in {facts.competition}.",
        f"Venue: {facts.venue or 'Not listed'}",
        f"Result: {facts.winner if facts.winner else 'Confirmed'}",
    ]
    if goal_lines:
        description_parts.append("\nGoals:\n" + "\n".join(goal_lines))
    description_parts.append(f"\n{settings.BRAND_NAME} - {settings.BRAND_TAGLINE}")
    description_parts.append("\n#football #matchsummary #footballhighlights")
    tags = [
        "football",
        "match summary",
        "football stats",
        facts.home_team,
        facts.away_team,
        facts.competition,
        settings.BRAND_NAME.lower(),
    ]
    return VideoMetadata(
        title=title[:95],
        description="\n\n".join(description_parts)[:5000],
        tags=[tag for tag in tags if tag][:30],
        privacy_status=settings.POST_MATCH_PRIVACY_STATUS,
    )
