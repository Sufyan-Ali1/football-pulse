"""
Sync video clip metadata from a JSON file into the video_clips table.

Examples:
    python scripts/sync_videos.py
    python scripts/sync_videos.py --json clips_ai.json
    python scripts/sync_videos.py --json /app/clips_ai.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.database import _conn, init_db


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Insert or update video clip rows from a JSON file."
    )
    parser.add_argument(
        "--json",
        default="clips.json",
        help="Path to the input JSON file. Defaults to clips.json",
    )
    return parser.parse_args()


def _load_clips(json_path: Path) -> list[dict[str, Any]]:
    with json_path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    if not isinstance(payload, list):
        raise ValueError("Input JSON must be an array of clip objects.")
    return payload


def _normalize_keywords(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return json.dumps(value, ensure_ascii=True)
    raise ValueError("keywords must be a string, array, or null.")


def _normalize_downloaded_at(value: Any) -> str:
    if isinstance(value, str) and value.strip():
        return value
    return datetime.now(timezone.utc).isoformat()


def _clip_id(file_path: str) -> str:
    return hashlib.md5(file_path.encode()).hexdigest()


def _validate_clip(raw_clip: dict[str, Any], index: int) -> dict[str, Any]:
    if not isinstance(raw_clip, dict):
        raise ValueError(f"Clip at index {index} must be an object.")

    file_path = str(raw_clip.get("file_path", "")).strip()
    description = str(raw_clip.get("description", "")).strip()

    if not file_path:
        raise ValueError(f"Clip at index {index} is missing file_path.")
    if not description:
        raise ValueError(f"Clip at index {index} is missing description.")

    return {
        "id": _clip_id(file_path),
        "file_path": file_path,
        "description": description,
        "keywords": _normalize_keywords(raw_clip.get("keywords")),
        "source": str(raw_clip.get("source", "manual") or "manual"),
        "source_url": raw_clip.get("source_url"),
        "duration": raw_clip.get("duration"),
        "width": raw_clip.get("width"),
        "height": raw_clip.get("height"),
        "downloaded_at": _normalize_downloaded_at(raw_clip.get("downloaded_at")),
        "is_used": int(raw_clip.get("is_used", 0) or 0),
        "last_used_at": raw_clip.get("last_used_at"),
    }


def sync_clips(json_path: Path) -> tuple[int, int]:
    init_db()
    clips = _load_clips(json_path)
    inserted = 0
    updated = 0

    with _conn() as conn:
        for index, raw_clip in enumerate(clips):
            clip = _validate_clip(raw_clip, index)
            exists = conn.execute(
                "SELECT 1 FROM video_clips WHERE id = ?",
                (clip["id"],),
            ).fetchone()

            conn.execute(
                """
                INSERT INTO video_clips (
                    id, file_path, description, keywords, source, source_url,
                    duration, width, height, downloaded_at, is_used, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(id) DO UPDATE SET
                    file_path = excluded.file_path,
                    description = excluded.description,
                    keywords = excluded.keywords,
                    source = excluded.source,
                    source_url = excluded.source_url,
                    duration = excluded.duration,
                    width = excluded.width,
                    height = excluded.height,
                    downloaded_at = excluded.downloaded_at,
                    is_used = excluded.is_used,
                    last_used_at = excluded.last_used_at
                """,
                (
                    clip["id"],
                    clip["file_path"],
                    clip["description"],
                    clip["keywords"],
                    clip["source"],
                    clip["source_url"],
                    clip["duration"],
                    clip["width"],
                    clip["height"],
                    clip["downloaded_at"],
                    clip["is_used"],
                    clip["last_used_at"],
                ),
            )

            if exists:
                updated += 1
            else:
                inserted += 1

        conn.commit()

    return inserted, updated


def main() -> int:
    args = _parse_args()
    json_path = Path(args.json).resolve()

    if not json_path.exists():
        print(f"JSON file not found: {json_path}", file=sys.stderr)
        return 1

    try:
        inserted, updated = sync_clips(json_path)
    except Exception as exc:
        print(f"Sync failed: {exc}", file=sys.stderr)
        return 1

    print(
        f"Video sync complete. Inserted: {inserted}, Updated: {updated}, File: {json_path}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
