from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from config import settings
from publish.youtube import _get_youtube_client

logger = logging.getLogger(__name__)


class LiveStreamError(RuntimeError):
    pass


@dataclass(slots=True)
class BroadcastRef:
    broadcast_id: str
    bound_stream_id: str | None
    life_cycle_status: str
    stream_status: str | None
    title: str


def _youtube():
    return _get_youtube_client()


def _iso8601(value: str | datetime | None) -> str:
    now = datetime.now(timezone.utc)
    minimum_start = now + timedelta(minutes=2)
    if isinstance(value, datetime):
        dt = value.astimezone(timezone.utc)
        if dt < minimum_start:
            dt = minimum_start
        return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    if isinstance(value, str) and value.strip():
        try:
            dt = datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            return minimum_start.replace(microsecond=0).isoformat().replace("+00:00", "Z")
        if dt < minimum_start:
            dt = minimum_start
        return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")
    return minimum_start.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _normalise_privacy(value: str) -> str:
    privacy = (value or settings.YOUTUBE_LIVE_PRIVACY_STATUS).strip().lower()
    if privacy not in {"private", "public", "unlisted"}:
        raise LiveStreamError(f"Invalid YOUTUBE_LIVE_PRIVACY_STATUS: {value!r}")
    return privacy


def _normalise_tags(tags: list[str] | tuple[str, ...] | None) -> list[str]:
    if not tags:
        return []
    cleaned: list[str] = []
    seen: set[str] = set()
    for raw in tags:
        tag = str(raw or "").strip()
        if not tag:
            continue
        key = tag.casefold()
        if key in seen:
            continue
        seen.add(key)
        cleaned.append(tag[:30])
    return cleaned[:15]


def get_stream(stream_id: str | None = None) -> dict[str, Any]:
    target_stream_id = (stream_id or settings.YOUTUBE_LIVE_STREAM_ID).strip()
    if not target_stream_id:
        raise LiveStreamError("YOUTUBE_LIVE_STREAM_ID is not configured")
    response = (
        _youtube()
        .liveStreams()
        .list(part="id,snippet,cdn,status", id=target_stream_id)
        .execute()
    )
    items = response.get("items") or []
    if not items:
        raise LiveStreamError(f"YouTube live stream not found: {target_stream_id}")
    return items[0]


def get_broadcast(broadcast_id: str) -> BroadcastRef:
    response = (
        _youtube()
        .liveBroadcasts()
        .list(part="id,snippet,status,contentDetails", id=broadcast_id)
        .execute()
    )
    items = response.get("items") or []
    if not items:
        raise LiveStreamError(f"YouTube broadcast not found: {broadcast_id}")
    item = items[0]
    return BroadcastRef(
        broadcast_id=item["id"],
        bound_stream_id=(item.get("contentDetails") or {}).get("boundStreamId"),
        life_cycle_status=((item.get("status") or {}).get("lifeCycleStatus") or "").lower(),
        stream_status=((item.get("status") or {}).get("streamStatus") or "").lower() or None,
        title=((item.get("snippet") or {}).get("title") or "").strip(),
    )


