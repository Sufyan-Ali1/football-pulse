"""
Canvas dimensions, coordinate constants, animation timing, and fonts.
All other broadcast modules import from here — nothing else defines layout.
"""
from pathlib import Path
from PIL import ImageFont

# ── Canvas ────────────────────────────────────────────────────────────────────
W, H = 1920, 1080
FPS  = 24

# Right-panel accent used by the blinking dot, separators, and point icons
RIGHT_PANEL_ACCENT = (0x54, 0xB7, 0x1D)
HEADLINE_ACCENT = RIGHT_PANEL_ACCENT

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
DEAL_LBL_X          = 1230
DEAL_LBL_Y          = 165   # kept for reference; compositor uses DEAL_LBL_BANNER_CY
# Banner measured from frame.png: x=1230→1577 (347px), y=158→217 (60px tall).
DEAL_LBL_MAX_W      = 325   # 347px - 22px right padding
DEAL_LBL_BANNER_CY  = 185   # vertical center of the banner, shifted 2px up

# ── Animation timing ──────────────────────────────────────────────────────────
ANIM_DUR = 0.7   # seconds per headline/source wipe
LINE_DUR = 0.4   # seconds per deal-point line wipe

# ── Fonts ─────────────────────────────────────────────────────────────────────
import sys as _sys

_WIN_FONTS  = Path("C:/Windows/Fonts")
_PROJ_FONTS = Path(__file__).resolve().parent.parent.parent / "config" / "fonts"
_LINUX_FONTS = [
    Path("/usr/share/fonts/truetype/msttcorefonts"),
    Path("/usr/share/fonts/truetype/freefont"),
    Path("/usr/share/fonts"),
]


def load_font(size: int, bold: bool = False, italic: bool = False) -> ImageFont.FreeTypeFont:
    cands = []

    def _from(folder: Path) -> None:
        if not bold and not italic:
            cands.extend([folder / "impact.ttf", folder / "Impact.ttf", folder / "IMPACT.TTF"])
        if bold and italic:
            cands.extend([folder / "arialbi.ttf", folder / "ARIALBI.TTF"])
        elif bold:
            cands.extend([folder / "arialbd.ttf", folder / "ARIALBD.TTF",
                          folder / "Arial_Bold.ttf", folder / "FreeSansBold.ttf"])
        elif italic:
            cands.extend([folder / "ariali.ttf", folder / "ARIALI.TTF"])
        cands.extend([folder / "arial.ttf", folder / "Arial.ttf", folder / "ARIAL.TTF",
                      folder / "FreeSans.ttf"])

    # Project-bundled fonts take priority (works on any OS)
    _from(_PROJ_FONTS)

    # OS font directories
    if _sys.platform == "win32":
        _from(_WIN_FONTS)
    else:
        for d in _LINUX_FONTS:
            _from(d)

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
