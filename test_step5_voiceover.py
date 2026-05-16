"""
Test Step 5 — ElevenLabs Voiceover Generation
Uses a hardcoded sample script to test both English and Yoruba voices.
"""
from modules.script_generator import Script
from modules.voiceover import generate_voiceover

# Sample football news script
sample_script = Script(
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
print("STEP 5 — Voiceover Generation")
print("=" * 60)

# Test English voice
print("\n[1] Generating ENGLISH voiceover...")
try:
    path = generate_voiceover(sample_script, language="english")
    size_kb = path.stat().st_size / 1024
    print(f"    Saved : {path}")
    print(f"    Size  : {size_kb:.1f} KB")
    print("    Status: OK")
except Exception as e:
    print(f"    Status: FAILED — {e}")

# Test Yoruba voice
print("\n[2] Generating YORUBA voiceover...")
yoruba_script = Script(
    news_id="test_001",
    script_type="breaking_news",
    format="short",
    text=(
        "Iroyin pataki lati Premier League. Manchester United ti fidi mulẹ pe wọn ti fowo si adehun "
        "pẹlu oṣere tuntun. Jẹ ki a tẹle Football Credo Hub fun iroyin siwaju sii."
    ),
    word_count=30,
    estimated_duration_seconds=15,
)
try:
    path = generate_voiceover(yoruba_script, language="yoruba")
    size_kb = path.stat().st_size / 1024
    print(f"    Saved : {path}")
    print(f"    Size  : {size_kb:.1f} KB")
    print("    Status: OK")
except Exception as e:
    print(f"    Status: FAILED — {e}")

print("\n" + "=" * 60)
print("Check storage/Voiceovers/ folder for the MP3 files.")
print("=" * 60)
