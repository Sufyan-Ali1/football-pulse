from datetime import datetime, timezone

from config import settings
from pipeline.post_match_runner import _finished_detected_timestamp, _settle_elapsed, _sleep_seconds_for_fixture
from process.match_facts import extract_match_facts, is_finished_fixture
from process.match_script_gen import build_display_points, select_match_clip_ids


def _sample_match_data():
    return {
        "fixture": {
            "id": 123,
            "date": "2026-06-25T18:00:00+00:00",
            "venue": {"name": "Test Stadium", "city": "Test City"},
            "status": {"short": "FT"},
            "league": {
                "id": 99,
                "name": "Test League",
                "type": "League",
                "round": "Regular Season - 1",
                "season": 2026,
            },
            "teams": {
                "home": {"id": 1, "name": "Home FC", "winner": True},
                "away": {"id": 2, "name": "Away FC", "winner": False},
            },
            "goals": {"home": 2, "away": 1},
        },
        "events": [
            {
                "elapsed": 12,
                "extra": None,
                "team": "Home FC",
                "player": "Home Scorer",
                "assist": "Home Creator",
                "type": "Goal",
                "detail": "Normal Goal",
            },
            {
                "elapsed": 55,
                "extra": None,
                "team": "Away FC",
                "player": "Away Scorer",
                "assist": "",
                "type": "Goal",
                "detail": "Normal Goal",
            },
            {
                "elapsed": 88,
                "extra": None,
                "team": "Home FC",
                "player": "Late Winner",
                "assist": "",
                "type": "Goal",
                "detail": "Normal Goal",
            },
            {
                "elapsed": 90,
                "extra": 2,
                "team": "Away FC",
                "player": "Away Defender",
                "assist": "",
                "type": "Card",
                "detail": "Red Card",
            },
        ],
        "statistics": {
            "Home FC": {"possession": "55%", "shots": "12", "shots_on_goal": "5", "corners": "4", "pass_accuracy": "88%"},
            "Away FC": {"possession": "45%", "shots": "8", "shots_on_goal": "3", "corners": "2", "pass_accuracy": "84%"},
        },
        "lineups": [
            {
                "team_id": 1,
                "team_name": "Home FC",
                "formation": "4-3-3",
                "coach": "Home Coach",
                "start_xi": [{"name": f"Home Player {i}", "number": i, "pos": "M"} for i in range(1, 12)],
            },
            {
                "team_id": 2,
                "team_name": "Away FC",
                "formation": "4-2-3-1",
                "coach": "Away Coach",
                "start_xi": [{"name": f"Away Player {i}", "number": i, "pos": "M"} for i in range(1, 12)],
            },
        ],
        "players": [
            {
                "team_name": "Home FC",
                "players": [
                    {"name": "Late Winner", "pos": "F", "rating": "8.5", "goals_total": 1, "assists": 0, "shots_on": 2, "minutes": 90},
                    {"name": "Home Creator", "pos": "M", "rating": "7.8", "goals_total": 0, "assists": 1, "shots_on": 1, "key_passes": 4, "minutes": 90},
                ],
            },
            {
                "team_name": "Away FC",
                "players": [
                    {"name": "Away Scorer", "pos": "F", "rating": "7.2", "goals_total": 1, "assists": 0, "shots_on": 1, "minutes": 90},
                ],
            },
        ],
        "standings": {
            "title": "Test League Table",
            "group": "Group A",
            "rows": [
                {"rank": 1, "team_id": 1, "team_name": "Home FC", "points": 6, "goals_diff": 2, "played": 2, "win": 2, "draw": 0, "lose": 0},
                {"rank": 2, "team_id": 2, "team_name": "Away FC", "points": 3, "goals_diff": 0, "played": 2, "win": 1, "draw": 0, "lose": 1},
            ],
        },
    }


def test_is_finished_fixture_accepts_final_statuses():
    assert is_finished_fixture({"status": {"short": "FT"}})
    assert is_finished_fixture({"status": {"short": "AET"}})
    assert is_finished_fixture({"status": {"short": "PEN"}})
    assert not is_finished_fixture({"status": {"short": "1H"}})


