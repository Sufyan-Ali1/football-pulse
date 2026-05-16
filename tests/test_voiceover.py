"""
Test: voiceover (Step 5)
Uses a hardcoded sample script to test English voice generation.

Run from football-autonews/:
    python -m tests.test_voiceover
"""
from core.types import Script
from process.voiceover import generate_voiceover

SAMPLE = Script(
    news_id="test_001",
    script_type="breaking_news",
    format="main",
    text=(
        "Breaking news from the Premier League. Manchester United have officially confirmed "
        "the signing of a new striker on a four-year deal. The club announced the transfer "
        "late on Thursday evening, with the player set to join the squad ahead of the weekend fixture. "
        "This is a major statement of intent from the manager as United look to push for a top-four finish. "
        "Stay tuned to Football Credo Hub for full coverage and reaction."
    ),
    word_count=75,
    estimated_duration_seconds=30,
)

print("=" * 60)
print("TEST — Voiceover (Step 5)")
print("=" * 60)

print("\n[1] Generating ENGLISH voiceover...")
try:
    path    = generate_voiceover(SAMPLE, language="english")
    size_kb = path.stat().st_size / 1024
    print(f"    Saved : {path.name}")
    print(f"    Size  : {size_kb:.1f} KB")
    print("    Status: PASS")
except Exception as e:
    print(f"    Status: FAIL — {e}")

print("\n" + "=" * 60)
print("Check storage/Voiceovers/ for the MP3 file.")
print("=" * 60)
