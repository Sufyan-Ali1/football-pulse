"""
Animation helpers — pure functions, no global state.
Reusable for any video type that needs wipe/reveal effects.
"""
import numpy as np
from PIL import Image, ImageDraw

from . import constants as C


def reveal(t: float, start: float, dur: float) -> float:
    """Return 0.0 → 1.0 progress over [start, start+dur]."""
    if t <= start:
        return 0.0
    if t >= start + dur:
        return 1.0
    return (t - start) / dur


def composite_revealed(img: Image.Image, layer: Image.Image,
                       x_start: int, x_end: int, fraction: float) -> None:
    """Alpha-composite layer onto img clipped to a left-to-right wipe mask."""
    if fraction <= 0:
        return
    if fraction >= 1.0:
        img.alpha_composite(layer)
        return
    reveal_x = int(x_start + (x_end - x_start) * fraction)
    mask = Image.new("L", img.size, 0)
    ImageDraw.Draw(mask).rectangle([0, 0, reveal_x, img.height], fill=255)
    l_arr = np.array(layer)
    l_arr[:, :, 3] = np.minimum(l_arr[:, :, 3], np.array(mask))
    img.alpha_composite(Image.fromarray(l_arr))


def build_dp_anim(data: dict) -> list:
    """
    Pre-compute per-line timing for all deal points.

    Returns list of (row_index, centre_y, point_dict, line_entries) where
    line_entries = [(start_t, is_first_line, line_text, line_y), ...]
    """
    d = ImageDraw.Draw(Image.new("RGBA", (1, 1)))

    def _wrap(text: str) -> list[str]:
        words = text.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w).strip()
            bb = d.textbbox((0, 0), test, font=C.F_PT)
            if bb[2] - bb[0] <= C.TEXT_W:
                cur = test
            else:
                if cur:
                    lines.append(cur)
                cur = w
        if cur:
            lines.append(cur)
        return lines

    result    = []
    running_t = 3 * C.ANIM_DUR + 0.2   # 0.2 s gap after source finishes
    for i, pt in enumerate(data["deal_points"]):
        lines = _wrap(pt["text"])
        cy    = C.ROW_CY[i]
        blk_h = len(lines) * 32
        cur_y = max(cy - C.CIRC_R, cy - blk_h // 2)
        entries = []
        for j, ln in enumerate(lines):
            bb = d.textbbox((0, 0), ln, font=C.F_PT)
            entries.append((running_t, j == 0, ln, cur_y))
            running_t += C.LINE_DUR
            cur_y += (bb[3] - bb[1]) + 5
        result.append((i, cy, pt, entries))
        running_t += 0.3   # gap between deal points
    return result
