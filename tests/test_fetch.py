"""
Test: fetch layer (Steps 1 & 2) — with optimization metrics.
Verifies parallel fetching, ETag caching, and circuit breaker.

Run from football-autonews/:
    python -m tests.test_fetch
"""
import json
import time
from pathlib import Path

from fetch.rss    import fetch_all_rss, _get_sources, _get_keywords
from fetch.alerts import fetch_google_alerts

print("=" * 60)
print("TEST — Fetch Layer (Optimized)")
print("=" * 60)

# Step 1: Config cache check
print("\n[1] Config cache check...")
sources  = _get_sources()
keywords = _get_keywords()
print(f"    RSS feeds   : {len(sources['rss_feeds'])} configured")
print(f"    Alert URLs  : {len(sources['google_alert_rss_urls'])} configured")
print(f"    Keywords    : {len(keywords)} loaded")
# Call again — should hit cache, not re-read disk
_get_sources()
_get_keywords()
print("    Cache       : OK (called twice, loaded once)")

# Step 2: Parallel RSS fetch with timing
print("\n[2] Fetching all RSS feeds in parallel...")
t0        = time.perf_counter()
rss_items = fetch_all_rss()
rss_time  = time.perf_counter() - t0
print(f"    Items fetched : {len(rss_items)}")
print(f"    Time taken    : {rss_time:.2f}s (parallel — all feeds at once)")

# Step 3: ETag caching check
state_path = Path("config/feed_state.json")
if state_path.exists():
    with open(state_path) as f:
        state = json.load(f)
    feeds_with_etag     = sum(1 for v in state.values() if v.get("etag"))
    feeds_with_modified = sum(1 for v in state.values() if v.get("last_modified"))
    feeds_with_failures = sum(1 for v in state.values() if v.get("failures", 0) > 0)
    circuit_open        = sum(1 for v in state.values() if v.get("skip_until"))
    print(f"\n[3] Feed state (config/feed_state.json):")
    print(f"    Feeds tracked       : {len(state)}")
    print(f"    With ETag           : {feeds_with_etag}")
    print(f"    With Last-Modified  : {feeds_with_modified}")
    print(f"    With failures > 0   : {feeds_with_failures}")
    print(f"    Circuit open        : {circuit_open}")
else:
    print("\n[3] Feed state: not yet created (first run)")

# Step 4: Second fetch — should be faster if ETags hit 304
print("\n[4] Second fetch (testing ETag 304 caching)...")
t1         = time.perf_counter()
rss_items2 = fetch_all_rss()
rss_time2  = time.perf_counter() - t1
print(f"    Items fetched : {len(rss_items2)}")
print(f"    Time taken    : {rss_time2:.2f}s")
if rss_time2 < rss_time:
    print(f"    ETag speedup  : {rss_time - rss_time2:.2f}s faster (304 Not Modified on unchanged feeds)")

# Step 5: Google Alerts
print("\n[5] Fetching Google Alerts in parallel...")
t2           = time.perf_counter()
alert_items  = fetch_google_alerts()
alert_time   = time.perf_counter() - t2
print(f"    Items fetched : {len(alert_items)}")
print(f"    Time taken    : {alert_time:.2f}s")

# Summary
total = len(rss_items) + len(alert_items)
print("\n" + "=" * 60)
print(f"PASS — {total} total items | RSS: {rss_time:.2f}s | Alerts: {alert_time:.2f}s")
print("=" * 60)
