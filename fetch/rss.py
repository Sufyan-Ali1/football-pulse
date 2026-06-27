"""
RSS feed fetcher — optimized.

Optimizations applied:
  1. sources.json loaded once per process (lru_cache)
  2. All feeds fetched in parallel (ThreadPoolExecutor)
  3. Per-feed 10-second timeout via requests
  4. ETag / Last-Modified conditional GET — skips unchanged feeds (304)
  5. Circuit breaker — skips dead feeds for 30 min after 5 consecutive failures

State (ETags + failure counts) is persisted to config/feed_state.json
so it survives process restarts.
"""
import functools
import json
import logging
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta, timezone
from pathlib import Path

import feedparser
import requests

from core.types import NewsItem

logger = logging.getLogger(__name__)

_SOURCES_PATH = Path(__file__).resolve().parent.parent / "config" / "sources.json"
_STATE_PATH   = Path(__file__).resolve().parent.parent / "config" / "feed_state.json"
_STATE_LOCK   = threading.Lock()

_TIMEOUT      = 10   # seconds — per-feed request timeout
_MAX_FAILURES = 5    # consecutive failures before circuit opens
_SKIP_MINUTES = 30   # how long a broken feed is skipped


# ── 1. sources.json cached after first load ───────────────────────────────────

@functools.lru_cache(maxsize=1)
def _get_sources() -> dict:
    with open(_SOURCES_PATH) as f:
        return json.load(f)


@functools.lru_cache(maxsize=1)
def _get_keywords() -> tuple[str, ...]:
    return tuple(kw.lower() for kw in _get_sources().get("filter_keywords", []))


# ── Feed state persistence (ETag + circuit breaker) ───────────────────────────

def _load_state() -> dict:
    with _STATE_LOCK:
        if not _STATE_PATH.exists():
            return {}
        try:
            with open(_STATE_PATH) as f:
                return json.load(f)
        except Exception:
            return {}


def _save_state(state: dict) -> None:
    with _STATE_LOCK:
        with open(_STATE_PATH, "w") as f:
            json.dump(state, f, indent=2)


# ── 5. Circuit breaker check ──────────────────────────────────────────────────

def _circuit_open(entry: dict) -> bool:
    """True if this feed should be skipped right now."""
    skip_until = entry.get("skip_until")
    if not skip_until:
        return False


def _entry_body(entry) -> str:
    """Prefer the richest body field exposed by the feed entry."""
    for key in ("summary", "description"):
        value = entry.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    content = entry.get("content")
    if isinstance(content, list):
        for part in content:
            if isinstance(part, dict):
                value = part.get("value")
                if isinstance(value, str) and value.strip():
                    return value.strip()
    return ""
    try:
        return datetime.fromisoformat(skip_until) > datetime.now(timezone.utc)
    except Exception:
        return False


# ── Entry parsing (shared by all fetchers) ────────────────────────────────────

def _parse_entries(feed, source_name: str) -> list[NewsItem]:
    keywords = _get_keywords()
    items: list[NewsItem] = []

    for entry in feed.entries:
        headline  = entry.get("title", "").strip()
        body      = _entry_body(entry)
        url       = entry.get("link", "")
        published = entry.get("published_parsed")

        if not headline:
            continue
        if headline.lower().startswith("rt by @"):
            continue
        if not any(kw in (headline + " " + body).lower() for kw in keywords):
            continue

        ts = (
            datetime(*published[:6], tzinfo=timezone.utc)
            if published
            else datetime.now(timezone.utc)
        )
        items.append(NewsItem(
            id=NewsItem.make_id(headline),
            headline=headline,
            body=body,
            url=url,
            source=source_name,
            source_type="rss",
            timestamp=ts,
            raw=dict(entry),
        ))
    return items


# ── 3 & 4. Single-feed fetch: timeout + ETag conditional GET ─────────────────

