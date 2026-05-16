"""
Test: process layer (Steps 3 & 4)
Fetches articles, runs ranker, then batch_classify, then generates scripts for 1 item.

Run from football-autonews/:
    python -m tests.test_process
"""
from fetch.rss      import fetch_all_rss
from fetch.alerts   import fetch_google_alerts
from process.ranker import rank_and_filter, get_batch_for_pipeline, score_item
from process.classifier import batch_classify, _keyword_classify
from process.script_gen import generate_all_scripts

print("=" * 60)
print("TEST — Process Layer (Ranker + Classifier + Script Gen)")
print("=" * 60)

# Fetch
print("\n[1] Fetching articles...")
all_items = fetch_all_rss() + fetch_google_alerts()
print(f"    Raw total: {len(all_items)}")

# Rank + filter
print("\n[2] Ranking & filtering (top 20)...")
top_items = rank_and_filter(all_items, top_n=20)
print(f"    After dedup + top-20: {len(top_items)} items")
print("\n    Top 5 by score:")
for item in top_items[:5]:
    print(f"      [{score_item(item):>3}] [{item.source:<25}] {item.headline[:60]}")

# Batch classify
print(f"\n[3] Batch classifying {len(top_items)} items...")
classifications = batch_classify(top_items)

keyword_hits = sum(1 for i in top_items if _keyword_classify(i.headline + " " + i.body[:300]))
groq_hits    = len(top_items) - keyword_hits
groq_calls   = max(1, (groq_hits + 9) // 10) if groq_hits else 0
print(f"    Keyword: {keyword_hits} | Groq: {groq_hits} ({groq_calls} API call(s))")

counts = {"breaking_news": 0, "transfer_rumour": 0, "club_update": 0, "tactical": 0}
for item in top_items:
    ct = classifications.get(item.id, "club_update")
    counts[ct] += 1
    print(f"    [{ct:<16}] {item.headline[:65]}")
print(f"\n    Breaking: {counts['breaking_news']} | Transfer: {counts['transfer_rumour']} | Club: {counts['club_update']} | Tactical: {counts['tactical']}")

# Script generation (1 item)
pipeline_batch = get_batch_for_pipeline(top_items, max_per_run=3)
if pipeline_batch:
    test_item = pipeline_batch[0]
    test_type = classifications.get(test_item.id, "club_update")
    print(f"\n[4] Generating scripts for: {test_item.headline[:70]}")
    main_s, short_s = generate_all_scripts(test_item, test_type)
    print(f"    Main  : {main_s.word_count} words (~{main_s.estimated_duration_seconds}s)")
    print(f"    Short : {short_s.word_count} words (~{short_s.estimated_duration_seconds}s)")

print("\n" + "=" * 60)
print(f"PASS — {len(all_items)} raw → {len(top_items)} ranked → {len(pipeline_batch)} pipeline batch")
print("=" * 60)
