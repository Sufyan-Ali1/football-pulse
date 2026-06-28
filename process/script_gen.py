"""
Script generator - Step 4.

Generates 20-30 second segment scripts for multi-story videos.
Each call returns script text, display headline, panel label,
3 bullet points, and a bounded set of relevant video clip IDs.

Prompt templates live in config/prompts/.
"""
import json
import logging
import re
from pathlib import Path

from openai import BadRequestError

from clients.groq_client import get_groq_client
from config import settings
from core.types import ContentType, NewsItem, Script

logger = logging.getLogger(__name__)

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "config" / "prompts"
_CLIP_CONTEXT_LIMITS = (24, 12, 6)
_CLIP_DESCRIPTION_LIMIT = 140
_CLIP_KEYWORDS_LIMIT = 80


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


def _clip_duration_seconds(clip: dict) -> float:
    duration = clip["duration"]
    if isinstance(duration, (int, float)) and duration > 0:
        return float(duration)
    return 6.0


def _story_terms(item: NewsItem, content_type: ContentType) -> set[str]:
    text = " ".join(
        [
            item.headline or "",
            item.body[:400] or "",
            item.source or "",
            content_type,
        ]
    ).lower()
    return {
        term
        for term in re.findall(r"[a-z0-9']+", text)
        if len(term) >= 3
    }


def _clip_relevance_score(clip: dict, story_terms: set[str]) -> tuple[int, float]:
    clip_text = " ".join(
        [
            clip.get("description") or "",
            clip.get("keywords") or "",
        ]
    ).lower()
    clip_terms = {
        term
        for term in re.findall(r"[a-z0-9']+", clip_text)
        if len(term) >= 3
    }
    overlap = len(story_terms & clip_terms)
    return overlap, _clip_duration_seconds(clip)


def _truncate_text(text: str, limit: int) -> str:
    cleaned = " ".join((text or "").split())
    if len(cleaned) <= limit:
        return cleaned
    return cleaned[: max(0, limit - 3)].rstrip() + "..."


def _rank_story_clips(
    clips: list,
    item: NewsItem,
    content_type: ContentType,
) -> list[dict]:
    story_terms = _story_terms(item, content_type)
    return sorted(
        clips,
        key=lambda clip: _clip_relevance_score(clip, story_terms),
        reverse=True,
    )


def _build_clip_block(candidate_clips: list[dict]) -> str:
    if not candidate_clips:
        return "\n\nAVAILABLE VIDEO CLIPS: (none)"

    clip_lines = "\n".join(
        (
            f"ID: {clip['id']} | Duration: {_clip_duration_seconds(clip):.2f}s | "
            f"Description: {_truncate_text(clip.get('description', ''), _CLIP_DESCRIPTION_LIMIT)} | "
            f"Keywords: {_truncate_text(clip.get('keywords', ''), _CLIP_KEYWORDS_LIMIT)}"
        )
        for clip in candidate_clips
    )
    return f"\n\nAVAILABLE VIDEO CLIPS:\n{clip_lines}"


def _select_covering_clip_ids(
    llm_video_ids: list[str],
    clips: list,
    target_duration_seconds: int,
    item: NewsItem,
    content_type: ContentType,
) -> list[str]:
    if not clips or target_duration_seconds <= 0:
        return []

    clip_by_id = {str(clip["id"]): clip for clip in clips}
    selected_ids: list[str] = []
    total_duration = 0.0

    for clip_id in llm_video_ids:
        clip = clip_by_id.get(clip_id)
        if not clip or clip_id in selected_ids:
            continue
        selected_ids.append(clip_id)
        total_duration += _clip_duration_seconds(clip)
        if total_duration >= target_duration_seconds:
            return selected_ids

    story_terms = _story_terms(item, content_type)
    remaining = [
        clip for clip in clips
        if str(clip["id"]) not in selected_ids
    ]
    ranked_remaining = sorted(
        remaining,
        key=lambda clip: _clip_relevance_score(clip, story_terms),
        reverse=True,
    )

    for clip in ranked_remaining:
        clip_id = str(clip["id"])
        selected_ids.append(clip_id)
        total_duration += _clip_duration_seconds(clip)
        if total_duration >= target_duration_seconds:
            break

    logger.info(
        "Clip coverage for '%s': %.1fs / target %ss using %d clip(s)",
        item.headline[:60],
        total_duration,
        target_duration_seconds,
        len(selected_ids),
    )
    return selected_ids


