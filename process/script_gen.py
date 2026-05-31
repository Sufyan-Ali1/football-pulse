"""
Script generator — Step 4.

Generates 20-30 second segment scripts for multi-story videos.
Each call returns script text, display headline, panel label,
3 bullet points, and 3 video clip IDs — all in one Groq call.

Prompt templates live in config/prompts/.
"""
import json
import logging
from pathlib import Path

from clients.groq_client import get_groq_client
from config import settings
from core.types import ContentType, NewsItem, Script

logger = logging.getLogger(__name__)

_groq = get_groq_client()

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "config" / "prompts"

def _load_prompt() -> str:
    return (_PROMPTS_DIR / "segment.txt").read_text(encoding="utf-8")


def _render(template: str, item: NewsItem, content_type: ContentType) -> str:
    return template.format(
        brand_name=settings.BRAND_NAME,
        brand_tagline=settings.BRAND_TAGLINE,
        headline=item.headline,
        body=item.body[:1000],
        source=item.source,
        content_type=content_type,
    )


def _word_count(text: str) -> int:
    return len(text.split())


def _estimate_duration(wc: int) -> int:
    return round(wc / 2.5)  # ~2.5 words/second for news delivery



def generate_segment_script(
    item: NewsItem,
    content_type: ContentType,
    clips: list | None = None,
) -> Script:
    """25-30 second segment script for multi-story videos (~80 words).

    Also selects up to 3 clip IDs from the local library in one Groq call.
    Pass clips= to reuse an already-fetched library (avoids repeated DB reads
    when generating scripts for multiple stories in one run).
    """
    from core.database import get_all_clips

    template    = _load_prompt()
    base_prompt = _render(template, item, content_type)
    if clips is None:
        clips = get_all_clips()

    if clips:
        clip_lines = "\n".join(
            f"ID: {c['id']} | Description: {c['description']} | Keywords: {c['keywords'] or ''}"
            for c in clips
        )
        clip_block = f"\n\nAVAILABLE VIDEO CLIPS:\n{clip_lines}"
    else:
        clip_block = "\n\nAVAILABLE VIDEO CLIPS: (none)"

    prompt = (
        f"{base_prompt}{clip_block}\n\n"
        "Return valid JSON with exactly these five keys:\n"
        '{\n'
        '  "script": "<around 80 words spoken voiceover script, equalling 25-30 seconds on air>",\n'
        '  "headline": "<punchy on-screen headline, 10-14 words, ALL CAPS>",\n'
        '  "panel_label": "<short label for the info panel, e.g. DEAL POINTS / MATCH STATS / KEY FACTS / INJURY UPDATE>",\n'
        '  "points": [\n'
        '    "<point 1 — one detailed fact relevant to this story, 15-20 words>",\n'
        '    "<point 2 — one detailed fact relevant to this story, 15-20 words>",\n'
        '    "<point 3 — one detailed fact relevant to this story, 15-20 words>"\n'
        '  ],\n'
        '  "video_ids": ["<id1>", "<id2>", "<id3>"]\n'
        '}\n'
        "headline: clean formatted version of the story for on-screen display.\n"
        "panel_label examples by story type:\n"
        "  transfer confirmed  → DEAL POINTS (list fee, contract length, clubs involved)\n"
        "  transfer rumour     → TRANSFER TALK (list interest, asking price, timeline)\n"
        "  manager sacked/appointed → KEY FACTS (list dates, replacement, record)\n"
        "  match result        → MATCH STATS (list scoreline, scorers, key moments)\n"
        "  injury/squad news   → SQUAD UPDATE (list player, timeline, impact)\n"
        "  club statement      → CLUB NEWS (list what was confirmed, when, next steps)\n"
        "points: 3 short bullet facts shown on screen — match the panel_label context, NOT script sentences.\n"
        "video_ids: 3 clip IDs that best match this story visually, in order of appearance. "
        "If fewer than 3 clips are available include as many as possible. If none, use []."
    )

    _MIN_WORDS = 50
    data = None
    for attempt in range(3):
        retry_note = (
            f"\n\nIMPORTANT: Your previous script was too short. "
            f"The script field MUST be at least 100 words. Write more detail."
            if attempt > 0 else ""
        )
        response = _groq.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": prompt + retry_note}],
            max_tokens=1000,
            temperature=0.7,
            response_format={"type": "json_object"},
        )
        data = json.loads(response.choices[0].message.content)
        wc_check = _word_count(str(data.get("script", "")))
        if wc_check >= _MIN_WORDS:
            break
        logger.warning("Script too short (%d words) on attempt %d — retrying", wc_check, attempt + 1)

    data             = data or {}
    text             = str(data.get("script", "")).strip()
    display_headline = str(data.get("headline", "")).strip()
    panel_label      = str(data.get("panel_label", "")).strip().upper()
    display_points   = [str(p) for p in data.get("points", []) if p][:3]
    video_ids        = [str(v) for v in data.get("video_ids", []) if v][:3]

    wc = _word_count(text)
    logger.info(
        "Segment script: %s | %d words | clips=%s | %s",
        content_type, wc, video_ids, item.headline[:60],
    )
    return Script(
        news_id=item.id, script_type=content_type, format="segment",
        text=text, word_count=wc, estimated_duration_seconds=_estimate_duration(wc),
        selected_clip_ids=video_ids,
        display_headline=display_headline,
        panel_label=panel_label,
        display_points=display_points,
    )


