"""Post-match video runner.

Scans configured API-Football fixtures, waits for final status + stat settling,
then generates one single-story video per finished match.
"""
from __future__ import annotations

import json
import logging
import subprocess
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from threading import Event
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from clients.api_football import ApiFootballClient
from clients.gdrive import sync_storage_to_drive
from config import settings
from core.database import (
    create_match_video_record,
    get_available_clips,
    get_match_video,
    mark_video_clips_used,
    update_match_video,
)
from process.match_facts import extract_match_facts, is_finished_fixture
from process.match_script_gen import (
    build_match_metadata,
    build_match_news_item,
    combine_match_script_parts,
    generate_match_script_parts,
)
from process.video_maker import create_multi_story_video
from process.voiceover import generate_voiceover
from publish.youtube import upload_video

logger = logging.getLogger(__name__)

_LIVE_STATUSES = {"1H", "HT", "2H", "ET", "BT", "P", "SUSP", "INT", "LIVE"}
_NOT_STARTED_STATUSES = {"NS", "TBD"}
_RECENT_MATCH_LOOKBACK_HOURS = 6
_POST_MATCH_GROUP_1_LABELS = {"OPENING HOOK", "MATCH RESULT", "FIRST HALF", "SECOND HALF"}


def _debug_enabled() -> bool:
    return bool(getattr(settings, "POST_MATCH_VERBOSE_LOGS", False))


def _debug_dir(fixture_id: int | str | None = None) -> Path:
    base = Path(getattr(settings, "POST_MATCH_DEBUG_DIR", settings.TEMP_DIR / "post_match_debug"))
    if fixture_id is not None:
        base = base / str(fixture_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _debug_slug(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"-", "_"} else "_" for ch in value.strip())
    return safe[:120] or "artifact"


def _write_debug_artifact(fixture_id: int | str | None, name: str, payload) -> Path | None:
    if not _debug_enabled():
        return None
    path = _debug_dir(fixture_id) / f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')}_{_debug_slug(name)}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    logger.info("Post-match debug artifact saved: %s", path)
    return path


def _api() -> ApiFootballClient:
    return ApiFootballClient()


def _timezone() -> ZoneInfo:
    try:
        return ZoneInfo(settings.POST_MATCH_TIMEZONE)
    except ZoneInfoNotFoundError:
        logger.warning("Invalid POST_MATCH_TIMEZONE=%r, using UTC", settings.POST_MATCH_TIMEZONE)
        return ZoneInfo("UTC")


def _scan_dates() -> list[str]:
    today = datetime.now(_timezone()).date()
    start = today - timedelta(days=max(settings.POST_MATCH_LOOKBACK_DAYS, 0))
    end = today + timedelta(days=max(settings.POST_MATCH_LOOKAHEAD_DAYS, 0))
    days = (end - start).days
    return [(start + timedelta(days=i)).isoformat() for i in range(days + 1)]


def _watcher_scan_dates(now: datetime | None = None) -> list[str]:
    current = (now or datetime.now(_timezone())).astimezone(_timezone())
    start = (current - timedelta(hours=_RECENT_MATCH_LOOKBACK_HOURS)).date()
    end = (current + timedelta(hours=max(settings.POST_MATCH_LOOKAHEAD_HOURS, 1))).date()
    days = (end - start).days
    return [(start + timedelta(days=i)).isoformat() for i in range(days + 1)]


def _fixture_summary(fixture: dict) -> tuple[int, str, str, str, str]:
    fixture_id = int(fixture.get("id") or 0)
    league = fixture.get("league") or {}
    teams = fixture.get("teams") or {}
    home = (teams.get("home") or {}).get("name") or ""
    away = (teams.get("away") or {}).get("name") or ""
    return fixture_id, fixture.get("date") or "", league.get("name") or "", home, away


def _fixture_datetime(fixture: dict) -> datetime | None:
    return _parse_iso_datetime(fixture.get("date"))