def generate_segment_script(
    item: NewsItem,
    content_type: ContentType,
    clips: list | None = None,
) -> Script:
    """25-30 second segment script for multi-story videos (~80 words).

    Also selects enough unique clip IDs to cover the story runtime.
    Pass clips= to reuse an already-fetched library (avoids repeated DB reads
    when generating scripts for multiple stories in one run).
    """
    from core.database import get_all_clips

    template = _load_prompt()
    base_prompt = _render(template, item, content_type)
    if clips is None:
        clips = get_all_clips()

    prompt_suffix = (
        "\n\n"
        "Return valid JSON with exactly these five keys:\n"
        "{\n"
        '  "script": "<around 80 words spoken voiceover script, equalling 25-30 seconds on air>",\n'
        '  "headline": "<punchy on-screen headline, 10-14 words, ALL CAPS>",\n'
        '  "panel_label": "<short label for the info panel, e.g. DEAL POINTS / MATCH STATS / KEY FACTS / INJURY UPDATE>",\n'
        '  "points": [\n'
        '    "<point 1 - one detailed fact relevant to this story, 15-20 words>",\n'
        '    "<point 2 - one detailed fact relevant to this story, 15-20 words>",\n'
        '    "<point 3 - one detailed fact relevant to this story, 15-20 words>"\n'
        "  ],\n"
        '  "video_ids": ["<id1>", "<id2>", "<id3>", "..."]\n'
        "}\n"
        "headline: clean formatted version of the story for on-screen display.\n"
        "panel_label examples by story type:\n"
        "  transfer confirmed -> DEAL POINTS (list fee, contract length, clubs involved)\n"
        "  transfer rumour -> TRANSFER TALK (list interest, asking price, timeline)\n"
        "  manager sacked/appointed -> KEY FACTS (list dates, replacement, record)\n"
        "  match result -> MATCH STATS (list scoreline, scorers, key moments)\n"
        "  injury/squad news -> SQUAD UPDATE (list player, timeline, impact)\n"
        "  club statement -> CLUB NEWS (list what was confirmed, when, next steps)\n"
        "points: 3 short bullet facts shown on screen - match the panel_label context, not script sentences.\n"
        "video_ids: return 4 to 8 unique clip IDs that best match this story visually, in preferred usage order. "
        "Do not repeat clip IDs. If fewer than 4 relevant clips exist, return as many unique clips as possible. "
        "If none fit, use []."
    )
    ranked_clips = _rank_story_clips(clips, item, content_type) if clips else []

    min_words = 50
    data = None
    last_size_error: Exception | None = None
    groq_client = get_groq_client()

    for clip_limit in _CLIP_CONTEXT_LIMITS:
        candidate_clips = ranked_clips[:clip_limit]
        prompt = f"{base_prompt}{_build_clip_block(candidate_clips)}{prompt_suffix}"
        logger.info(
            "Segment script prompt for '%s': using %d/%d clip(s)",
            item.headline[:60],
            len(candidate_clips),
            len(clips or []),
        )
        try:
            for attempt in range(3):
                retry_note = (
                    "\n\nIMPORTANT: Your previous script was too short. "
                    "The script field must be at least 100 words. Write more detail."
                    if attempt > 0 else ""
                )
                response = groq_client.chat.completions.create(
                    model=settings.GROQ_MODEL,
                    messages=[{"role": "user", "content": prompt + retry_note}],
                    max_tokens=1000,
                    temperature=0.7,
                    response_format={"type": "json_object"},
                )
                data = json.loads(response.choices[0].message.content)
                wc_check = _word_count(str(data.get("script", "")))
                if wc_check >= min_words:
                    last_size_error = None
                    break
                logger.warning(
                    "Script too short (%d words) on attempt %d - retrying",
                    wc_check,
                    attempt + 1,
                )
            if data:
                break
        except BadRequestError as exc:
            if "Request too large" not in str(exc):
                raise
            last_size_error = exc
            logger.warning(
                "Segment script prompt too large for '%s' with %d clip(s) - retrying with fewer",
                item.headline[:60],
                len(candidate_clips),
            )

    if last_size_error is not None and not data:
        raise last_size_error

    data = data or {}
    text = str(data.get("script", "")).strip()
    display_headline = str(data.get("headline", "")).strip()
    panel_label = str(data.get("panel_label", "")).strip().upper()
    display_points = [str(p) for p in data.get("points", []) if p][:3]
    wc = _word_count(text)
    estimated_duration = _estimate_duration(wc)
    llm_video_ids = [str(v) for v in data.get("video_ids", []) if v]
    video_ids = _select_covering_clip_ids(
        llm_video_ids,
        clips,
        estimated_duration,
        item,
        content_type,
    )
    logger.info(
        "Segment script: %s | %d words | clips=%s | %s",
        content_type,
        wc,
        video_ids,
        item.headline[:60],
    )
    return Script(
        news_id=item.id,
        script_type=content_type,
        format="segment",
        text=text,
        word_count=wc,
        estimated_duration_seconds=estimated_duration,
        selected_clip_ids=video_ids,
        display_headline=display_headline,
        panel_label=panel_label,
        display_points=display_points,
    )