def test_extract_match_facts_normalizes_core_match_data():
    facts = extract_match_facts(_sample_match_data())

    assert facts.fixture_id == 123
    assert facts.home_team == "Home FC"
    assert facts.away_team == "Away FC"
    assert facts.scoreline == "2-1"
    assert facts.winner == "Home FC"
    assert facts.first_half_goals == {"home": 1, "away": 0}
    assert facts.second_half_goals == {"home": 1, "away": 1}
    assert len(facts.goals) == 3
    assert len(facts.red_cards) == 1
    assert any(event["player"] == "Away Defender" for event in facts.important_events)
    assert any(event["player"] == "Late Winner" and "winning_goal" in event.get("importance_tags", []) for event in facts.important_events)
    assert facts.top_players[0]["name"] == "Late Winner"
    assert facts.player_of_match["name"] == "Late Winner"
    assert facts.match_result_type == "late_winner"
    assert facts.lineups_summary["home"]["formation"] == "4-3-3"
    assert facts.standings_summary["group"] == "Group A"
    assert facts.standings_summary["home"]["rank"] == 1
    assert facts.stats_insights["dominant_team"] == "Home FC"
    assert facts.stats_insights["clinical_team"] == "Home FC"


def test_display_points_and_clip_selection_cover_duration():
    facts = extract_match_facts(_sample_match_data())
    points = build_display_points(facts)
    clips = [
        {"id": "1", "description": "football match stadium goal", "keywords": "soccer", "duration": 6.0},
        {"id": "2", "description": "crowd and football highlights", "keywords": "goal", "duration": 6.0},
        {"id": "3", "description": "training pitch", "keywords": "", "duration": 6.0},
    ]

    assert points[0] == "Final score: Home FC 2-1 Away FC"
    assert select_match_clip_ids(facts, clips, target_duration_seconds=12) == ["1", "2"]


def test_finished_detection_timestamp_backdates_old_finished_match():
    fixture = {
        "date": "2026-06-25T10:00:00+00:00",
        "status": {"short": "FT"},
    }
    now = datetime(2026, 6, 25, 15, 0, tzinfo=timezone.utc)

    assert _finished_detected_timestamp(fixture, now=now) == "2026-06-25T12:00:00+00:00"


def test_settle_elapsed_uses_estimated_finish_when_record_missing(monkeypatch):
    monkeypatch.setattr(settings, "POST_MATCH_SETTLE_SECONDS", 600)
    fixture = {
        "date": "2026-06-25T10:00:00+00:00",
        "status": {"short": "FT"},
    }
    now = datetime(2026, 6, 25, 12, 20, tzinfo=timezone.utc)

    assert _settle_elapsed(None, fixture=fixture, now=now)


def test_important_events_are_deduplicated_for_penalty_goals():
    data = _sample_match_data()
    data["events"].append(
        {
            "elapsed": 88,
            "extra": None,
            "team": "Home FC",
            "player": "Late Winner",
            "assist": "",
            "type": "Goal",
            "detail": "Penalty",
        }
    )

    facts = extract_match_facts(data)

    unique_keys = {
        (event["elapsed"], event["team"], event["player"], event["type"], event["detail"])
        for event in facts.important_events
    }
    assert len(unique_keys) == len(facts.important_events)


def test_watcher_sleep_waits_until_prematch_lead_for_upcoming_fixture(monkeypatch):
    monkeypatch.setattr(settings, "POST_MATCH_PREMATCH_LEAD_SECONDS", 600)
    fixture = {
        "date": "2026-06-25T15:00:00+00:00",
        "status": {"short": "NS"},
    }
    now = datetime(2026, 6, 25, 10, 0, tzinfo=timezone.utc)

    assert _sleep_seconds_for_fixture(fixture, now=now) == 17400


def test_watcher_sleep_uses_live_match_checkpoints(monkeypatch):
    monkeypatch.setattr(settings, "POST_MATCH_LIVE_EARLY_CHECK_MINUTE", 45)
    monkeypatch.setattr(settings, "POST_MATCH_LIVE_LATE_CHECK_MINUTE", 80)
    monkeypatch.setattr(settings, "POST_MATCH_LIVE_FINAL_POLL_SECONDS", 300)
    early_live = {
        "date": "2026-06-25T10:00:00+00:00",
        "status": {"short": "1H", "elapsed": 10},
    }
    late_live = {
        "date": "2026-06-25T10:00:00+00:00",
        "status": {"short": "2H", "elapsed": 85},
    }
    now = datetime(2026, 6, 25, 10, 10, tzinfo=timezone.utc)

    assert _sleep_seconds_for_fixture(early_live, now=now) == 2100
    assert _sleep_seconds_for_fixture(late_live, now=now) == 300


def test_watcher_sleep_waits_only_remaining_settle_time_for_finished_fixture(monkeypatch):
    monkeypatch.setattr(settings, "POST_MATCH_SETTLE_SECONDS", 600)
    fixture = {
        "date": "2026-06-25T10:00:00+00:00",
        "status": {"short": "FT"},
    }
    now = datetime(2026, 6, 25, 12, 5, tzinfo=timezone.utc)

    assert _sleep_seconds_for_fixture(fixture, now=now) == 300
