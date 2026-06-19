"""
Bulk clip indexer.

Scans a folder for .mp4 files, sends each to Groq Vision for a description
and keywords, then saves the result to the video_clips DB table.

Usage:
    python index_clips.py <folder>                 # index new clips in a specific folder
    python index_clips.py <folder> --reindex       # re-run vision on clips that failed (filename as description)
"""
import logging
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("index_clips")

from core.database import get_all_clips, update_video_clip_description
from process.clip_indexer import _load_clip_info
from process.clip_indexer import index_clip
from clients.groq_vision import describe_frame


def _looks_like_filename(desc: str) -> bool:
    """True if the description is just the Pexels filename (vision failed at index time)."""
    return desc.startswith("pexels_") or (len(desc) < 10 and "_" in desc)


def reindex_failed(folder: Path) -> None:
    """Re-run Groq Vision on clips whose description is just their filename."""
    all_clips = get_all_clips()
    failed = [c for c in all_clips if _looks_like_filename(c["description"])]

    print(f"\nRe-index failed clips")
    print(f"  Total in DB        : {len(all_clips)}")
    print(f"  Bad descriptions   : {len(failed)}")
    print()

    if not failed:
        print("Nothing to re-index — all clips have proper descriptions.")
        return

    ok = 0
    still_fail = 0
    for i, clip in enumerate(failed, 1):
        path = Path(clip["file_path"])
        print(f"  [{i}/{len(failed)}] {path.name}")

        if not path.exists():
            print(f"    -> file missing on disk, skipping")
            still_fail += 1
            continue

        try:
            frames, _ = _load_clip_info(path)
            if not frames:
                print(f"    -> frame extraction failed")
                still_fail += 1
                continue

            desc, kws = describe_frame(frames)
            if not desc or _looks_like_filename(desc):
                print(f"    -> vision returned empty/bad result, skipping")
                still_fail += 1
                continue

            update_video_clip_description(clip["file_path"], desc, kws)
            print(f"    -> {desc!r}")
            ok += 1

        except Exception as exc:
            logger.warning("Failed: %s — %s", path.name, exc)
            still_fail += 1

    print(f"\nDone — updated: {ok}  |  still failed: {still_fail}")


def index_new(folder: Path) -> None:
    """Index .mp4 files in folder that aren't in the DB yet."""
    mp4s = sorted(folder.rglob("*.mp4"))
    if not mp4s:
        print(f"No .mp4 files found in {folder}")
        return

    already_indexed = {r["file_path"] for r in get_all_clips()}
    pending = [p for p in mp4s if str(p) not in already_indexed]

    print(f"\nClip indexer")
    print(f"  Folder         : {folder}")
    print(f"  Total .mp4     : {len(mp4s)}")
    print(f"  Already in DB  : {len(already_indexed)}")
    print(f"  To index       : {len(pending)}\n")

    if not pending:
        print("Nothing to do — all clips already indexed.")
        return

    ok = 0
    fail = 0
    for i, path in enumerate(pending, 1):
        print(f"  [{i}/{len(pending)}] {path.name}")
        try:
            success = index_clip(video_path=path, source_url=None)
            if success:
                ok += 1
            else:
                fail += 1
                print(f"    -> skipped")
        except Exception as exc:
            fail += 1
            logger.warning("Failed: %s — %s", path.name, exc)

    print(f"\nDone — indexed: {ok}  |  failed/skipped: {fail}")


def main() -> None:
    reindex = "--reindex" in sys.argv
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print("Usage: python index_clips.py <folder> [--reindex]")
        sys.exit(1)

    folder = Path(args[0])

    if not folder.exists() and not reindex:
        print(f"Folder not found: {folder}")
        sys.exit(1)

    if reindex:
        reindex_failed(folder)
    else:
        index_new(folder)


if __name__ == "__main__":
    main()