def _fetch_one(
    url: str,
    source_name: str,
    feed_state: dict,
) -> tuple[list[NewsItem], dict]:
    """
    Fetch one RSS URL with timeout and ETag support.
    Returns (items, updated_state_entry).
    Never raises — failures are recorded in the returned state.
    """
    updated = dict(feed_state)

    # Build conditional request headers (ETag / Last-Modified)
    headers = {"User-Agent": "FootballAutoNews/1.0"}
    if feed_state.get("etag"):
        headers["If-None-Match"] = feed_state["etag"]
    if feed_state.get("last_modified"):
        headers["If-Modified-Since"] = feed_state["last_modified"]

    try:
        resp = requests.get(url, headers=headers, timeout=_TIMEOUT)

        # 304 Not Modified — feed unchanged, nothing new to process
        if resp.status_code == 304:
            logger.debug("Feed unchanged (304): %s", source_name)
            updated.update({"failures": 0, "skip_until": None})
            return [], updated

        resp.raise_for_status()

        # Save new ETag / Last-Modified for next poll
        updated["etag"]          = resp.headers.get("ETag", feed_state.get("etag", ""))
        updated["last_modified"] = resp.headers.get("Last-Modified", feed_state.get("last_modified", ""))
        updated["failures"]      = 0
        updated["skip_until"]    = None

        items = _parse_entries(feedparser.parse(resp.content), source_name)
        logger.info("RSS [%-25s]: %d items", source_name, len(items))
        return items, updated

    except requests.Timeout:
        logger.warning("Feed timed out after %ds: %s", _TIMEOUT, source_name)
    except Exception as e:
        logger.warning("Feed fetch failed [%s]: %s", source_name, e)

    # Record failure and open circuit if threshold reached
    failures = feed_state.get("failures", 0) + 1
    updated["failures"] = failures
    if failures >= _MAX_FAILURES:
        updated["skip_until"] = (
            datetime.now(timezone.utc) + timedelta(minutes=_SKIP_MINUTES)
        ).isoformat()
        logger.warning(
            "Circuit open for '%s' after %d failures — skipping for %d min",
            source_name, failures, _SKIP_MINUTES,
        )
    return [], updated


# ── 2. Parallel batch fetcher (shared by fetch_all_rss + fetch_google_alerts) ─

def fetch_feeds_parallel(feeds: list[tuple[str, str]]) -> list[NewsItem]:
    """
    Fetch a list of (url, source_name) pairs in parallel.
    Persists ETag + circuit-breaker state after all fetches complete.
    Returns deduplicated NewsItems.
    """
    if not feeds:
        return []

    state        = _load_state()
    all_items:   list[NewsItem]   = []
    state_updates: dict[str, dict] = {}
    updates_lock = threading.Lock()

    def _task(url: str, name: str) -> list[NewsItem]:
        feed_state = state.get(url, {})
        if _circuit_open(feed_state):
            logger.info("Circuit open — skipping '%s'", name)
            return []
        items, updated = _fetch_one(url, name, feed_state)
        with updates_lock:
            state_updates[url] = updated
        return items

    # All feeds run concurrently — total time ≈ slowest single feed
    with ThreadPoolExecutor(max_workers=min(len(feeds), 10)) as pool:
        futures = {pool.submit(_task, url, name): name for url, name in feeds}
        for future in as_completed(futures):
            name = futures[future]
            try:
                all_items.extend(future.result())
            except Exception as e:
                logger.warning("Unexpected error fetching '%s': %s", name, e)

    # Write state once after all threads finish (no concurrent writes)
    state.update(state_updates)
    _save_state(state)

    # Deduplicate within this batch by NewsItem.id
    seen: set[str] = set()
    result: list[NewsItem] = []
    for i in all_items:
        if i.id not in seen:
            seen.add(i.id)
            result.append(i)
    return result



def fetch_all_rss() -> list[NewsItem]:
    """
    Fetch all active RSS feeds from config/sources.json in parallel.
    Returns football-relevant, deduplicated NewsItems.
    """
    sources = _get_sources()
    feeds   = [
        (f["url"], f["name"])
        for f in sources.get("rss_feeds", [])
        if f.get("active", True)
    ]
    items = fetch_feeds_parallel(feeds)
    logger.info("fetch_all_rss: %d unique items from %d feeds", len(items), len(feeds))
    return items
