"""
Import clip metadata from clips.json into the video_clips table.

Usage:
    venv\Scripts\python scripts\import_clips_json.py
    venv\Scripts\python scripts\import_clips_json.py C:\path\to\clips.json
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.database import clip_exists, get_all_clips, insert_video_clip


def _load_records(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [r for r in data if isinstance(r, dict)]
    if isinstance(data, dict):
        clips = data.get("clips", [])
        if isinstance(clips, list):
            return [r for r in clips if isinstance(r, dict)]
    raise ValueError("clips.json must contain a top-level list or {'clips': [...]} object")


def main() -> int:
    source_path = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "clips.json"
    if not source_path.exists():
        print(f"clips.json not found: {source_path}")
        return 1

    records = _load_records(source_path)
    before = len(get_all_clips())
    inserted = 0
    rejected = 0

    for idx, record in enumerate(records, start=1):
        file_path = str(record.get("file_path") or "").strip()
        description = str(record.get("description") or "").strip()
        if not file_path or not description:
            rejected += 1
            print(f"[reject {idx}] missing file_path or description")
            continue

        existed = clip_exists(file_path)
        insert_video_clip(
            file_path=file_path,
            description=description,
            keywords=str(record.get("keywords") or "").strip(),
            source=str(record.get("source") or "pexels").strip() or "pexels",
            source_url=record.get("source_url"),
            duration=record.get("duration"),
            width=record.get("width"),
            height=record.get("height"),
        )
        if not existed and clip_exists(file_path):
            inserted += 1

    final_count = len(get_all_clips())
    skipped = len(records) - inserted - rejected

    print("\nClip JSON import")
    print(f"  Source file : {source_path}")
    print(f"  Records     : {len(records)}")
    print(f"  Inserted    : {inserted}")
    print(f"  Skipped     : {skipped}")
    print(f"  Rejected    : {rejected}")
    print(f"  DB before   : {before}")
    print(f"  DB after    : {final_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
