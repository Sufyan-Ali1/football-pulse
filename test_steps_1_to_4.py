"""
Test Steps 1-4:
  Step 1 - Project setup (settings + sources load correctly)
  Step 2 - News Monitor (fetch from RSS + Google Alerts)
  Step 3 - Content Classifier (classify each item)
  Step 4 - Script Generator (generate main + short script via Groq)
"""
import json
from config import settings
from modules.news_monitor import fetch_all_rss, fetch_google_alerts
from pipeline.content_classifier import classify
from modules.script_generator import generate_all_scripts

# ── Step 1: Settings & config load ───────────────────────────────────────────
print("=" * 60)
print("STEP 1 — Settings & Config")
print("=" * 60)
print(f"Brand      : {settings.BRAND_NAME}")
print(f"Groq model : {settings.GROQ_MODEL}")
print(f"Groq key   : {'SET' if settings.GROQ_API_KEY else 'MISSING'}")

with open("config/sources.json") as f:
    sources = json.load(f)
print(f"RSS feeds  : {len(sources['rss_feeds'])}")
print(f"Alerts     : {len(sources['google_alert_rss_urls'])}")
print()

# ── Step 2: News Monitor ──────────────────────────────────────────────────────
print("=" * 60)
print("STEP 2 — News Monitor")
print("=" * 60)

rss_items = fetch_all_rss()
alert_items = fetch_google_alerts()
all_items = rss_items + alert_items

print(f"RSS items fetched    : {len(rss_items)}")
print(f"Alert items fetched  : {len(alert_items)}")
print(f"Total items          : {len(all_items)}")
print()

# ── Step 3: Content Classifier ────────────────────────────────────────────────
print("=" * 60)
print("STEP 3 — Content Classifier (first 10 items)")
print("=" * 60)

counts = {"breaking_news": 0, "transfer_rumour": 0, "club_update": 0, "tactical": 0}
classified_items = []

for item in all_items[:10]:
    content_type = classify(item)
    counts[content_type] += 1
    classified_items.append((item, content_type))
    print(f"[{content_type:<16}] {item.headline[:70]}")

print(f"\nBreaking: {counts['breaking_news']} | Transfer: {counts['transfer_rumour']} | Club: {counts['club_update']} | Tactical: {counts['tactical']}")
print()

# ── Step 4: Script Generator ──────────────────────────────────────────────────
print("=" * 60)
print("STEP 4 — Script Generator (1 item via Groq)")
print("=" * 60)

# Pick first item for script generation
test_item, test_type = classified_items[0]
print(f"Generating scripts for: {test_item.headline[:70]}")
print(f"Content type          : {test_type}")
print()

main_script, short_script = generate_all_scripts(test_item, test_type)

print(f"--- MAIN SCRIPT ({main_script.word_count} words, ~{main_script.estimated_duration_seconds}s) ---")
print(main_script.text)
print()
print(f"--- SHORT SCRIPT ({short_script.word_count} words, ~{short_script.estimated_duration_seconds}s) ---")
print(short_script.text)
print()
print("=" * 60)
print("All 4 steps completed successfully!")
print("=" * 60)