def _fixture_status(fixture: dict) -> str:
    return str((fixture.get("status") or {}).get("short") or "").upper()


def _fixture_elapsed(fixture: dict) -> int | None:
    elapsed = (fixture.get("status") or {}).get("elapsed")
    return elapsed if isinstance(elapsed, int) else None


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _estimated_finished_at(fixture: dict) -> datetime | None:
    kickoff = _parse_iso_datetime(fixture.get("date"))
    if kickoff is None:
        return None
    status_short = str((fixture.get("status") or {}).get("short") or "").upper()
    # Use a conservative baseline so restarted workers do not add an extra full settle window.
    baseline_minutes = 165 if status_short in {"AET", "PEN"} else 120
    return kickoff + timedelta(minutes=baseline_minutes)


def _finished_detected_timestamp(fixture: dict, now: datetime | None = None) -> str:
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    estimated_finished_at = _estimated_finished_at(fixture)
    if estimated_finished_at is None:
        return now_utc.isoformat()
    return min(now_utc, estimated_finished_at).isoformat()


def _settle_elapsed(record, fixture: dict | None = None, now: datetime | None = None) -> bool:
    raw = record["finished_detected_at"] if record else None
    if raw:
        detected_at = _parse_iso_datetime(raw)
    else:
        detected_at = _estimated_finished_at(fixture or {})
    if detected_at is None:
        return False
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    elapsed = now_utc - detected_at
    return elapsed.total_seconds() >= settings.POST_MATCH_SETTLE_SECONDS


def _sleep_seconds_for_fixture(fixture: dict, now: datetime | None = None) -> int:
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    status = _fixture_status(fixture)
    kickoff = _fixture_datetime(fixture)

    if is_finished_fixture(fixture):
        estimated_finished_at = _estimated_finished_at(fixture)
        if estimated_finished_at is None:
            return max(60, settings.POST_MATCH_LIVE_FINAL_POLL_SECONDS)
        settle_until = estimated_finished_at + timedelta(seconds=settings.POST_MATCH_SETTLE_SECONDS)
        return max(0, int((settle_until - now_utc).total_seconds()))

    if status in _LIVE_STATUSES:
        elapsed = _fixture_elapsed(fixture)
        if elapsed is None:
            return max(60, settings.POST_MATCH_LIVE_FINAL_POLL_SECONDS)
        if elapsed < settings.POST_MATCH_LIVE_EARLY_CHECK_MINUTE:
            return max(60, (settings.POST_MATCH_LIVE_EARLY_CHECK_MINUTE - elapsed) * 60)
        if elapsed < settings.POST_MATCH_LIVE_LATE_CHECK_MINUTE:
            return max(60, (settings.POST_MATCH_LIVE_LATE_CHECK_MINUTE - elapsed) * 60)
        return max(60, settings.POST_MATCH_LIVE_FINAL_POLL_SECONDS)

    if kickoff is None:
        return max(300, settings.POST_MATCH_LIVE_FINAL_POLL_SECONDS)

    seconds_until_prematch_check = int(
        (kickoff - timedelta(seconds=settings.POST_MATCH_PREMATCH_LEAD_SECONDS) - now_utc).total_seconds()
    )
    if status in _NOT_STARTED_STATUSES and seconds_until_prematch_check > 0:
        return seconds_until_prematch_check
    return max(60, settings.POST_MATCH_LIVE_FINAL_POLL_SECONDS)


def _metadata_sidecar_path(video_output: Path) -> Path:
    return video_output.with_suffix(".metadata.json")


def _save_video_metadata(video_output: Path, metadata) -> Path:
    metadata_path = _metadata_sidecar_path(video_output)
    payload = {
        "title": metadata.title,
        "description": metadata.description,
        "tags": metadata.tags,
        "category_id": metadata.category_id,
        "privacy_status": metadata.privacy_status,
        "publish_at": metadata.publish_at,
    }
    metadata_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
    logger.info("Saved post-match upload metadata: %s", metadata_path)
    return metadata_path


