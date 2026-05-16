"""
Shared constants for the entire pipeline.
Define once here — never duplicate across modules.
"""

# ── Classification signals ────────────────────────────────────────────────────

BREAKING_SIGNALS: list[str] = [
    "here we go", "confirmed", "done deal", "official", "breaking",
    "agreement reached", "deal signed", "medicals", "contract signed",
    "announced", "unveiled", "sacked", "appointed",
]

TRANSFER_SIGNALS: list[str] = [
    "transfer", "signing", "loan", "bid", "fee", "move", "linked",
    "interest", "talks", "negotiations", "wanted", "target",
    "deal", "offer", "approach", "bid rejected", "clause",
]

TACTICAL_SIGNALS: list[str] = [
    "match report", "tactical", "formation", "press conference",
    "lineup", "starting eleven", "substitution", "tactics",
    "analysis", "performance", "rating",
]

# ── Source quality tiers (used by ranker) ─────────────────────────────────────

SOURCE_TIERS: dict[str, int] = {
    "Sky Sports Football":    90,
    "BBC Sport Football":     85,
    "The Guardian Football":  80,
    "ESPN FC":                75,
    "Google Alerts":          70,
    "TalkSport":              65,
    "90min":                  60,
    "Football Italia":        55,
}
DEFAULT_SOURCE_SCORE: int = 40

# ── Stop-words stripped before similarity comparison (ranker) ─────────────────

STOP_WORDS: set[str] = {
    "the", "a", "an", "is", "in", "on", "at", "to", "for", "of",
    "and", "or", "but", "it", "he", "she", "we", "are", "was", "has",
    "have", "be", "been", "that", "this", "with", "from", "as",
}

# ── Content-type badge labels (used by video_editor and thumbnail) ────────────

BADGE_LABELS: dict[str, str] = {
    "breaking_news":   "BREAKING NEWS",
    "transfer_rumour": "TRANSFER NEWS",
    "club_update":     "CLUB UPDATE",
    "tactical":        "TACTICAL ANALYSIS",
}
