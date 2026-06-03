"""
Single SQLite database for the entire pipeline (database/articles.db).

Tables:
  articles      — every collected article with rank score + status
  daily_videos  — one row per day's generated video
  video_clips   — local stock video library (path + description + keywords)

Status lifecycle:
  articles:     pending → used | rejected
  daily_videos: pending → generating → done | failed
"""
import hashlib
import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core.types import NewsItem

logger = logging.getLogger(__name__)

_DB_PATH = Path(__file__).resolve().parent.parent / "database" / "articles.db"


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(_DB_PATH)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    return c


def init_db() -> None:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    with _conn() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS articles (
                id            TEXT PRIMARY KEY,
                headline      TEXT NOT NULL,
                body          TEXT,
                url           TEXT,
                source        TEXT,
                source_type   TEXT,
                content_type  TEXT,
                rank_score    INTEGER DEFAULT 0,
                timestamp     TEXT NOT NULL,
                status        TEXT DEFAULT 'pending',
                classified_by TEXT DEFAULT 'keyword',
                used_in_video TEXT,
                created_at    TEXT NOT NULL
            )
        """)
        # Migrate existing DB — add new columns if they don't exist yet
        for migration in [
            "ALTER TABLE articles ADD COLUMN classified_by TEXT DEFAULT 'keyword'",
            "ALTER TABLE articles ADD COLUMN relevance_score INTEGER DEFAULT NULL",
        ]:
            try:
                c.execute(migration)
            except Exception:
                pass
        c.execute("""
            CREATE TABLE IF NOT EXISTS daily_videos (
                video_date  TEXT PRIMARY KEY,
                article_ids TEXT NOT NULL,
                video_path  TEXT,
                status      TEXT DEFAULT 'pending',
                error       TEXT,
                created_at  TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS video_clips (
                id            TEXT PRIMARY KEY,
                file_path     TEXT NOT NULL UNIQUE,
                description   TEXT NOT NULL,
                keywords      TEXT,
                source        TEXT DEFAULT 'pexels',
                source_url    TEXT,
                duration      REAL,
                width         INTEGER,
                height        INTEGER,
                downloaded_at TEXT NOT NULL
            )
        """)
        c.commit()


# ── Articles ──────────────────────────────────────────────────────────────────

def article_exists(news_id: str) -> bool:
    with _conn() as c:
        return c.execute(
            "SELECT 1 FROM articles WHERE id = ?", (news_id,)
        ).fetchone() is not None


def insert_article(
    item: NewsItem,
    content_type: str,
    rank_score: int,
    status: str = "pending",
    classified_by: str = "keyword",
) -> None:
    with _conn() as c:
        c.execute(
            """INSERT OR IGNORE INTO articles
               (id, headline, body, url, source, source_type,
                content_type, rank_score, timestamp, status, classified_by, created_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                item.id, item.headline, item.body, item.url,
                item.source, item.source_type, content_type,
                rank_score, (item.timestamp.replace(tzinfo=timezone.utc) if item.timestamp.tzinfo is None else item.timestamp.astimezone(timezone.utc)).strftime("%Y-%m-%dT%H:%M:%SZ"),
                status, classified_by, datetime.now(timezone.utc).isoformat(),
            ),
        )
        c.commit()


def get_pending_articles(limit: int = 5, offset: int = 0) -> list[sqlite3.Row]:
    with _conn() as c:
        return c.execute(
            """SELECT * FROM articles
               WHERE status = 'pending'
                 AND COALESCE(timestamp, created_at) >= datetime('now', '-12 hours')
               ORDER BY
                 rank_score DESC,
                 COALESCE(timestamp, created_at) DESC
               LIMIT ? OFFSET ?""",
            (limit, offset),
        ).fetchall()


def get_articles_by_ids(article_ids: list[str]) -> list[sqlite3.Row]:
    if not article_ids:
        return []
    placeholders = ",".join("?" * len(article_ids))
    with _conn() as c:
        return c.execute(
            f"SELECT * FROM articles WHERE id IN ({placeholders})",
            article_ids,
        ).fetchall()




def mark_articles_used(article_ids: list[str], video_date: str) -> None:
    if not article_ids:
        return
    placeholders = ",".join("?" * len(article_ids))
    with _conn() as c:
        c.execute(
            f"UPDATE articles SET status='used', used_in_video=? WHERE id IN ({placeholders})",
            [video_date] + article_ids,
        )
        c.commit()