def _part_news_item(base_item, script, index: int, total: int):
    label = script.panel_label.replace("_", " ").title() if script.panel_label else f"Part {index}"
    headline = f"{base_item.headline} - {label}"
    return type(base_item)(
        id=script.news_id,
        headline=headline,
        body=script.text,
        url=base_item.url,
        source=base_item.source,
        source_type=base_item.source_type,
        timestamp=base_item.timestamp,
        raw={"fixture_part": index, "fixture_parts_total": total, "section": script.panel_label},
    )


def _split_post_match_story_groups(stories: list[tuple]) -> list[list[tuple]]:
    group_1 = [story for story in stories if story[0].panel_label in _POST_MATCH_GROUP_1_LABELS]
    group_2 = [story for story in stories if story[0].panel_label not in _POST_MATCH_GROUP_1_LABELS]
    return [group for group in (group_1, group_2) if group]


def _ffmpeg_bin() -> str:
    return getattr(settings, "LIVESTREAM_FFMPEG_BIN", "ffmpeg") or "ffmpeg"


def _concat_rendered_groups(group_paths: list[Path], output_name: str) -> Path:
    if not group_paths:
        raise ValueError("No rendered post-match groups to concatenate")
    if len(group_paths) == 1:
        output_path = settings.VIDEOS_DIR / f"{output_name}.mp4"
        if group_paths[0] != output_path:
            group_paths[0].replace(output_path)
        return output_path

    output_path = settings.VIDEOS_DIR / f"{output_name}.mp4"
    concat_file = settings.TEMP_DIR / f"{output_name}_concat.txt"
    concat_file.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    for path in group_paths:
        safe_path = str(path.resolve()).replace("'", "'\\''")
        lines.append(f"file '{safe_path}'")
    concat_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    cmd = [
        _ffmpeg_bin(),
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_file),
        "-c",
        "copy",
        str(output_path),
    ]
    logger.info("Concatenating %d post-match group video(s) into %s", len(group_paths), output_path.name)
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        logger.warning("Stream-copy concat failed, retrying with re-encode: %s", exc.stderr[-1000:])
        cmd = [
            _ffmpeg_bin(),
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_file),
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "18",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output_path),
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    finally:
        concat_file.unlink(missing_ok=True)

    for path in group_paths:
        if path != output_path:
            path.unlink(missing_ok=True)
    return output_path


def _render_post_match_groups(stories: list[tuple], output_name: str) -> Path:
    groups = _split_post_match_story_groups(stories)
    if len(groups) <= 1:
        return create_multi_story_video(stories, output_name=output_name)

    group_paths: list[Path] = []
    try:
        for index, group in enumerate(groups, start=1):
            group_output_name = f"{output_name}_group_{index}"
            logger.info(
                "Rendering post-match group %d/%d with %d section(s)",
                index,
                len(groups),
                len(group),
            )
            group_paths.append(
                create_multi_story_video(
                    group,
                    output_name=group_output_name,
                    include_intro=(index == 1),
                    include_outro=(index == len(groups)),
                )
            )
        return _concat_rendered_groups(group_paths, output_name)
    except Exception:
        for path in group_paths:
            path.unlink(missing_ok=True)
        raise


