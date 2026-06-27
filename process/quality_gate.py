"""
Deterministic quality checks for news items before they reach video creation.

These rules catch source/format problems that LLM classification is bad at
spotting from headlines alone: video promos, live blogs, paper roundups, and
obvious low-signal Google Alert snippets.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from typing import Literal
from urllib.parse import parse_qs, unquote, urlparse

from core.types import NewsItem

Severity = Literal["reject", "penalty", "ok"]


@dataclass(frozen=True)
class QualityAssessment:
    allowed: bool
    reason: str
    severity: Severity = "ok"
    score_penalty: int = 0


_REJECT = "reject"
_PENALTY = "penalty"
_OK = "ok"

_VIDEO_DOMAINS = (
    "youtube.com",
    "www.youtube.com",
    "m.youtube.com",
    "youtu.be",
)

_SOCIAL_VIDEO_DOMAINS = (
    "tiktok.com",
    "www.tiktok.com",
    "instagram.com",
    "www.instagram.com",
)

_LIVE_URL_PATTERNS = (
    re.compile(r"(?:^|/)live(?:/|$)", re.I),
    re.compile(r"/live-blog(?:/|$)", re.I),
    re.compile(r"/live-updates?(?:/|$)", re.I),
    re.compile(r"/as-it-happened(?:/|$)", re.I),
    re.compile(r"/transfer-centre-live(?:/|$)", re.I),
    re.compile(r"/sport/live(?:/|$)", re.I),
)

_STRICT_NON_FOOTBALL_PATTERNS = (
    re.compile(r"\b(nba|nfl|nhl|mlb|stanley cup|super bowl|world series)\b", re.I),
    re.compile(r"\b(college football|penn state football|iowa football|michigan football|washington football)\b", re.I),
    re.compile(r"\b(wisconsin football|post-hype players|manning passing academy|bluegrass prospect)\b", re.I),
    re.compile(r"\b(kentucky wildcats|mississippi state football|lsu)\b", re.I),
    re.compile(r"\bfootball alliance\b", re.I),
)

_CONTEXTUAL_NON_FOOTBALL_PATTERNS = (
    re.compile(r"\b(heavyweight|boxing|boxer|ufc|mma)\b", re.I),
    re.compile(r"\b(cricket|wicket|bowler|batter|mccullum|jofra archer)\b", re.I),
)

_BAD_TEXT_PATTERNS = (
    (re.compile(r"\btransfer centre live\b", re.I), "transfer_centre_live"),
    (re.compile(r"\blive updates?\b", re.I), "live_updates"),
    (re.compile(r"\blive blog\b", re.I), "live_blog"),
    (re.compile(r"^\s*papers?\s*:", re.I), "paper_roundup"),
    (re.compile(r"\btoday['’]?s papers\b", re.I), "paper_roundup"),
    (re.compile(r"\bpaper talk\b", re.I), "paper_talk"),
    (re.compile(r"\bgossip\b", re.I), "gossip_roundup"),
    (re.compile(r"^\s*watch\s*:", re.I), "watch_item"),
    (re.compile(r"\b(position deep dive|countdown to kickoff|team guide|fairytale journey)\b", re.I), "feature_or_guide"),
    (re.compile(r"\btransfer window\b.*\ball deals\b|\ball deals\b.*\btransfer window\b", re.I), "reference_roundup"),
    (re.compile(r"\bgo to channel\b", re.I), "video_channel_snippet"),
    (re.compile(r"\b\d[\d,]*\s+views\b", re.I), "video_views_snippet"),
)

_WEAK_GOOGLE_SNIPPET_PATTERNS = (
    re.compile(r"\.\.\.", re.I),
    re.compile(r"&middot;", re.I),
    re.compile(r"\bnew\.\s+\d[\d,]*\s+views\b", re.I),
)

_FOOTBALL_SIGNAL_PATTERNS = (
    re.compile(r"\b(world cup|fifa|uefa|football|soccer)\b", re.I),
    re.compile(r"\b(transfer|signing|deal|loan|contract|injury|manager|coach|goal|match|fixture)\b", re.I),
    re.compile(r"\b(messi|ronaldo|haaland|mbappe|salah|england|france|argentina|chelsea|arsenal|liverpool|barcelona|real madrid)\b", re.I),
)


def _clean_text(text: str | None) -> str:
    if not text:
        return ""
    text = html.unescape(re.sub(r"<[^>]+>", " ", text))
    return " ".join(text.split())


def _target_url(url: str) -> str:
    """Return the final URL embedded in Google redirect links when present."""
    if not url:
        return ""
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    if host.endswith("google.com") and parsed.path.startswith("/url"):
        target = parse_qs(parsed.query).get("url", [""])[0]
        if target:
            return unquote(target)
    return url


def _is_video_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    return host in _VIDEO_DOMAINS or any(host.endswith("." + d) for d in _VIDEO_DOMAINS)


def _is_social_video_url(url: str) -> bool:
    parsed = urlparse(url)
    host = parsed.netloc.lower()
    return host in _SOCIAL_VIDEO_DOMAINS or any(host.endswith("." + d) for d in _SOCIAL_VIDEO_DOMAINS)


def _looks_like_article_url(url: str) -> bool:
    parsed = urlparse(url)
    return parsed.scheme in {"http", "https"} and bool(parsed.netloc)


def _is_live_blog_url(url: str) -> bool:
    path = urlparse(url).path or ""
    return any(pattern.search(path) for pattern in _LIVE_URL_PATTERNS)


def _bad_url_reason(url: str) -> str | None:
    target = _target_url(url)
    if not _looks_like_article_url(target):
        return "bad_url_format"
    if _is_video_url(target) or _is_social_video_url(target):
        return "video_url"
    if _is_live_blog_url(target):
        return "bad_url_format"
    return None


def _is_google_alert(item: NewsItem, source: str) -> bool:
    return item.source_type == "google_alerts" or source == "Google Alerts"


def _has_football_signal(text: str) -> bool:
    return any(pattern.search(text) for pattern in _FOOTBALL_SIGNAL_PATTERNS)


def _non_football_reason(text: str) -> str | None:
    if any(pattern.search(text) for pattern in _STRICT_NON_FOOTBALL_PATTERNS):
        return "non_football_sport"
    if not _has_football_signal(text) and any(pattern.search(text) for pattern in _CONTEXTUAL_NON_FOOTBALL_PATTERNS):
        return "non_football_sport"
    return None


def assess_item_quality(item: NewsItem) -> QualityAssessment:
    """Assess a fetched NewsItem before it is stored or ranked."""
    source = (item.source or "").strip()
    headline = _clean_text(item.headline)
    body = _clean_text(item.body)
    combined = f"{headline} {body}".strip()

    reason = _bad_url_reason(item.url)
    if reason:
        return QualityAssessment(False, reason, _REJECT)

    reason = _non_football_reason(combined)
    if reason:
        return QualityAssessment(False, reason, _REJECT)

    for pattern, pattern_reason in _BAD_TEXT_PATTERNS:
        if pattern.search(combined):
            return QualityAssessment(False, pattern_reason, _REJECT)

    if _is_google_alert(item, source):
        has_football_signal = _has_football_signal(combined)
        weak_snippet = any(p.search(combined) for p in _WEAK_GOOGLE_SNIPPET_PATTERNS)
        if len(body) < 35 and not has_football_signal:
            return QualityAssessment(False, "google_alert_thin_body", _REJECT)
        if weak_snippet and not has_football_signal:
            return QualityAssessment(False, "google_alert_weak_snippet", _REJECT)
        if len(body) < 120 or weak_snippet:
            return QualityAssessment(True, "google_alert_weak_snippet", _PENALTY, -10)
        return QualityAssessment(True, "google_alert_low_trust", _PENALTY, -20)

    return QualityAssessment(True, "ok", _OK, 0)


def assess_article_row_quality(row) -> QualityAssessment:
    """Assess a sqlite Row from articles using the same deterministic rules."""
    item = NewsItem(
        id=row["id"],
        headline=row["headline"] or "",
        body=row["body"] or "",
        url=row["url"] or "",
        source=row["source"] or "",
        source_type=row["source_type"] or "rss",
        timestamp=row["timestamp"],
    )
    return assess_item_quality(item)
