"""
Test optimized Step 3:
  - Fetch all articles (~300)
  - Run through ranker (fuzzy dedup + scoring + top 20)
  - Run batch_classify (keyword + batched Groq)
  - Show Groq API call count vs old approach
"""
from modules.news_monitor import fetch_all_rss, fetch_google_alerts
from pipeline.ranker import rank_and_filter, get_batch_for_pipeline, score_item
from pipeline.content_classifier import batch_classify

print("=" * 60)
print("STEP 3 OPTIMIZED — Ranker + Batch Classifier")
print("=" * 60)

# ── Fetch ─────────────────────────────────────────────────────
print("\n[1] Fetching articles...")
rss_items    = fetch_all_rss()
alert_items  = fetch_google_alerts()
all_items    = rss_items + alert_items
print(f"    Raw articles fetched : {len(all_items)}")

# ── Ranker: fuzzy dedup + top 20 ──────────────────────────────
print("\n[2] Ranking & filtering...")
top_items = rank_and_filter(all_items, top_n=20)
print(f"    After dedup + top-20 : {len(top_items)} items")

print("\n    Top 5 by score:")
for item in top_items[:5]:
    print(f"      [{score_item(item):>3}] [{item.source:<25}] {item.headline[:65]}")

# ── Batch classify ────────────────────────────────────────────
print(f"\n[3] Batch classifying {len(top_items)} items...")
print(f"    Old approach : up to {len(top_items)} Groq calls")
classifications = batch_classify(top_items)

# Count how many went to Groq vs keyword
from pipeline.content_classifier import _keyword_classify
keyword_hits = sum(
    1 for item in top_items
    if _keyword_classify(item.headline + " " + item.body[:300])
)
groq_hits = len(top_items) - keyword_hits
groq_calls = max(1, (groq_hits + 9) // 10) if groq_hits else 0
print(f"    Keyword classified   : {keyword_hits}")
print(f"    Groq classified      : {groq_hits} ({groq_calls} API call(s))")
print(f"    API calls saved      : {groq_hits - groq_calls} vs old approach")

# ── Results ───────────────────────────────────────────────────
print(f"\n[4] Classification results:")
counts = {"breaking_news": 0, "transfer_rumour": 0, "club_update": 0, "tactical": 0}
for item in top_items:
    ct = classifications.get(item.id, "club_update")
    counts[ct] += 1
    print(f"    [{ct:<16}] {item.headline[:65]}")

print(f"\n    Breaking: {counts['breaking_news']} | Transfer: {counts['transfer_rumour']} | Club: {counts['club_update']} | Tactical: {counts['tactical']}")

# ── Pipeline batch (cap at 3) ─────────────────────────────────
print("\n[5] Pipeline batch (max 3, breaking first):")
pipeline_batch = get_batch_for_pipeline(top_items, max_per_run=3)
for item in pipeline_batch:
    ct = classifications.get(item.id, "club_update")
    print(f"    [{ct:<16}] {item.headline[:65]}")

print("\n" + "=" * 60)
print("Optimization summary:")
print(f"  Raw articles     : {len(all_items)}")
print(f"  After filtering  : {len(top_items)}")
print(f"  Groq API calls   : {groq_calls} (was up to {len(all_items)} before)")
print(f"  Pipeline runs    : {len(pipeline_batch)} per cycle")
print("=" * 60)
