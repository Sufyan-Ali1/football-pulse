"""
Shared constants for the entire pipeline.
Define once here — never duplicate across modules.
"""

# ── Classification signals ────────────────────────────────────────────────────

DEAL_DONE_SIGNALS: list[str] = [
    "here we go", "done deal", "agreement reached", "deal signed", "medicals",
    "officially unveiled",
    "signs for", "joins on a", "world record fee", "breaks transfer record",
    "transfer confirmed", "deal done", "completed signing", "unveiled as",
    "officially joins", "announce the signing",
]

MANAGER_SACKED_SIGNALS: list[str] = [
    "sacked", "dismissed", "parted ways", "relieved of duties",
    "sacked as manager", "sacked as head coach",
    "managerial departure", "no longer manager", "leaves by mutual consent",
]

MANAGER_APPOINTED_SIGNALS: list[str] = [
    "appointed as manager", "appointed as head coach", "named as new manager",
    "named as head coach", "takes charge as manager", "takes charge as head coach",
    "officially appointed", "confirmed as manager", "new manager confirmed", "named manager",
]

CONTRACT_EXTENSION_SIGNALS: list[str] = [
    "signs new contract", "contract extension",
    "extended his contract", "signed a new deal", "penned new deal",
    "contract renewal", "keeps him until", "new deal until",
    "signs contract extension", "contract signed",
]

INJURY_FITNESS_SIGNALS: list[str] = [
    "ruled out", "fitness doubt", "fitness concern", "out for",
    "undergone surgery", "picked up an injury", "returns from injury",
    "back in training", "injury blow", "miss the match",
    "injury update", "on the injury",
]

CLUB_STATEMENT_SIGNALS: list[str] = [
    "club confirm", "official statement", "officially announce", "club announce",
    "the club have confirmed", "officially released", "statement from the club",
    "club release statement",
]

BREAKING_SIGNALS: list[str] = [
    "breaking", "exclusive", "just in", "developing story",
]

TRANSFER_SIGNALS: list[str] = [
    "transfer", "signing", "loan", "bid", "fee", "move", "linked",
    "interest", "talks", "negotiations", "wanted", "target",
    "offer", "approach", "bid rejected", "clause", "deal",
]

# All valid content type strings — single source of truth for classifier and verifier validation.
VALID_CONTENT_TYPES: list[str] = [
    "deal_done", "transfer_rumour", "breaking_news", "manager_sacked",
    "manager_appointed", "contract_extension", "injury_fitness", "club_statement", "tactical",
]

TACTICAL_SIGNALS: list[str] = [
    "match report", "tactical", "formation", "press conference",
    "lineup", "starting eleven", "substitution", "tactics",
    "analysis", "performance", "rating",
]

# Non-football sports — heavy penalty so these never reach BREAKING_SCORE_THRESHOLD
NON_FOOTBALL_SPORT_SIGNALS: list[str] = [
    "stanley cup", "nhl", "nba", "nfl", "mlb",
    "super bowl", "superbowl", "world series",
    "ice hockey", "basketball",
    "formula 1", "formula one", "grand prix",
    "ufc", " mma ", "boxing champion",
    "rugby union", "rugby league",
    "cricket test", "cricket match",
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
    "Fabrizio Romano (Nitter)": 60,
    "David Ornstein (Nitter)":  58,
    "Ben Jacobs (Nitter)":      56,
    "Laurie Whitwell (Nitter)": 54,
    "Sky Sports Football":       57,
    "Sky Sports Football News":  55,
    "BBC Sport Football":        54,
    "The Guardian Football":     52,
    "ESPN FC":                   50,
    "Google Alerts":             25,
    "TalkSport":                 46,
    "90min":                     44,
    "Football Italia":           42,
}
DEFAULT_SOURCE_SCORE: int = 35

# ── Stop-words stripped before similarity comparison (ranker) ─────────────────

STOP_WORDS: set[str] = {
    "the", "a", "an", "is", "in", "on", "at", "to", "for", "of",
    "and", "or", "but", "it", "he", "she", "we", "are", "was", "has",
    "have", "be", "been", "that", "this", "with", "from", "as",
}
