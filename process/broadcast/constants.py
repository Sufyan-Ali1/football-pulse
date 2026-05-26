"""
Canvas dimensions, coordinate constants, animation timing, and fonts.
All other broadcast modules import from here — nothing else defines layout.
"""
from pathlib import Path
from PIL import ImageFont

# ── Canvas ────────────────────────────────────────────────────────────────────
W, H = 1920, 1080
FPS  = 24

# ── Left video window ─────────────────────────────────────────────────────────
VID_X1, VID_Y1 = 86,  465
VID_X2, VID_Y2 = 1110, 937
VID_W = VID_X2 - VID_X1
VID_H = VID_Y2 - VID_Y1

# ── Headline ──────────────────────────────────────────────────────────────────
HL_X,   HL_Y   = 85, 265
HL_MAX_W       = 1050   # safe up to SEP_X1 (1216) - HL_X (85) = 1131

# ── Source text ───────────────────────────────────────────────────────────────
SRC_X, SRC_Y = 85, 422

# ── Date (top bar) ────────────────────────────────────────────────────────────
DATE_X, DATE_Y = 1442, 40

# ── Right panel deal-point rows ───────────────────────────────────────────────
CIRC_X = 1248
CIRC_R = 32
ROW_CY = [298, 427, 556]
TEXT_X = CIRC_X + CIRC_R + 14   # 1294
TEXT_W = 515

# ── Separator lines ───────────────────────────────────────────────────────────
SEP_X1 = CIRC_X - CIRC_R        # 1216
SEP_X2 = TEXT_X + TEXT_W        # 1809
SEP_Y  = [(ROW_CY[0] + ROW_CY[1]) // 2,
           (ROW_CY[1] + ROW_CY[2]) // 2]

# ── Ticker strip ──────────────────────────────────────────────────────────────
TICKER_Y     = 983
TICKER_H     = 68
TICKER_LEFT  = 275
TICKER_RIGHT = 1890
TICKER_SPEED = 130
TICK_SLANT_TOP_X = 262
TICK_SLANT_BOT_X = 244

# ── Badge positions ───────────────────────────────────────────────────────────
BADGE_CX     = 145
BADGE_CY     = 1016
TOP_BADGE_CX = 247
TOP_BADGE_CY = 165

# ── Right panel top-bar (BREAKING label + blinking dot) ───────────────────────
BRK_R_CX = 1746
BRK_R_CY = 55

# ── Deal label ────────────────────────────────────────────────────────────────
DEAL_LBL_X = 1230
DEAL_LBL_Y = 165

# ── Animation timing ──────────────────────────────────────────────────────────
ANIM_DUR = 0.7   # seconds per headline/source wipe
LINE_DUR = 0.4   # seconds per deal-point line wipe

# ── Fonts ─────────────────────────────────────────────────────────────────────
_FONTS = Path("C:/Windows/Fonts")


def load_font(size: int, bold: bool = False, italic: bool = False) -> ImageFont.FreeTypeFont:
    cands = []
    if not bold and not italic:
        cands += [_FONTS / "impact.ttf", _FONTS / "IMPACT.TTF"]
    if bold and italic:
        cands += [_FONTS / "arialbi.ttf", _FONTS / "ARIALBI.TTF"]
    elif bold:
        cands += [_FONTS / "arialbd.ttf", _FONTS / "ARIALBD.TTF"]
    elif italic:
        cands += [_FONTS / "ariali.ttf",  _FONTS / "ARIALI.TTF"]
    cands += [_FONTS / "arial.ttf", _FONTS / "ARIAL.TTF"]
    for p in cands:
        try:
            return ImageFont.truetype(str(p), size)
        except Exception:
            pass
    return ImageFont.load_default()


F_HL1   = load_font(68, bold=True)
F_HL2   = load_font(58, bold=True)
F_SRC   = load_font(24)
F_PT    = load_font(26)
F_TICK  = load_font(38, bold=True)
F_BRK_R = load_font(26, bold=True)
F_DEAL  = load_font(44, bold=True)
F_BADGE = load_font(34, bold=True)   # bottom + top-left badge text
