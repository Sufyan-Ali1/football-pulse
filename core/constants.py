"""
Shared constants for the entire pipeline.
Define once here — never duplicate across modules.
"""

# ── Classification signals ────────────────────────────────────────────────────

BREAKING_SIGNALS: list[str] = [
    "here we go",
    "done deal",
    "agreement reached",
    "deal signed",
    "medicals",
    "contract signed",
    "officially confirmed",
    "officially unveiled",
    "officially appointed",
    "officially sacked",
    "sacked as manager",
    "sacked as head coach",
    "appointed as manager",
    "appointed as head coach",
    "signs for",
    "joins on a",
    "world record fee",
    "breaks transfer record",
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

# Signals that indicate low viewer interest — used to penalise rank score
LOW_INTEREST_SIGNALS: list[str] = [
    "how to watch",
    "where to watch",
    "live stream guide",
    "tv schedule",
    "fantasy football",
    "betting tips",
    "fixture list",
    "fixtures and results",
    "on this day",
    "years ago today",
    "throwback",
    "flashback",
    "tickets on sale",
    "buy tickets",
    "kit review",
    "boots review",
    "top 10",
    "best football",
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