def find_reusable_broadcast(
    *,
    title: str,
    start_time: str | datetime | None,
    include_completed: bool = False,
) -> BroadcastRef | None:
    scheduled = _iso8601(start_time)
    try:
        scheduled_dt = datetime.fromisoformat(scheduled.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError as exc:
        raise LiveStreamError(f"Invalid scheduled start time: {start_time!r}") from exc

    response = (
        _youtube()
        .liveBroadcasts()
        .list(
            part="id,snippet,status,contentDetails",
            broadcastStatus="all",
            broadcastType="event",
            maxResults=25,
        )
        .execute()
    )
    for item in response.get("items") or []:
        item_title = ((item.get("snippet") or {}).get("title") or "").strip()
        if item_title != title:
            continue
        life_cycle_status = ((item.get("status") or {}).get("lifeCycleStatus") or "").lower()
        if life_cycle_status == "complete" and not include_completed:
            continue
        raw_start = (item.get("snippet") or {}).get("scheduledStartTime") or ""
        try:
            item_start = datetime.fromisoformat(raw_start.replace("Z", "+00:00")).astimezone(timezone.utc)
        except ValueError:
            continue
        if abs((item_start - scheduled_dt).total_seconds()) > timedelta(hours=6).total_seconds():
            continue
        return BroadcastRef(
            broadcast_id=item["id"],
            bound_stream_id=(item.get("contentDetails") or {}).get("boundStreamId"),
            life_cycle_status=life_cycle_status,
            stream_status=((item.get("status") or {}).get("streamStatus") or "").lower() or None,
            title=item_title,
        )
    return None


def create_broadcast(
    *,
    title: str,
    description: str,
    start_time: str | datetime | None,
    privacy_status: str | None = None,
    category_id: str | None = None,
    tags: list[str] | tuple[str, ...] | None = None,
) -> BroadcastRef:
    body = {
        "snippet": {
            "title": title,
            "description": description,
            "scheduledStartTime": _iso8601(start_time),
            "categoryId": category_id or settings.YOUTUBE_LIVE_CATEGORY_ID,
            "tags": _normalise_tags(tags),
        },
        "status": {
            "privacyStatus": _normalise_privacy(privacy_status or settings.YOUTUBE_LIVE_PRIVACY_STATUS),
            "selfDeclaredMadeForKids": False,
        },
        "contentDetails": {
            "enableAutoStart": False,
            "enableAutoStop": False,
            "enableClosedCaptions": False,
            "recordFromStart": True,
            "startWithSlate": False,
            "monitorStream": {"enableMonitorStream": False},
        },
    }
    item = (
        _youtube()
        .liveBroadcasts()
        .insert(part="snippet,status,contentDetails", body=body)
        .execute()
    )
    logger.info("YouTube broadcast created: %s | %s", item["id"], title)
    return BroadcastRef(
        broadcast_id=item["id"],
        bound_stream_id=(item.get("contentDetails") or {}).get("boundStreamId"),
        life_cycle_status=((item.get("status") or {}).get("lifeCycleStatus") or "").lower(),
        stream_status=((item.get("status") or {}).get("streamStatus") or "").lower() or None,
        title=title,
    )


def bind_broadcast_to_stream(broadcast_id: str, stream_id: str | None = None) -> BroadcastRef:
    target_stream_id = (stream_id or settings.YOUTUBE_LIVE_STREAM_ID).strip()
    if not target_stream_id:
        raise LiveStreamError("YOUTUBE_LIVE_STREAM_ID is not configured")
    item = (
        _youtube()
        .liveBroadcasts()
        .bind(part="id,contentDetails,status,snippet", id=broadcast_id, streamId=target_stream_id)
        .execute()
    )
    logger.info("YouTube broadcast %s bound to stream %s", broadcast_id, target_stream_id)
    return BroadcastRef(
        broadcast_id=item["id"],
        bound_stream_id=(item.get("contentDetails") or {}).get("boundStreamId"),
        life_cycle_status=((item.get("status") or {}).get("lifeCycleStatus") or "").lower(),
        stream_status=((item.get("status") or {}).get("streamStatus") or "").lower() or None,
        title=((item.get("snippet") or {}).get("title") or "").strip(),
    )


def transition_broadcast(broadcast_id: str, status: str) -> BroadcastRef:
    target = status.strip().lower()
    if target not in {"testing", "live", "complete"}:
        raise LiveStreamError(f"Unsupported broadcast transition: {status!r}")
    item = (
        _youtube()
        .liveBroadcasts()
        .transition(broadcastStatus=target, id=broadcast_id, part="id,status,contentDetails,snippet")
        .execute()
    )
    logger.info("YouTube broadcast %s transitioned to %s", broadcast_id, target)
    return BroadcastRef(
        broadcast_id=item["id"],
        bound_stream_id=(item.get("contentDetails") or {}).get("boundStreamId"),
        life_cycle_status=((item.get("status") or {}).get("lifeCycleStatus") or "").lower(),
        stream_status=((item.get("status") or {}).get("streamStatus") or "").lower() or None,
        title=((item.get("snippet") or {}).get("title") or "").strip(),
    )


def delete_broadcast(broadcast_id: str) -> None:
    _youtube().liveBroadcasts().delete(id=broadcast_id).execute()
    logger.info("YouTube broadcast deleted: %s", broadcast_id)


def stream_health(stream_id: str | None = None) -> str:
    stream = get_stream(stream_id)
    status = ((stream.get("status") or {}).get("streamStatus") or "").lower()
    return status or "unknown"
