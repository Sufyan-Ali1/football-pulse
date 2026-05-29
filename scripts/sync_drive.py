"""
Sync local temp/ to Google Drive.

Usage:
    python scripts/sync_drive.py              # upload all, keep local copies
    python scripts/sync_drive.py --delete     # upload all, delete local after upload
    python scripts/sync_drive.py --dry-run    # print what would be uploaded, no action

Requires:
    - GDRIVE_REFRESH_TOKEN in .env
    - GOOGLE_DRIVE_FOLDER_ID in .env
"""
import sys
from pathlib import Path

# Allow running from project root: python scripts/sync_drive.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config import settings


def _dry_run():
    from clients.gdrive import _SYNC_MAP

    total = 0

    print(f"\n{'='*56}")
    print("  Google Drive Sync — DRY RUN (no uploads)")
    print(f"  Root folder ID: {settings.GDRIVE_FOLDER_ID or '(not set)'}")
    print(f"{'='*56}")

    for local_subpath, drive_path in _SYNC_MAP.items():
        local_dir = settings.TEMP_DIR / local_subpath.replace("/", "\\")
        if not local_dir.exists():
            print(f"\n  [{local_subpath}] — folder does not exist locally, skip")
            continue
        files = [f for f in local_dir.iterdir() if f.is_file()]
        drive_dest = "Drive/" + "/".join(drive_path)
        print(f"\n  [{local_subpath}] -> {drive_dest}  ({len(files)} file(s))")
        for f in sorted(files):
            size_mb = f.stat().st_size / (1024 * 1024)
            print(f"    {f.name}  ({size_mb:.1f} MB)")
            total += 1

    print(f"\n  Total: {total} file(s) would be uploaded")
    print(f"{'='*56}\n")


def main():
    delete_local = "--delete" in sys.argv
    dry_run      = "--dry-run" in sys.argv

    if dry_run:
        _dry_run()
        return

    from clients.gdrive import sync_storage_to_drive
    stats = sync_storage_to_drive(delete_local=delete_local)

    if stats["failed"] > 0:
        print(f"  WARNING: {stats['failed']} file(s) failed to upload — check logs above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
