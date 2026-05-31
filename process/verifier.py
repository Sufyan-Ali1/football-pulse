"""
2nd-pass Groq verifier.

After the classifier's 1st pass, this module re-checks articles that were
classified by keyword or groq_batch (never groq_verified) in batches of 5.

Groq sees each article's current classification and either confirms it or
corrects it. The DB is updated in place — nothing is wasted:
  - Confirmed articles keep their type, get classified_by='groq_verified'
  - Corrected articles get the right type + classified_by='groq_verified'

Because classified_by is persisted, an article is NEVER sent to Groq twice.
"""
import json
import logging
import sqlite3

from clients.groq_client import get_groq_client
from config import settings
from core.constants import VALID_CONTENT_TYPES
from core.database import bulk_update_article_classifications, get_articles_by_ids
from core.types import ContentType

logger = logging.getLogger(__name__)

_groq = get_groq_client()

_VALID = VALID_CONTENT_TYPES

_VERIFY_PROMPT = """You are quality-checking football news article classifications for a YouTube channel.
For each article return two things: the CORRECT category, and a relevance score (1-10).

IMPORTANT: If an article is NOT about football at all, assign relevance 1 — it will be filtered out.

Categories:
- deal_done          → confirmed/completed transfer signing, "here we go", medicals done, player unveiled
- transfer_rumour    → unconfirmed: transfer links, bids, interest, negotiations, speculation
- breaking_news      → confirmed breaking football event not covered by other specific types
- manager_sacked     → manager dismissed, sacked, relieved of duties, parted ways
- manager_appointed  → manager appointed, named, takes charge of a club
- contract_extension → player or manager signs contract extension or renewal
- injury_fitness     → injury news, fitness updates, player ruled out, return from injury
- club_statement     → official club announcement, statement, or press release
- tactical           → match results, match reports, analysis, formations, post-match reaction

Relevance score (viewer interest for a football news YouTube channel):
- 9-10: Must cover — confirmed big transfer, major sacking, title win, historic result
- 7-8:  Strong story — interesting rumour, big match result, key injury to star player
- 5-6:  Decent story — minor squad news, mid-table result, small club update
- 3-4:  Weak — generic analysis, obscure club, very low viewer interest
- 1-2:  Skip — not football, fixture lists, kit reviews, betting tips, throwbacks, merchandise, fantasy football

Key rules:
- Match results and cup finals are ALWAYS tactical, never deal_done or breaking_news
- "Confirmed" in a match/analysis context is NOT deal_done
- Kit releases and merchandise are club_statement, relevance 1-3
- Non-football articles get relevance 1 regardless of category

Articles (format: "N. [current: TYPE] Headline"):
{lines}

Respond with ONLY a JSON object. Example:
{{"1": {{"type": "deal_done", "relevance": 10}}, "2": {{"type": "transfer_rumour", "relevance": 7}}}}
No explanation. No other text."""


def _groq_verify_batch(
    articles: list[sqlite3.Row],
) -> dict[str, tuple[ContentType, int]]:
    """
    Send one batch of up to 5 articles to Groq for verification.
    Returns {article_id: (content_type, relevance_score)}.
    """
    lines = "\n".join(
        f"{i}. [current: {a['content_type']}] {a['headline']}"
        for i, a in enumerate(articles, start=1)
    )
    result: dict[str, tuple[ContentType, int]] = {}

    try:
        response = _groq.chat.completions.create(
            model=settings.GROQ_MODEL,
            messages=[{"role": "user", "content": _VERIFY_PROMPT.format(lines=lines)}],
            max_tokens=120,
            temperature=0,
        )
        parsed: dict = json.loads(response.choices[0].message.content.strip())
        for idx_str, entry in parsed.items():
            idx = int(idx_str) - 1
            if 0 <= idx < len(articles):
                article = articles[idx]
                cat = str(entry.get("type", "")).lower().strip()
                rel = int(entry.get("relevance", 5))
                result[article["id"]] = (
                    cat if cat in _VALID else article["content_type"],
                    max(1, min(10, rel)),
                )
    except Exception as e:
        logger.warning("Groq verify batch failed: %s - keeping current classifications", e)
        for a in articles:
            result[a["id"]] = (a["content_type"], 5)

    return result


def verify_and_reclassify(
    articles: list[sqlite3.Row],
    batch_size: int = 5,
) -> list[sqlite3.Row]:
    """
    Run 2nd-pass Groq verification on articles not yet groq_verified.
    Updates each article in the DB (content_type + classified_by='groq_verified').
    Returns fresh rows from DB with corrected data.
    """
    to_verify = [a for a in articles if a["classified_by"] != "groq_verified"]
    already_done = [a for a in articles if a["classified_by"] == "groq_verified"]

    if not to_verify:
        return articles

    corrected = 0
    all_verified_ids: list[str] = [a["id"] for a in already_done]
    bulk_updates: list[tuple[str, str, str, int | None]] = []

    for start in range(0, len(to_verify), batch_size):
        batch = to_verify[start:start + batch_size]
        corrections = _groq_verify_batch(batch)

        for article in batch:
            old_type = article["content_type"]
            new_type, relevance = corrections.get(article["id"], (old_type, 5))
            bulk_updates.append((article["id"], new_type, "groq_verified", relevance))
            if new_type != old_type:
                corrected += 1
                logger.info(
                    "Reclassified [%s -> %s, relevance=%d]: %s",
                    old_type, new_type, relevance, article["headline"][:70],
                )
            else:
                logger.debug(
                    "Confirmed [%s, relevance=%d]: %s",
                    new_type, relevance, article["headline"][:70],
                )
            all_verified_ids.append(article["id"])

    # One DB call for all updates instead of one per article
    bulk_update_article_classifications(bulk_updates)

    if corrected:
        logger.info("Verifier: corrected %d / %d articles", corrected, len(to_verify))
    else:
        logger.info("Verifier: all %d classifications confirmed", len(to_verify))

    # Re-fetch so callers get updated content_type values
    return get_articles_by_ids(all_verified_ids)