def _generate_fixture_video(fixture_id: int) -> None:
    logger.info("Post-match video generation started for fixture %s", fixture_id)
    _write_debug_artifact(fixture_id, "step_00_generation_started", {"fixture_id": fixture_id})
    update_match_video(fixture_id, "generating")
    vo_path: Path | None = None
    vo_paths: list[Path] = []
    video_output: Path | None = None
    metadata_path: Path | None = None

    try:
        logger.info("Post-match step fixture %s: fetching complete API-Football match payload", fixture_id)
        data = _api().live_match(fixture_id)
        _write_debug_artifact(fixture_id, "step_01_api_football_live_match_response", data)
        logger.info("Post-match step fixture %s: extracting deterministic match facts", fixture_id)
        facts = extract_match_facts(data)
        _write_debug_artifact(fixture_id, "step_02_extracted_match_facts", facts.to_dict())
        logger.info("Post-match step fixture %s: loading available stock clips", fixture_id)
        clips = get_available_clips()
        _write_debug_artifact(fixture_id, "step_03_available_clips", {"count": len(clips), "clips": clips})
        logger.info("Post-match step fixture %s: generating section-wise LLM script", fixture_id)
        script_parts = generate_match_script_parts(facts, clips=clips)
        script = combine_match_script_parts(facts, script_parts)
        _write_debug_artifact(
            fixture_id,
            "step_04_final_script",
            {
                "text": script.text,
                "word_count": script.word_count,
                "estimated_duration_seconds": script.estimated_duration_seconds,
                "selected_clip_ids": script.selected_clip_ids,
                "display_headline": script.display_headline,
                "display_points": script.display_points,
                "parts": [
                    {
                        "news_id": part.news_id,
                        "panel_label": part.panel_label,
                        "text": part.text,
                        "word_count": part.word_count,
                        "estimated_duration_seconds": part.estimated_duration_seconds,
                        "selected_clip_ids": part.selected_clip_ids,
                    }
                    for part in script_parts
                ],
            },
        )
        item = build_match_news_item(facts)
        _write_debug_artifact(fixture_id, "step_05_news_item", item.__dict__)

        logger.info("Post-match step fixture %s: generating %d section voiceover(s)", fixture_id, len(script_parts))
        stories = []
        for index, part in enumerate(script_parts, start=1):
            vo_path = generate_voiceover(part, "english")
            vo_paths.append(vo_path)
            stories.append((part, _part_news_item(item, part, index, len(script_parts)), vo_path))
        _write_debug_artifact(
            fixture_id,
            "step_06_voiceovers",
            [{"news_id": part.news_id, "path": str(path)} for part, _, path in stories],
        )
        output_name = f"match_{fixture_id}_{date.today().isoformat()}"
        logger.info("Post-match step fixture %s: rendering final video in grouped sections", fixture_id)
        video_output = _render_post_match_groups(stories, output_name)
        _write_debug_artifact(fixture_id, "step_07_video_rendered", {"path": str(video_output)})
        logger.info("Post-match step fixture %s: building YouTube metadata", fixture_id)
        metadata = build_match_metadata(facts)
        _write_debug_artifact(fixture_id, "step_08_youtube_metadata", metadata.__dict__)
        metadata_path = _save_video_metadata(video_output, metadata)

        youtube_id = None
        final_path = str(video_output)
        if settings.POST_MATCH_UPLOAD_ENABLED:
            logger.info("Post-match step fixture %s: uploading video to YouTube", fixture_id)
            youtube_id = upload_video(video_output, None, metadata)
            final_path = f"youtube:{youtube_id}"
            _write_debug_artifact(fixture_id, "step_09_youtube_upload_response", {"youtube_id": youtube_id})
            logger.info("Post-match YouTube upload complete for fixture %s: %s", fixture_id, youtube_id)

        used_clip_ids = sorted({clip_id for part in script_parts for clip_id in part.selected_clip_ids})
        logger.info("Post-match step fixture %s: marking %d selected clip(s) as used", fixture_id, len(used_clip_ids))
        mark_video_clips_used(used_clip_ids)
        update_match_video(
            fixture_id,
            "done",
            video_path=final_path,
            youtube_id=youtube_id,
            facts_json=json.dumps(facts.to_dict(), ensure_ascii=True),
            script_text=script.text,
        )
        _write_debug_artifact(
            fixture_id,
            "step_10_db_done_record",
            {"status": "done", "video_path": final_path, "youtube_id": youtube_id, "used_clip_ids": used_clip_ids},
        )

        if settings.POST_MATCH_UPLOAD_ENABLED:
            try:
                sync_storage_to_drive(delete_local=True)
            except Exception as exc:
                logger.warning("Post-match Drive sync failed after upload for fixture %s: %s", fixture_id, exc)

        if settings.POST_MATCH_UPLOAD_ENABLED:
            video_output.unlink(missing_ok=True)
            metadata_path.unlink(missing_ok=True)
        for path in vo_paths:
            path.unlink(missing_ok=True)

        logger.info("Post-match video done for fixture %s", fixture_id)
    except Exception as exc:
        _write_debug_artifact(fixture_id, "step_failed", {"error_type": type(exc).__name__, "error": str(exc)})
        update_match_video(fixture_id, "failed", error=f"{type(exc).__name__}: {exc}")
        logger.error("Post-match video failed for fixture %s: %s", fixture_id, exc)
        if metadata_path:
            metadata_path.unlink(missing_ok=True)
        if video_output:
            video_output.unlink(missing_ok=True)
        for path in vo_paths:
            path.unlink(missing_ok=True)


