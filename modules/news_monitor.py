"""
News monitor: fetches new football news items from RSS feeds, Twitter/X,
and Google Alerts (via RSS). Returns normalised NewsItem dataclasses.
"""
import hashlib
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import feedparser
import tweepy

from config import settings

logger = logging.getLogger(__name__)

SourceType = Literal["rss", "twitter", "google_alerts"]

SOURCES_PATH = Path(__file__).resolve().parent.parent / "config" / "sources.json"


@dataclass
class NewsItem:
    id: str                    # SHA-256 hash of headline (deduplication key)
    headline: str
    body: str
    url: str
    source: str                # e.g. "Sky Sports Football"
    source_type: SourceType
    timestamp: datetime
    raw: dict = field(default_factory=dict, repr=False)

    @staticmethod
    def make_id(headline: str) -> str:
        return hashlib.sha256(headline.strip().lower().encode()).hexdigest()[:16]


def _load_sources() -> dict:
    with open(SOURCES_PATH) as f:
        return json.load(f)


def _is_football_relevant(text: str) -> bool:
    """Quick keyword gate to filter non-football items."""
    sources = _load_sources()
    keywords = [kw.lower() for kw in sources.get("filter_keywords", [])]
    text_lower = text.lower()
    return any(kw in text_lower for kw in keywords)


# ── RSS ───────────────────────────────────────────────────────────────────────

def fetch_rss_items(feed_url: str, source_name: str) -> list[NewsItem]:
    items: list[NewsItem] = []
    try:
        feed = feedparser.parse(feed_url)
        for entry in feed.entries:
            headline = entry.get("title", "").strip()
            body = entry.get("summary", entry.get("description", "")).strip()
            url = entry.get("link", "")
            published = entry.get("published_parsed")

            if not headline:
                continue
            if not _is_football_relevant(headline + " " + body):
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
    except Exception as e:
        logger.warning("RSS fetch failed for %s: %s", feed_url, e)
    return items


def fetch_all_rss() -> list[NewsItem]:
    sources = _load_sources()
    results: list[NewsItem] = []
    for feed in sources.get("rss_feeds", []):
        if not feed.get("active", True):
            continue
        results.extend(fetch_rss_items(feed["url"], feed["name"]))
    return results


# ── Google Alerts (via RSS) ───────────────────────────────────────────────────

def fetch_google_alerts() -> list[NewsItem]:
    sources = _load_sources()
    results: list[NewsItem] = []
    for alert_url in sources.get("google_alert_rss_urls", []):
        if not alert_url.startswith("http"):
            continue
        results.extend(fetch_rss_items(alert_url, "Google Alerts"))
    return results


# ── Twitter / X ───────────────────────────────────────────────────────────────

def _get_twitter_client() -> tweepy.Client:
    return tweepy.Client(
        bearer_token=settings.TWITTER_BEARER_TOKEN,
        consumer_key=settings.TWITTER_API_KEY,
        consumer_secret=settings.TWITTER_API_SECRET,
        access_token=settings.TWITTER_ACCESS_TOKEN,
        access_token_secret=settings.TWITTER_ACCESS_SECRET,
        wait_on_rate_limit=True,
    )


def fetch_twitter_posts(since_id: str | None = None) -> list[NewsItem]:
    """
    Fetches recent tweets from monitored accounts.
    `since_id` avoids re-fetching already-seen tweets across poll cycles.
    """
    sources = _load_sources()
    usernames = [
        acc["username"]
        for acc in sources.get("twitter_accounts", [])
        if acc.get("active", True)
    ]
    if not usernames:
        return []

    client = _get_twitter_client()
    items: list[NewsItem] = []

    query = "(" + " OR ".join(f"from:{u}" for u in usernames) + ") -is:retweet lang:en"

    try:
        kwargs: dict = {
            "query": query,
            "max_results": 50,
            "tweet_fields": ["created_at", "author_id", "text", "entities"],
            "expansions": ["author_id"],
            "user_fields": ["username", "name"],
        }
        if since_id:
            kwargs["since_id"] = since_id

        response = client.search_recent_tweets(**kwargs)
        if not response.data:
            return []

        users = {u.id: u for u in (response.includes or {}).get("users", [])}

        for tweet in response.data:
            text = tweet.text.strip()
            if not _is_football_relevant(text):
                continue

            author = users.get(tweet.author_id)
            source_name = f"Twitter – {author.name}" if author else "Twitter"
            urls = []
            if tweet.entities and tweet.entities.get("urls"):
                urls = [u["expanded_url"] for u in tweet.entities["urls"]]
            url = urls[0] if urls else f"https://twitter.com/i/web/status/{tweet.id}"

            items.append(NewsItem(
                id=NewsItem.make_id(text),
                headline=text[:200],
                body=text,
                url=url,
                source=source_name,
                source_type="twitter",
                timestamp=tweet.created_at or datetime.now(timezone.utc),
                raw={"tweet_id": str(tweet.id), "author_id": str(tweet.author_id)},
            ))
    except tweepy.TweepyException as e:
        logger.warning("Twitter fetch failed: %s", e)

    return items


# ── Combined fetcher ──────────────────────────────────────────────────────────

def get_all_new_items(twitter_since_id: str | None = None) -> list[NewsItem]:
    """
    Fetches from all sources. Deduplication (by id) against the seen_news DB
    is handled by pipeline/deduplication.py — this returns raw unique items
    deduplicated only within this batch.
    """
    all_items: list[NewsItem] = []
    all_items.extend(fetch_all_rss())
    all_items.extend(fetch_google_alerts())
    all_items.extend(fetch_twitter_posts(since_id=twitter_since_id))

    # Deduplicate within this batch by id
    seen: set[str] = set()
    unique: list[NewsItem] = []
    for item in all_items:
        if item.id not in seen:
            seen.add(item.id)
            unique.append(item)

    logger.info("News monitor: %d unique items fetched", len(unique))
    return unique
