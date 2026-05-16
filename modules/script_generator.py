"""
Groq script generator.
Reads prompt templates from config/prompts/ and generates all 3 script formats
for a given NewsItem: main script (breaking/analysis) + short-form (15s).
"""
import logging
from dataclasses import dataclass
from pathlib import Path

from openai import OpenAI

from config import settings
from modules.news_monitor import NewsItem
from pipeline.content_classifier import ContentType

logger = logging.getLogger(__name__)

# Groq is OpenAI-compatible — same client, different base URL and model
_groq_client = OpenAI(
    api_key=settings.GROQ_API_KEY,
    base_url="https://api.groq.com/openai/v1",
)

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "config" / "prompts"

# Maps content type → prompt template filename
PROMPT_MAP: dict[ContentType, str] = {
    "breaking_news":   "breaking_news.txt",
    "transfer_rumour": "analysis.txt",
    "club_update":     "analysis.txt",
    "tactical":        "analysis.txt",
}


@dataclass
class Script:
    news_id: str
    script_type: ContentType
    format: str          # "main" | "short"
    text: str
    word_count: int
    estimated_duration_seconds: int


def _load_prompt(template_file: str) -> str:
    return (PROMPTS_DIR / template_file).read_text(encoding="utf-8")


def _render_prompt(template: str, item: NewsItem, content_type: ContentType) -> str:
    return template.format(
        brand_name=settings.BRAND_NAME,
        brand_tagline=settings.BRAND_TAGLINE,
        headline=item.headline,
        body=item.body[:1000],
        source=item.source,
        content_type=content_type,
    )


def _call_groq(prompt: str, max_tokens: int = 600) -> str:
    response = _groq_client.chat.completions.create(
        model=settings.GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        max_tokens=max_tokens,
        temperature=0.7,
    )
    return response.choices[0].message.content.strip()


def _word_count(text: str) -> int:
    return len(text.split())


def _estimate_duration(word_count: int) -> int:
    # Average speaking pace: ~2.5 words/second for news delivery
    return round(word_count / 2.5)


def generate_main_script(item: NewsItem, content_type: ContentType) -> Script:
    template_file = PROMPT_MAP[content_type]
    template = _load_prompt(template_file)
    prompt = _render_prompt(template, item, content_type)

    max_tokens = 200 if content_type == "breaking_news" else 600
    text = _call_groq(prompt, max_tokens=max_tokens)
    wc = _word_count(text)

    logger.info("Generated %s script for '%s' (%d words)", content_type, item.headline[:60], wc)
    return Script(
        news_id=item.id,
        script_type=content_type,
        format="main",
        text=text,
        word_count=wc,
        estimated_duration_seconds=_estimate_duration(wc),
    )


def generate_short_script(item: NewsItem, content_type: ContentType) -> Script:
    template = _load_prompt("short_form.txt")
    prompt = _render_prompt(template, item, content_type)
    text = _call_groq(prompt, max_tokens=80)
    wc = _word_count(text)

    logger.info("Generated short script for '%s' (%d words)", item.headline[:60], wc)
    return Script(
        news_id=item.id,
        script_type=content_type,
        format="short",
        text=text,
        word_count=wc,
        estimated_duration_seconds=15,
    )


def generate_all_scripts(item: NewsItem, content_type: ContentType) -> tuple[Script, Script]:
    """Returns (main_script, short_script)."""
    main = generate_main_script(item, content_type)
    short = generate_short_script(item, content_type)
    return main, short
