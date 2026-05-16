"""
Google Alerts RSS fetcher.

Fetches all configured alert URLs in parallel using the same
fetch_feeds_parallel() infrastructure as fetch/rss.py — so ETag caching,
timeout, and circuit breaker all apply here too.
"""
import logging

from core.types import NewsItem
from fetch.rss import fetch_feeds_parallel, _get_sources

logger = logging.getLogger(__name__)


def fetch_google_alerts() -> list[NewsItem]:
    """
    Fetch all Google Alert RSS URLs from config/sources.json in parallel.
    Returns football-relevant, deduplicated NewsItems.
    """
    sources = _get_sources()
    feeds   = [
        (url, "Google Alerts")
        for url in sources.get("google_alert_rss_urls", [])
        if url.startswith("http")
    ]
    items = fetch_feeds_parallel(feeds)
    logger.info("fetch_google_alerts: %d items from %d alerts", len(items), len(feeds))
    return items
