"""
SQLite-backed deduplication store.
Tracks every news item that has entered the pipeline so it is never processed twice.
"""
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core.types import NewsItem

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parent / "seen_news.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    return c


def init_db() -> None:
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS seen_news (
                id          TEXT PRIMARY KEY,
                headline    TEXT NOT NULL,
                source      TEXT,
                source_type TEXT,
                url         TEXT,
                seen_at     TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS pipeline_runs (
                id          TEXT PRIMARY KEY,
                status      TEXT NOT NULL DEFAULT 'pending',
                error       TEXT,
                started_at  TEXT,
                finished_at TEXT
            )
        """)
        c.commit()


def is_seen(news_id: str) -> bool:
    with _conn() as c:
        return c.execute("SELECT 1 FROM seen_news WHERE id = ?", (news_id,)).fetchone() is not None


def mark_seen(item: NewsItem) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR IGNORE INTO seen_news (id, headline, source, source_type, url, seen_at) VALUES (?,?,?,?,?,?)",
            (item.id, item.headline, item.source, item.source_type, item.url,
             datetime.now(timezone.utc).isoformat()),
        )
        c.commit()


def filter_unseen(items: list[NewsItem]) -> list[NewsItem]:
    """Return only items not yet processed."""
    return [i for i in items if not is_seen(i.id)]


def mark_pipeline_started(news_id: str) -> None:
    with _conn() as c:
        c.execute(
            "INSERT OR REPLACE INTO pipeline_runs (id, status, started_at) VALUES (?, 'in_progress', ?)",
            (news_id, datetime.now(timezone.utc).isoformat()),
        )
        c.commit()


def mark_pipeline_finished(news_id: str, error: str | None = None) -> None:
    status = "failed" if error else "completed"
    with _conn() as c:
        c.execute(
            "UPDATE pipeline_runs SET status=?, error=?, finished_at=? WHERE id=?",
            (status, error, datetime.now(timezone.utc).isoformat(), news_id),
        )
        c.commit()


init_db()
