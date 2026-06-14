"""Poll an existing Veo operation and save the result."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.generate_intro import _poll_operation, _extract_video_bytes
from publish.thumbnail import _get_vertex_access_token
from config import settings

OPERATION_ID = "projects/football-pulse-499015/locations/us-central1/publishers/google/models/veo-3.1-generate-001/operations/c79866f8-502c-474a-8c20-5a49667f3739"
OUTPUT_PATH  = ROOT / "config" / "video" / "intro.mp4"

token  = _get_vertex_access_token()
result = _poll_operation(OPERATION_ID, token)
video_bytes = _extract_video_bytes(result, token)
OUTPUT_PATH.write_bytes(video_bytes)
print(f"Saved: {OUTPUT_PATH} ({len(video_bytes)/1024/1024:.1f} MB)")