def mark_articles_rejected(article_ids: list[str]) -> None:
    if not article_ids:
        return
    placeholders = ",".join("?" * len(article_ids))
    with _conn() as c:
        c.execute(
            f"UPDATE articles SET status='rejected' WHERE id IN ({placeholders})",
            article_ids,
        )
        c.commit()


def bulk_update_article_classifications(
    updates: list[tuple[str, str, str, int | None]],
) -> None:
    """Update content_type, classified_by, relevance_score for multiple articles in one transaction.

    Each tuple: (article_id, content_type, classified_by, relevance_score)
    """
    if not updates:
        return
    with _conn() as c:
        c.executemany(
            "UPDATE articles SET content_type=?, classified_by=?, relevance_score=? WHERE id=?",
            [(ct, cb, rel, aid) for aid, ct, cb, rel in updates],
        )
        c.commit()


# ── Daily videos ──────────────────────────────────────────────────────────────

def create_daily_video_record(video_date: str, article_ids: list[str]) -> None:
    with _conn() as c:
        c.execute(
            """INSERT OR IGNORE INTO daily_videos
               (video_date, article_ids, status, created_at)
               VALUES (?,?,?,?)""",
            (
                video_date,
                json.dumps(article_ids),
                "pending",
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        c.commit()


def update_daily_video(
    video_date: str,
    status: str,
    video_path: str | None = None,
    error: str | None = None,
) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE daily_videos SET status=?, video_path=?, error=? WHERE video_date=?",
            (status, video_path, error, video_date),
        )
        c.commit()


def daily_video_exists(video_date: str) -> bool:
    with _conn() as c:
        return c.execute(
            "SELECT 1 FROM daily_videos WHERE video_date=? AND status IN ('done','generating')",
            (video_date,),
        ).fetchone() is not None


# ── Video clips ───────────────────────────────────────────────────────────────

def insert_video_clip(
    file_path: str,
    description: str,
    keywords: str = "",
    source: str = "pexels",
    source_url: str | None = None,
    duration: float | None = None,
    width: int | None = None,
    height: int | None = None,
) -> None:
    clip_id = hashlib.md5(file_path.encode()).hexdigest()
    with _conn() as c:
        c.execute(
            """INSERT OR IGNORE INTO video_clips
               (id, file_path, description, keywords, source, source_url,
                duration, width, height, downloaded_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)""",
            (
                clip_id, file_path, description, keywords, source, source_url,
                duration, width, height, datetime.now(timezone.utc).isoformat(),
            ),
        )
        c.commit()


def clip_exists(file_path: str) -> bool:
    with _conn() as c:
        return c.execute(
            "SELECT 1 FROM video_clips WHERE file_path = ?", (file_path,)
        ).fetchone() is not None


def update_video_clip_description(file_path: str, description: str, keywords: str) -> None:
    with _conn() as c:
        c.execute(
            "UPDATE video_clips SET description=?, keywords=? WHERE file_path=?",
            (description, keywords, file_path),
        )
        c.commit()


def get_all_clips() -> list[sqlite3.Row]:
    """Return every clip in the library, newest first."""
    with _conn() as c:
        return c.execute(
            "SELECT * FROM video_clips ORDER BY downloaded_at DESC"
        ).fetchall()


def get_clips_by_ids(ids: list[str]) -> list[sqlite3.Row]:
    """Return clips for the given IDs, preserving input order."""
    if not ids:
        return []
    placeholders = ",".join("?" * len(ids))
    with _conn() as c:
        rows = {
            r["id"]: r
            for r in c.execute(
                f"SELECT * FROM video_clips WHERE id IN ({placeholders})", ids
            ).fetchall()
        }
    return [rows[i] for i in ids if i in rows]


# ── Conversion helper ─────────────────────────────────────────────────────────

def row_to_news_item(row: sqlite3.Row) -> NewsItem:
    ts_str = row["timestamp"]
    try:
        ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except Exception:
        ts = datetime.now(timezone.utc)
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    return NewsItem(
        id=row["id"],
        headline=row["headline"],
        body=row["body"] or "",
        url=row["url"] or "",
        source=row["source"] or "",
        source_type=row["source_type"] or "rss",
        timestamp=ts,
    )


init_db()
