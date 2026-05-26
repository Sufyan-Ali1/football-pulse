"""
Pexels Videos API client.
Searches for HD B-roll clips and caches them locally by video ID.
"""
import hashlib
import logging
import random
import requests
from pathlib import Path

logger = logging.getLogger(__name__)

FALLBACK_QUERY = "football match players"


def fetch_clips(
    query: str,
    api_key: str,
    cache_dir: Path,
    n: int,
) -> list[Path | None]:
    """Search Pexels, randomly pick n HD clips, cache by video ID.
    Each call returns a different random selection — same theme, fresh variety."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    base_key = hashlib.md5(query.encode()).hexdigest()[:10]

    print(f"    [Pexels] Searching: {query!r} ...")
    try:
        resp = requests.get(
            "https://api.pexels.com/videos/search",
            headers={"Authorization": api_key},
            params={"query": query, "per_page": 15,
                    "min_duration": 6, "max_duration": 20,
                    "orientation": "landscape"},
            timeout=15,
        )
        resp.raise_for_status()
        videos = resp.json().get("videos", [])
    except Exception as exc:
        logger.warning("Pexels search failed: %s", exc)
        print(f"    [Pexels] Search failed: {exc}")
        return [None] * n

    hd_videos = [
        v for v in videos
        if any(f.get("quality") == "hd" and f.get("width", 0) >= 1280
               for f in v.get("video_files", []))
    ]
    if not hd_videos:
        hd_videos = videos

    if not hd_videos:
        print("    [Pexels] No results found — using fallback placeholder")
        return [None] * n

    print(f"    [Pexels] {len(hd_videos)} HD results — picking {n} randomly")

    k      = min(n, len(hd_videos))
    picked = random.sample(hd_videos, k)

    result: list[Path | None] = []
    for i, vid in enumerate(picked, 1):
        vid_path = cache_dir / f"pexels_{base_key}_v{vid['id']}.mp4"
        if vid_path.exists():
            print(f"    [Pexels] Clip {i}/{k}: {vid_path.name} (cached)")
        else:
            hd_files = [f for f in vid.get("video_files", [])
                        if f.get("quality") == "hd"
                        and 1280 <= f.get("width", 0) <= 1920]
            if not hd_files:
                hd_files = vid.get("video_files", [])
            target = max(hd_files, key=lambda f: f.get("width", 0), default=None)
            if not target:
                result.append(None)
                continue
            try:
                print(f"    [Pexels] Clip {i}/{k}: downloading {vid_path.name} ...")
                data = requests.get(target["link"], timeout=90, stream=True)
                with open(vid_path, "wb") as fp:
                    for chunk in data.iter_content(65536):
                        fp.write(chunk)
                size_kb = vid_path.stat().st_size // 1024
                print(f"    [Pexels] Clip {i}/{k}: done ({size_kb} KB)")
                logger.info("Cached clip: %s", vid_path.name)
                _try_index(vid_path, vid, target)
            except Exception as exc:
                logger.warning("Download failed vid=%s: %s", vid["id"], exc)
                print(f"    [Pexels] Clip {i}/{k}: download failed — {exc}")
                result.append(None)
                continue
        result.append(vid_path)

    while len(result) < n:
        result.append(result[0] if result else None)
    return result


def _try_index(vid_path: Path, vid: dict, target: dict) -> None:
    """Index the downloaded clip in the background — errors must not block rendering."""
    try:
        from process.clip_indexer import index_clip
        index_clip(
            video_path=vid_path,
            source_url=vid.get("url"),
            width=target.get("width"),
            height=target.get("height"),
        )
    except Exception as exc:
        logger.warning("Clip indexing failed for %s: %s", vid_path.name, exc)
