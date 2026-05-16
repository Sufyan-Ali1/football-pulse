"""
Test: SadTalker talking head (Step 6).

Animates a static presenter photo to lip-sync with an ElevenLabs MP3.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SETUP INSTRUCTIONS (one-time, before running this test)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Step A — Clone SadTalker
  git clone https://github.com/OpenTalker/SadTalker.git C:\\SadTalker
  cd C:\\SadTalker

Step B — Install Python dependencies (use a venv if you prefer)
  pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118
  pip install -r requirements.txt

  If you don't have a CUDA GPU, use CPU-only PyTorch instead:
  pip install torch torchvision torchaudio

Step C — Download model weights (automated script)
  cd C:\\SadTalker
  python scripts/download_models.py

  OR download manually from:
    https://github.com/OpenTalker/SadTalker#-model-zoo
  And place the files in:
    C:\\SadTalker\\checkpoints\\
    C:\\SadTalker\\gfpgan\\weights\\

Step D — Add presenter photo
  Put a clear face photo at:
    football-autonews/config/presenter_english.jpg
  Requirements:
    - Front-facing, neutral expression
    - Good lighting, no obstructions
    - 512×512 pixels or larger recommended

Step E — Ensure .env is configured
  SADTALKER_PATH=C:\\SadTalker
  PRESENTER_PHOTO_ENGLISH=config/presenter_english.jpg
  SADTALKER_QUALITY=256

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
HOW TO RUN
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  cd football-autonews
  python -m tests.test_sadtalker

  Expected time: 5-15 min on CPU, 1-2 min on GPU.
  Output: storage/Videos/Raw/test_st_001_main_raw.mp4
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
import sys
import time
from pathlib import Path

# ── Pre-flight checks ─────────────────────────────────────────────────────────

def _check_prerequisites() -> bool:
    """Check everything is in place before attempting to run SadTalker."""
    ok = True

    from config import settings

    print("\n[Prerequisites]")

    # 1. SadTalker directory
    sadtalker_dir = Path(settings.SADTALKER_PATH) if settings.SADTALKER_PATH else None
    if not sadtalker_dir or not sadtalker_dir.exists():
        print(f"  ✗  SadTalker not found at: {settings.SADTALKER_PATH or '(SADTALKER_PATH not set)'}")
        print("     Fix: git clone https://github.com/OpenTalker/SadTalker.git C:\\SadTalker")
        ok = False
    else:
        print(f"  ✓  SadTalker directory: {sadtalker_dir}")

    # 2. inference.py
    if sadtalker_dir and sadtalker_dir.exists():
        inference = sadtalker_dir / "inference.py"
        if not inference.exists():
            print(f"  ✗  inference.py not found in {sadtalker_dir}")
            ok = False
        else:
            print(f"  ✓  inference.py found")

    # 3. Model weights
    if sadtalker_dir and sadtalker_dir.exists():
        checkpoints = sadtalker_dir / "checkpoints"
        if not checkpoints.exists() or not any(checkpoints.iterdir()):
            print(f"  ✗  Model weights missing: {checkpoints}")
            print("     Fix: cd C:\\SadTalker && python scripts/download_models.py")
            ok = False
        else:
            weight_count = len(list(checkpoints.iterdir()))
            print(f"  ✓  Model weights: {weight_count} files in checkpoints/")

    # 4. Presenter photo
    photo = settings.PRESENTER_PHOTO_ENGLISH
    if not photo.exists():
        print(f"  ✗  Presenter photo not found: {photo}")
        print("     Fix: Add a front-facing face photo at that path.")
        ok = False
    else:
        size_kb = photo.stat().st_size // 1024
        print(f"  ✓  Presenter photo: {photo.name} ({size_kb} KB)")

    # 5. Voiceover for the test
    vo_path = Path("storage/Voiceovers/test_001_main_english.mp3")
    if not vo_path.exists():
        print(f"  ✗  Test voiceover not found: {vo_path}")
        print("     Fix: Run tests/test_voiceover.py first to generate it.")
        ok = False
    else:
        size_kb = vo_path.stat().st_size // 1024
        print(f"  ✓  Test voiceover: {vo_path.name} ({size_kb} KB)")

    return ok


# ── Test data ─────────────────────────────────────────────────────────────────

from core.types import Script

TEST_SCRIPT = Script(
    news_id="test_st_001",
    script_type="breaking_news",
    format="main",
    text=(
        "Breaking news tonight — Manchester United have officially confirmed "
        "a massive £80 million signing. The striker has passed his medical and "
        "will be in the squad this weekend. Stay tuned to Football Credo Hub "
        "for full reaction and analysis."
    ),
    word_count=45,
    estimated_duration_seconds=18,
)


# ── Test runner ───────────────────────────────────────────────────────────────

print("=" * 60)
print("TEST — SadTalker Talking Head Generator")
print("=" * 60)

if not _check_prerequisites():
    print("\n✗  Prerequisites not met. Fix the issues above and re-run.")
    print("   See the SETUP INSTRUCTIONS at the top of this file.")
    sys.exit(1)

print("\n  All prerequisites met. Starting SadTalker...\n")

from process.sadtalker import generate_talking_head

vo_path = Path("storage/Voiceovers/test_001_main_english.mp3")

# Remove previous test output so we always re-generate
prev = Path(f"storage/Videos/Raw/{TEST_SCRIPT.news_id}_{TEST_SCRIPT.format}_raw.mp4")
if prev.exists():
    prev.unlink()
    print(f"  Removed previous output: {prev.name}")

print(f"  Input audio : {vo_path.name} ({vo_path.stat().st_size // 1024} KB)")
print(f"  Output path : {prev.name}")
print(f"  Quality     : {__import__('config').settings.SADTALKER_QUALITY}px")
print()
print("  NOTE: This may take 5-15 minutes on CPU. Do not interrupt.")
print("-" * 60)

t0 = time.perf_counter()
try:
    output = generate_talking_head(TEST_SCRIPT, vo_path, language="english")
    elapsed = time.perf_counter() - t0
    size_mb = output.stat().st_size / (1024 * 1024)

    print()
    print("=" * 60)
    print("  Status  : PASS")
    print(f"  Saved   : {output}")
    print(f"  Size    : {size_mb:.1f} MB")
    print(f"  Time    : {elapsed:.0f}s ({elapsed / 60:.1f} min)")
    print("=" * 60)
    print()
    print("Next steps:")
    print("  1. Open the MP4 in VLC to check lip-sync quality.")
    print("  2. If quality is good → this replaces video_maker.py for Module 1.")
    print("  3. If quality is poor → adjust SADTALKER_QUALITY=512 in .env for HD.")
    print("  4. If too slow → consider a GPU instance on Railway for production.")

except Exception as e:
    elapsed = time.perf_counter() - t0
    print()
    print("=" * 60)
    print(f"  Status  : FAIL ({elapsed:.0f}s elapsed)")
    print(f"  Error   : {e}")
    print("=" * 60)
    print()
    print("Troubleshooting:")
    print("  - Check the SadTalker stderr output above for the root cause.")
    print("  - Common issues:")
    print("    • Missing CUDA / wrong PyTorch version → install CPU PyTorch")
    print("    • Missing gfpgan weights → re-run scripts/download_models.py")
    print("    • Photo not a valid face → use a clear front-facing portrait")
    sys.exit(1)
