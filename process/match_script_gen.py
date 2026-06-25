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
    ("opening_hook", "Write 1-3 punchy sentences that hook viewers using only the match facts."),
    ("match_result", "State the competition, teams, final score, winner or draw, and venue."),
    ("first_half", "Summarize the first half in 60-100 words using only first-half goals and events."),
    ("second_half", "Summarize the second half in 60-100 words using only second-half goals and events."),
    ("goals_recap", "Narrate every goal chronologically with minute, scorer, and assist if available."),
    ("turning_points", "Explain red cards, penalties, late goals, or other listed important events. If none are provided, return an empty string."),
    ("top_performers", "Discuss the listed top players using only their objective stats."),
    ("stats_analysis", "Explain the available team statistics and what they show about the match."),
    ("closing", "Close with a short assessment. Do not invent next fixtures or milestones."),
]


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


def _estimate_duration(wc: int) -> int:
    return round(wc / 2.5)


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
    }
    if section == "first_half":
        base["first_half_goals"] = facts.first_half_goals
        base["first_half_events"] = [
            e for e in facts.goals + facts.important_events
            if isinstance(e.get("elapsed"), int) and e["elapsed"] <= 45
        ]
    elif section == "second_half":
        base["second_half_goals"] = facts.second_half_goals
        base["second_half_events"] = [
            e for e in facts.goals + facts.important_events
            if not isinstance(e.get("elapsed"), int) or e["elapsed"] > 45
        ]
    elif section == "goals_recap":
        base["goals"] = facts.goals
    elif section == "turning_points":
        base["important_events"] = facts.important_events
        base["red_cards"] = facts.red_cards
        base["penalties"] = facts.penalties
    elif section == "top_performers":
        base["top_players"] = facts.top_players
    elif section == "stats_analysis":
        base["statistics"] = facts.statistics
    elif section == "closing":
        base["standings"] = facts.standings
        base["standings_error"] = facts.standings_error
    else:
        base["goals"] = facts.goals
        base["important_events"] = facts.important_events
    return base


def _should_skip_section(facts: MatchFacts, section: str) -> bool:
    if section == "turning_points":
        return not facts.important_events and not facts.red_cards and not facts.penalties
    if section == "top_performers":
        return not facts.top_players
    if section == "stats_analysis":
        return not facts.statistics
    if section == "goals_recap":
        return not facts.goals
    return False


def _generate_section(section: str, instruction: str, facts: MatchFacts) -> str:
    payload = _compact_facts_for_section(facts, section)
    prompt = (
        "You are a football commentator writing one section of a post-match YouTube script.\n"
        "Use ONLY the facts in the JSON. Do not add injuries, transfers, records, milestones, "
        "next fixtures, quotes, tactics, or names that are not present.\n"
        "If the facts are insufficient for this section, return an empty string.\n"
        "Keep wording natural and energetic, but factual.\n\n"
        f"Section: {section}\n"
        f"Instruction: {instruction}\n"
        f"Facts JSON:\n{json.dumps(payload, ensure_ascii=False, indent=2)}\n\n"
        "Return valid JSON only: {\"text\": \"...\"}"
    )
    _write_debug_artifact(
        facts.fixture_id,
        f"llm_{section}_request",
        {
            "section": section,
            "model": settings.GROQ_MODEL,
            "temperature": 0.45,
            "max_tokens": 700,
            "messages": [{"role": "user", "content": prompt}],
            "facts_payload": payload,
        },
    )
    groq_client = get_groq_client()
    response = groq_client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=700,
        temperature=0.45,
        response_format={"type": "json_object"},
    )
    raw_content = response.choices[0].message.content
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
    data = json.loads(raw_content)
    return str(data.get("text") or "").strip()


def _fallback_section(section: str, facts: MatchFacts) -> str:
    if section == "opening_hook":
        if facts.winner and facts.winner != "Draw":
            return f"{facts.winner} came out on top as {facts.home_team} and {facts.away_team} delivered a decisive post-match story."
        return f"{facts.home_team} and {facts.away_team} finished level after a tense contest."
    if section == "match_result":
        venue = f" at {facts.venue}" if facts.venue else ""
        if facts.winner == "Draw":
            return f"{facts.home_team} drew {facts.away_team} {facts.scoreline}{venue} in {facts.competition}."
        return f"{facts.winner} won as {facts.home_team} finished {facts.scoreline} against {facts.away_team}{venue} in {facts.competition}."
    if section == "goals_recap" and facts.goals:
        lines = []
        for goal in facts.goals:
            assist = f" from {goal['assist']}" if goal.get("assist") else ""
            lines.append(f"{goal.get('player') or 'A scorer'} struck for {goal.get('team')} in the {goal.get('minute')}{assist}.")
        return " ".join(lines)
    if section == "stats_analysis" and facts.statistics:
        return f"The numbers added context to the scoreline, with the available team statistics showing how {facts.home_team} and {facts.away_team} shared control across key areas."
    if section == "closing":
        return "That is the full-time picture from this match, with the result now confirmed and the key numbers telling the story."
    return ""


def generate_match_script(facts: MatchFacts, clips: list | None = None) -> Script:
    sections: list[str] = []
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
            sections.append(text)

    if not sections:
        sections = [
            _fallback_section("opening_hook", facts),
            _fallback_section("match_result", facts),
            _fallback_section("closing", facts),
        ]

    text = "\n\n".join(section for section in sections if section).strip()
    wc = _word_count(text)
    estimated_duration = _estimate_duration(wc)
    script = Script(
        news_id=f"match_{facts.fixture_id}",
        script_type="tactical",
        format="match",
        text=text,
        word_count=wc,
        estimated_duration_seconds=estimated_duration,
        selected_clip_ids=select_match_clip_ids(facts, clips or [], estimated_duration),
        display_headline=f"{facts.home_team.upper()} {facts.scoreline} {facts.away_team.upper()}",
        panel_label="MATCH STATS",
        display_points=build_display_points(facts),
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


def select_match_clip_ids(facts: MatchFacts, clips: list, target_duration_seconds: int) -> list[str]:
    if not clips or target_duration_seconds <= 0:
        return []
    terms = _match_terms(facts)
    ranked = sorted(clips, key=lambda clip: _clip_score(clip, terms), reverse=True)
    selected: list[str] = []
    total_duration = 0.0
    for clip in ranked:
        clip_id = str(clip["id"])
        if clip_id in selected:
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
