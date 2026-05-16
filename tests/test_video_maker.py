"""
Test: MoviePy video maker (Step 6 — HeyGen replacement).

Tests:
  1. Landscape video (main) with voiceover
  2. Vertical video (short) with voiceover
  3. Video without audio (silent fallback)

Run from football-autonews/:
    python -m tests.test_video_maker
"""
import time
from datetime import datetime, timezone
from pathlib import Path

from core.types import NewsItem, Script
from process.video_maker import create_video

# ── Test data ─────────────────────────────────────────────────────────────────

ITEM = NewsItem(
    id="test_vm_001",
    headline="Manchester United Sign Striker in £80m Deal — Here We Go",
    body=(
        "Manchester United have confirmed the signing of a new striker "
        "in a deal worth £80 million. The player will join the squad ahead "
        "of this weekend's Premier League fixture at Old Trafford. Manager "
        "confirms the deal is done and the player has passed his medical."
    ),
    url="https://example.com",
    source="Sky Sports Football",
    source_type="rss",
    timestamp=datetime.now(timezone.utc),
)

MAIN_SCRIPT = Script(
    news_id="test_vm_001",
    script_type="breaking_news",
    format="main",
    text=(
        "Breaking news tonight — Manchester United have officially confirmed "
        "a massive £80 million signing. The striker has passed his medical and "
        "will be in the squad this weekend. This is a statement of intent from "
        "the club as they push for a top-four finish. Stay tuned to Football "
        "Credo Hub for full reaction and analysis."
    ),
    word_count=60,
    estimated_duration_seconds=24,
)

SHORT_SCRIPT = Script(
    news_id="test_vm_001",
    script_type="breaking_news",
    format="short",
    text="Man Utd just signed a striker for £80m. Here we go! Follow Football Credo Hub.",
    word_count=15,
    estimated_duration_seconds=8,
)

# ── Test runner ───────────────────────────────────────────────────────────────

print("=" * 60)
print("TEST — MoviePy Video Maker")
print("=" * 60)

# Look for existing voiceover from test_voiceover test
voiceover_path = Path("storage/Voiceovers/test_001_main_english.mp3")
if voiceover_path.exists():
    print(f"\nUsing existing voiceover: {voiceover_path.name}")
else:
    voiceover_path = None
    print("\nNo voiceover found — videos will use estimated duration (silent).")
    print("Run tests/test_voiceover.py first to generate audio.")

# Test 1: Landscape (main video)
print("\n[1] Landscape video (1920x1080) ...")
# Delete previous test output so we re-render
prev = Path("storage/Videos/Raw/test_vm_001_main_raw.mp4")
if prev.exists():
    prev.unlink()

t0 = time.perf_counter()
try:
    path = create_video(MAIN_SCRIPT, voiceover_path, ITEM)
    elapsed = time.perf_counter() - t0
    size_mb = path.stat().st_size / (1024 * 1024)
    print(f"    Saved  : {path.name}")
    print(f"    Size   : {size_mb:.1f} MB")
    print(f"    Time   : {elapsed:.1f}s")
    print("    Status : PASS")
except Exception as e:
    print(f"    Status : FAIL — {e}")

# Test 2: Vertical (short video)
print("\n[2] Vertical video (1080x1920) ...")
prev_short = Path("storage/Videos/Raw/test_vm_001_short_raw.mp4")
if prev_short.exists():
    prev_short.unlink()

t1 = time.perf_counter()
try:
    path_short = create_video(SHORT_SCRIPT, voiceover_path, ITEM)
    elapsed = time.perf_counter() - t1
    size_mb = path_short.stat().st_size / (1024 * 1024)
    print(f"    Saved  : {path_short.name}")
    print(f"    Size   : {size_mb:.1f} MB")
    print(f"    Time   : {elapsed:.1f}s")
    print("    Status : PASS")
except Exception as e:
    print(f"    Status : FAIL — {e}")

# Test 3: No voiceover (silent fallback)
print("\n[3] Silent video (no voiceover) ...")
silent_script = Script(
    news_id="test_vm_silent",
    script_type="transfer_rumour",
    format="main",
    text="Ronaldo linked with shock return to Manchester United.",
    word_count=10,
    estimated_duration_seconds=10,
)
prev_silent = Path("storage/Videos/Raw/test_vm_silent_main_raw.mp4")
if prev_silent.exists():
    prev_silent.unlink()

try:
    path_silent = create_video(silent_script, None, ITEM)
    size_mb = path_silent.stat().st_size / (1024 * 1024)
    print(f"    Saved  : {path_silent.name}")
    print(f"    Size   : {size_mb:.1f} MB")
    print("    Status : PASS")
except Exception as e:
    print(f"    Status : FAIL — {e}")

print("\n" + "=" * 60)
print("Check storage/Videos/Raw/ to preview the output MP4 files.")
print("Open them in VLC or Windows Media Player to verify quality.")
print("=" * 60)
