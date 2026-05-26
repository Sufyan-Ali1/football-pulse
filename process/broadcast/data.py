"""
Pipeline data helpers — converts Script + NewsItem into the broadcast data dict.
Also usable standalone for any code that needs to prepare broadcast data.
"""
from . import constants as C

_ICON_FILLS = [(160, 0, 0), (30, 30, 30), (30, 30, 30)]

_SPLIT_KEYWORDS = [
    " SIGN", " SIGNS", " CONFIRM", " CONFIRMS",
    " COMPLET", " ANNOUNC", " ANNOUNCES",
    " JOIN", " JOINS", " MOVE", " MOVES",
    " AGREE", " AGREES", " TRANSFER", " APPOINT",
]


def _text_px(text: str, font) -> int:
    """Return pixel width of text using the given PIL font."""
    try:
        return int(font.getlength(text))
    except Exception:
        return len(text) * 30  # rough fallback if font unavailable


def split_headline(headline: str) -> tuple[str, str]:
    """
    Split a raw headline into (white_part, red_part) for the two-line display.
    Searches all word-boundary splits outward from the preferred keyword split
    point until both lines fit within C.HL_MAX_W pixels.
    E.g. 'Man Utd confirm Carrick to stay as head coach'
      -> ('MAN UTD CONFIRM CARRICK', 'TO STAY AS HEAD COACH')
    """
    MAX_W = C.HL_MAX_W
    upper = headline.upper()
    words = upper.split()

    if len(words) <= 1:
        return upper, ""

    # Determine preferred split index from keyword match
    preferred = None
    for kw in _SPLIT_KEYWORDS:
        idx = upper.find(kw)
        if 0 < idx < len(upper) - len(kw):
            preferred = len(upper[:idx].strip().split())
            break
    if preferred is None:
        preferred = min(3, max(1, len(words) // 2))
    preferred = max(1, min(preferred, len(words) - 1))

    # Build search order: preferred first, then expand outward
    search_order = [preferred]
    lo, hi = preferred - 1, preferred + 1
    while lo >= 1 or hi <= len(words) - 1:
        if hi <= len(words) - 1:
            search_order.append(hi); hi += 1
        if lo >= 1:
            search_order.append(lo); lo -= 1

    # Pick the first split where both lines fit
    for i in search_order:
        w = " ".join(words[:i])
        r = " ".join(words[i:])
        if _text_px(w, C.F_HL1) <= MAX_W and _text_px(r, C.F_HL2) <= MAX_W:
            return w, r

    # Fallback: use preferred split and hard-truncate whichever line overflows
    w = " ".join(words[:preferred])
    r = " ".join(words[preferred:])

    if _text_px(w, C.F_HL1) > MAX_W:
        while w and _text_px(w + "...", C.F_HL1) > MAX_W:
            w = w.rsplit(" ", 1)[0] if " " in w else w[:-1]
        w = w + "..."

    if _text_px(r, C.F_HL2) > MAX_W:
        while r and _text_px(r + "...", C.F_HL2) > MAX_W:
            r = r.rsplit(" ", 1)[0] if " " in r else r[:-1]
        r = r + "..."

    return w, r


def build_data_dict(
    script,
    item,
    voiceover_path,
    left_video_path,
    ticker_text: str,
) -> dict:
    """
    Build the broadcast data dict from pipeline objects.

    Args:
        script:          Script dataclass (display_headline, display_points, script_type).
        item:            NewsItem dataclass (source).
        voiceover_path:  Path to MP3 or None.
        left_video_path: Path to left-window MP4 or None.
        ticker_text:     Pre-formatted ticker string.
    """
    hw, hr = split_headline(script.display_headline)
    deal_points = [
        {"text": p, "highlight": None, "icon_fill": _ICON_FILLS[i]}
        for i, p in enumerate(script.display_points[:3])
    ]
    return {
        "headline_white": hw,
        "headline_red":   hr,
        "source":         f"Source: {item.source}",
        "deal_points":    deal_points,
        "ticker":         ticker_text,
        "player_image":   None,
        "left_video":     str(left_video_path) if left_video_path else None,
        "breaking_label": "BREAKING NEWS",
        "deal_label":     script.panel_label,
        "voiceover":      str(voiceover_path) if voiceover_path else None,
    }
