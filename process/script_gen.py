"""
Script generator — Step 4.

Calls Groq to produce two scripts per NewsItem:
  main  — full 60s or 2-3 min script depending on content type
  short — 15-second short-form script for Shorts/Reels/TikTok

Prompt templates live in config/prompts/ and are loaded at call time.
"""
import logging
from pathlib import Path

from openai import OpenAI

from config import settings
from core.types import ContentType, NewsItem, Script

logger = logging.getLogger(__name__)

_groq = OpenAI(api_key=settings.GROQ_API_KEY, base_url="https://api.groq.com/openai/v1")

_PROMPTS_DIR = Path(__file__).resolve().parent.parent / "config" / "prompts"

# Content type → prompt template filename
_PROMPT_MAP: dict[str, str] = {
    "breaking_news":   "breaking_news.txt",
    "transfer_rumour": "analysis.txt",
    "club_update":     "analysis.txt",
    "tactical":        "analysis.txt",
}


def _load_prompt(filename: str) -> str:
    return (_PROMPTS_DIR / filename).read_text(encoding="utf-8")


def _render(template: str, item: NewsItem, content_type: ContentType) -> str:
    return template.format(
        brand_name=settings.BRAND_NAME,
        brand_tagline=settings.BRAND_TAGLINE,
        headline=item.headline,
        body=item.body[:1000],
        source=item.source,
        content_type=content_type,
    )


def _call_groq(prompt: str, max_tokens: int = 600) -> str:
    response = _groq.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


def _word_count(text: str) -> int:
    return len(text.split())


def _estimate_duration(wc: int) -> int:
    return round(wc / 2.5)  # ~2.5 words/second for news delivery


def generate_main_script(item: NewsItem, content_type: ContentType) -> Script:
    template = _load_prompt(_PROMPT_MAP[content_type])
    prompt   = _render(template, item, content_type)
    max_tok  = 200 if content_type == "breaking_news" else 600
    text     = _call_groq(prompt, max_tokens=max_tok)
    wc       = _word_count(text)
    logger.info("Main script: %s | %d words | %s", content_type, wc, item.headline[:60])
    return Script(
        news_id=item.id, script_type=content_type, format="main",
        text=text, word_count=wc, estimated_duration_seconds=_estimate_duration(wc),
    )


def generate_short_script(item: NewsItem, content_type: ContentType) -> Script:
    template = _load_prompt("short_form.txt")
    prompt   = _render(template, item, content_type)
    text     = _call_groq(prompt, max_tokens=80)
    wc       = _word_count(text)
    logger.info("Short script: %d words | %s", wc, item.headline[:60])
    return Script(
        news_id=item.id, script_type=content_type, format="short",
        text=text, word_count=wc, estimated_duration_seconds=15,
    )


def generate_all_scripts(item: NewsItem, content_type: ContentType) -> tuple[Script, Script]:
    """Returns (main_script, short_script)."""
    return generate_main_script(item, content_type), generate_short_script(item, content_type)