def _process_finished_fixture(fixture: dict, force: bool = False) -> bool:
    if not is_finished_fixture(fixture):
        return False

    fixture_id, fixture_date, league_name, home_team, away_team = _fixture_summary(fixture)
    if not fixture_id:
        return False

    record = get_match_video(fixture_id)
    if record and record["status"] == "done" and not force:
        return False
    if record and record["status"] == "generating" and not force:
        return False

    if not record:
        create_match_video_record(
            fixture_id,
            fixture_date,
            league_name,
            home_team,
            away_team,
            finished_detected_at=_finished_detected_timestamp(fixture),
        )
        record = get_match_video(fixture_id)
        logger.info("Finished fixture detected, waiting for stats to settle: %s %s vs %s", fixture_id, home_team, away_team)

    if not force and not _settle_elapsed(record, fixture=fixture):
        logger.info("Fixture %s finished but still inside settle window; skipping this pass", fixture_id)
        return False

    _generate_fixture_video(fixture_id)
    return True


def generate_post_match_video_for_fixture(fixture_id: int, force: bool = False) -> bool:
    """Generate a post-match video for one exact fixture ID.

    Returns True when generation was started and completed, False when skipped.
    """
    client = _api()
    fixture = client.fixture(fixture_id)
    if not is_finished_fixture(fixture):
        raise ValueError(f"Fixture {fixture_id} is not finished yet")

    normalized_fixture_id, _, _, _, _ = _fixture_summary(fixture)
    if not normalized_fixture_id:
        raise ValueError("Fixture payload did not include a valid fixture ID")
    return _process_finished_fixture(fixture, force=force)


def run_post_match_videos(force: bool = False, bypass_enabled: bool = False) -> None:
    """Generate videos for finished configured fixtures, one at a time."""
    if not settings.POST_MATCH_ENABLED and not bypass_enabled:
        logger.info("Post-match videos disabled; set POST_MATCH_ENABLED=true to enable.")
        return

    logger.info(
        "=== Post-match Runner START (league=%s season=%s tz=%s) ===",
        settings.POST_MATCH_TARGET_LEAGUE_ID,
        settings.POST_MATCH_TARGET_SEASON,
        settings.POST_MATCH_TIMEZONE,
    )
    client = _api()
    generated = 0
    for match_date in _scan_dates():
        try:
            fixtures = client.fixtures_for_date(
                match_date=match_date,
                league=settings.POST_MATCH_TARGET_LEAGUE_ID,
                season=settings.POST_MATCH_TARGET_SEASON,
                timezone=settings.POST_MATCH_TIMEZONE,
            )
            _write_debug_artifact(
                "runner",
                f"fixtures_for_date_{match_date}",
                {"date": match_date, "count": len(fixtures), "fixtures": fixtures},
            )
        except Exception as exc:
            logger.warning("Could not fetch fixtures for %s: %s", match_date, exc)
            continue

        for fixture in fixtures:
            if _process_finished_fixture(fixture, force=force):
                generated += 1

    logger.info("=== Post-match Runner DONE (generated=%d) ===", generated)


