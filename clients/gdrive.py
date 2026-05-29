"""
Google Drive client — upload storage/ files to Drive and optionally delete local copies.

Authentication: OAuth 2.0 (your Google account) via config/gdrive_client_secrets.json
                Token cached at config/gdrive_token.json after first browser login.
Root folder:    settings.GDRIVE_FOLDER_ID  (folder shared with your Google account)
"""
import io
import logging
from pathlib import Path

from config import settings

logger = logging.getLogger(__name__)

_SCOPES = ["https://www.googleapis.com/auth/drive"]

# Maps local dirs → Drive subfolder hierarchy
_SYNC_MAP: dict[str, list[str]] = {
    "videos/final": ["Videos", "Final"],
}


def _get_service():
    """Return an authenticated Drive v3 service object (OAuth 2.0).

    First call opens a browser login page and saves the token to
    config/gdrive_token.json. All subsequent calls use the saved token.
    """
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    if not settings.GDRIVE_REFRESH_TOKEN:
        raise RuntimeError("GDRIVE_REFRESH_TOKEN is not set in .env")
    if not settings.GOOGLE_CLIENT_ID or not settings.GOOGLE_CLIENT_SECRET:
        raise RuntimeError("GOOGLE_CLIENT_ID and GOOGLE_CLIENT_SECRET must be set in .env")
    creds = Credentials(
        token=None,
        refresh_token=settings.GDRIVE_REFRESH_TOKEN,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=settings.GOOGLE_CLIENT_ID,
        client_secret=settings.GOOGLE_CLIENT_SECRET,
        scopes=_SCOPES,
    )
    creds.refresh(Request())
    return build("drive", "v3", credentials=creds, cache_discovery=False)


def get_or_create_folder(service, name: str, parent_id: str) -> str:
    """Return the Drive folder ID for `name` under `parent_id`, creating it if absent."""
    query = (
        f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
        f"and '{parent_id}' in parents and trashed=false"
    )
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    if files:
        return files[0]["id"]

    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=meta, fields="id").execute()
    logger.info("Created Drive folder: %s (id=%s)", name, folder["id"])
    return folder["id"]


def _get_folder_id(service, name: str, parent_id: str) -> str | None:
    """Return the Drive folder ID for `name` under `parent_id`, or None if it doesn't exist."""
    query = (
        f"name='{name}' and mimeType='application/vnd.google-apps.folder' "
        f"and '{parent_id}' in parents and trashed=false"
    )
    files = service.files().list(q=query, fields="files(id)").execute().get("files", [])
    return files[0]["id"] if files else None



def sync_storage_to_drive(delete_local: bool = False) -> dict:
    """Sync all storage/ subfolders to Google Drive.

    Mirrors the folder structure under settings.GDRIVE_FOLDER_ID.
    Skips files already present on Drive.
    If delete_local=True, deletes each local file after a successful upload.

    Returns {"uploaded": N, "skipped": N, "failed": N}.
    """
    root_id = settings.GDRIVE_FOLDER_ID
    if not root_id:
        raise ValueError(
            "GOOGLE_DRIVE_FOLDER_ID is not set in .env. "
            "Add it with the folder ID the client shared with you."
        )

    service = _get_service()
    storage_root = settings.TEMP_DIR

    stats = {"uploaded": 0, "skipped": 0, "failed": 0}

    print(f"\n{'='*56}")
    print(f"  Google Drive Sync  |  root folder: {root_id}")
    print(f"  delete_local={delete_local}")
    print(f"{'='*56}")

    for local_subpath, drive_path in _SYNC_MAP.items():
        local_dir = storage_root / Path(*local_subpath.split("/"))
        if not local_dir.exists():
            print(f"\n  [GDrive] Skipping {local_subpath} — folder does not exist locally")
            continue

        files = [f for f in local_dir.iterdir() if f.is_file()]
        if not files:
            print(f"\n  [GDrive] {local_subpath} — no files to upload")
            continue

        # Resolve (or create) the matching Drive subfolder hierarchy
        folder_id = root_id
        for part in drive_path:
            folder_id = get_or_create_folder(service, part, folder_id)

        print(f"\n  [{local_subpath}]  {len(files)} file(s) → Drive/{'/'.join(drive_path)}")

        for f in sorted(files):
            # Re-use the already-built service — pass folder_id directly
            name = f.name
            size_mb = f.stat().st_size / (1024 * 1024)

            query = f"name='{name}' and '{folder_id}' in parents and trashed=false"
            existing = service.files().list(q=query, fields="files(id)").execute().get("files", [])
            if existing:
                print(f"    [GDrive] Skipped (already on Drive): {name}")
                stats["skipped"] += 1
                continue

            print(f"    [GDrive] Uploading {name} ({size_mb:.1f} MB) ...")
            try:
                from googleapiclient.http import MediaFileUpload
                media = MediaFileUpload(str(f), resumable=True)
                file_meta = {"name": name, "parents": [folder_id]}
                result = (
                    service.files()
                    .create(body=file_meta, media_body=media, fields="id")
                    .execute()
                )
                file_id = result["id"]
                print(f"    [GDrive] Done — {name} (id={file_id})")
                logger.info("Uploaded: %s → Drive id=%s", name, file_id)
                stats["uploaded"] += 1

                if delete_local:
                    f.unlink()
                    print(f"    [GDrive] Local copy deleted: {name}")

            except Exception as exc:
                logger.warning("Upload failed %s: %s", name, exc)
                print(f"    [GDrive] FAILED: {name} — {exc}")
                stats["failed"] += 1

    print(f"\n{'='*56}")
    print(f"  Sync complete — uploaded={stats['uploaded']}  skipped={stats['skipped']}  failed={stats['failed']}")
    print(f"{'='*56}\n")
    return stats


_CLIPS_FOLDER_PATH = ["Clips", "pexels"]


def download_clip(filename: str, local_path: Path) -> bool:
    """Download a Pexels clip by filename from Drive/Clips/pexels/ to local_path."""
    service = _get_service()
    folder_id = settings.GDRIVE_FOLDER_ID
    for part in _CLIPS_FOLDER_PATH:
        folder_id = _get_folder_id(service, part, folder_id)
        if folder_id is None:
            logger.warning("Drive folder not found for clip lookup: %s", part)
            return False

    query = f"name='{filename}' and '{folder_id}' in parents and trashed=false"
    files = service.files().list(q=query, fields="files(id)").execute().get("files", [])
    if not files:
        logger.warning("Clip not found on Drive: %s", filename)
        return False

    return download_file(files[0]["id"], local_path)


def download_file(drive_file_id: str, local_path: Path) -> bool:
    """Download a Drive file by ID to `local_path`.

    Returns True on success. Use this to retrieve a file that was
    previously uploaded and deleted locally.
    """
    from googleapiclient.http import MediaIoBaseDownload

    service = _get_service()
    local_path.parent.mkdir(parents=True, exist_ok=True)

    try:
        request = service.files().get_media(fileId=drive_file_id)
        with io.FileIO(str(local_path), "wb") as fh:
            downloader = MediaIoBaseDownload(fh, request)
            done = False
            while not done:
                _, done = downloader.next_chunk()
        size_mb = local_path.stat().st_size / (1024 * 1024)
        logger.info("Downloaded: %s (%.1f MB)", local_path.name, size_mb)
        return True
    except Exception as exc:
        logger.warning("Download failed for %s: %s", local_path.name, exc)
        return False
