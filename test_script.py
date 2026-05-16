from modules.news_monitor import fetch_all_rss, fetch_google_alerts

print("=== RSS FEEDS ===")
items = fetch_all_rss()
for item in items[:5]:  # show first 5
      print(f"[{item.source}] {item.headline}")
      print(f"  URL: {item.url}")
      print(f"  Time: {item.timestamp}")
      print()

print(f"Total RSS items fetched: {len(items)}")

print("\n=== GOOGLE ALERTS ===")
alerts = fetch_google_alerts()
print(f"Total Alert items: {len(alerts)}")
for item in alerts[:3]:
      print(f"  {item.headline}")