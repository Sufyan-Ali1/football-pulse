from modules.news_monitor import fetch_all_rss
#from config import sources  # or load sources.json directly
import json

with open("config/sources.json") as f:
      config = json.load(f)

keywords = [k.lower() for k in config["filter_keywords"]]
items = fetch_all_rss()

print(f"Total fetched: {len(items)}")

relevant = [i for i in items if any(k in i.headline.lower() or k in i.body.lower() for k in keywords)]
skipped  = [i for i in items if i not in relevant]

print(f"Relevant (pass filter): {len(relevant)}")
print(f"Skipped (not football): {len(skipped)}\n")

print("=== RELEVANT ITEMS ===")
for item in relevant[:10]:
      print(f"[{item.source}] {item.headline}")

print("\n=== SKIPPED ITEMS ===")
for item in skipped[:5]:
      print(f"[{item.source}] {item.headline}")