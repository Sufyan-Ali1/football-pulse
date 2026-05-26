"""
Scrolling ticker strip — build once, draw per frame.
"""
import numpy as np
from PIL import Image, ImageDraw

from . import constants as C


def build_ticker(data: dict) -> tuple[Image.Image, int]:
    """Render the full ticker text onto an off-screen strip. Returns (strip, width)."""
    dummy = ImageDraw.Draw(Image.new("RGBA", (1, 1)))
    tb    = dummy.textbbox((0, 0), data["ticker"], font=C.F_TICK)
    tw    = tb[2] - tb[0] + 60
    strip = Image.new("RGBA", (tw, C.TICKER_H), (0, 0, 0, 0))
    d     = ImageDraw.Draw(strip)
    ty    = (C.TICKER_H - (tb[3] - tb[1])) // 2 - tb[1]
    d.text((20, ty), data["ticker"], fill=(255, 255, 255, 255), font=C.F_TICK)
    return strip, tw


def draw_ticker(img: Image.Image, ticker_img: Image.Image,
                ticker_w: int, t: float) -> Image.Image:
    """
    Composite the scrolling ticker onto img at the current time t.
    Returns the (potentially new) composited img.
    """
    total    = C.TICKER_RIGHT + ticker_w
    scrolled = int(t * C.TICKER_SPEED) % total
    tx       = C.TICKER_RIGHT - scrolled

    dst_x  = max(tx, 0)
    src_x1 = max(0, -tx)
    src_x2 = min(ticker_w, C.TICKER_RIGHT - tx)

    if src_x2 <= src_x1 or tx >= C.TICKER_RIGHT:
        return img

    strip      = ticker_img.crop((src_x1, 0, src_x2, C.TICKER_H))
    tick_layer = Image.new("RGBA", (C.W, C.H), (0, 0, 0, 0))
    tick_layer.paste(strip, (dst_x, C.TICKER_Y), strip)

    slant_poly = [
        (C.TICK_SLANT_TOP_X, C.TICKER_Y),
        (C.TICKER_RIGHT,     C.TICKER_Y),
        (C.TICKER_RIGHT,     C.TICKER_Y + C.TICKER_H),
        (C.TICK_SLANT_BOT_X, C.TICKER_Y + C.TICKER_H),
    ]
    pmask = Image.new("L", (C.W, C.H), 0)
    ImageDraw.Draw(pmask).polygon(slant_poly, fill=255)
    t_arr = np.array(tick_layer)
    t_arr[:, :, 3] = np.minimum(t_arr[:, :, 3], np.array(pmask))
    return Image.alpha_composite(img, Image.fromarray(t_arr))