def _fetch_watcher_fixtures(client: ApiFootballClient) -> list[dict]:
    now = datetime.now(timezone.utc)
    lower_bound = now - timedelta(hours=_RECENT_MATCH_LOOKBACK_HOURS)
    upper_bound = now + timedelta(hours=max(settings.POST_MATCH_LOOKAHEAD_HOURS, 1))
    fixtures: list[dict] = []
    seen_ids: set[int] = set()

    for match_date in _watcher_scan_dates(now):
        try:
            rows = client.fixtures_for_date(
                match_date=match_date,
                league=settings.POST_MATCH_TARGET_LEAGUE_ID,
                season=settings.POST_MATCH_TARGET_SEASON,
                timezone=settings.POST_MATCH_TIMEZONE,
            )
            _write_debug_artifact(
                "watcher",
                f"fixtures_for_date_{match_date}",
                {"date": match_date, "count": len(rows), "fixtures": rows},
            )
        except Exception as exc:
            logger.warning("Could not fetch post-match watcher fixtures for %s: %s", match_date, exc)
            continue

        for fixture in rows:
            fixture_id, *_ = _fixture_summary(fixture)
            fixture_time = _fixture_datetime(fixture)
            if not fixture_id or fixture_id in seen_ids or fixture_time is None:
                continue
            if lower_bound <= fixture_time <= upper_bound or is_finished_fixture(fixture) or _fixture_status(fixture) in _LIVE_STATUSES:
                fixtures.append(fixture)
                seen_ids.add(fixture_id)

    return sorted(fixtures, key=lambda f: _fixture_datetime(f) or datetime.max.replace(tzinfo=timezone.utc))


def _next_unprocessed_fixture(fixtures: list[dict]) -> dict | None:
    for fixture in fixtures:
        fixture_id, *_ = _fixture_summary(fixture)
        record = get_match_video(fixture_id)
        if record and record["status"] in {"generating", "done"}:
            continue
        return fixture
    return None


def run_post_match_watcher(stop_event: Event | None = None) -> None:
    """Low-API watcher that sleeps until useful match checkpoints."""
    if not settings.POST_MATCH_ENABLED:
        logger.info("Post-match watcher disabled; set POST_MATCH_ENABLED=true to enable.")
        return

    logger.info(
        "Post-match watcher started (league=%s season=%s window=%sh)",
        settings.POST_MATCH_TARGET_LEAGUE_ID,
        settings.POST_MATCH_TARGET_SEASON,
        settings.POST_MATCH_LOOKAHEAD_HOURS,
    )
    client = _api()
    stop_event = stop_event or Event()
    while not stop_event.is_set():
        try:
            fixtures = _fetch_watcher_fixtures(client)
            generated = 0
            for fixture in fixtures:
                if _process_finished_fixture(fixture):
                    generated += 1

            next_fixture = _next_unprocessed_fixture(fixtures)
            if next_fixture is None:
                sleep_seconds = max(300, settings.POST_MATCH_NO_FIXTURE_SLEEP_SECONDS)
                logger.info("No post-match fixtures in watcher window; sleeping for %ss", sleep_seconds)
            else:
                fixture_id, fixture_date, _, home_team, away_team = _fixture_summary(next_fixture)
                sleep_seconds = max(60, _sleep_seconds_for_fixture(next_fixture))
                logger.info(
                    "Next post-match watcher check in %ss for fixture %s (%s vs %s, %s, status=%s)",
                    sleep_seconds,
                    fixture_id,
                    home_team,
                    away_team,
                    fixture_date,
                    _fixture_status(next_fixture),
                )

            if generated:
                sleep_seconds = min(sleep_seconds, max(60, settings.POST_MATCH_LIVE_FINAL_POLL_SECONDS))
            stop_event.wait(sleep_seconds)
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            logger.error("Post-match watcher loop failed: %s", exc)
            stop_event.wait(max(300, settings.POST_MATCH_LIVE_FINAL_POLL_SECONDS))

    logger.info("Post-match watcher stopped.")
