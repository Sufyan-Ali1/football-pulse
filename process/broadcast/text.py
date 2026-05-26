"""
PIL drawing helpers — stateless, reusable across any video template.
"""
from PIL import ImageDraw


def draw_wrapped(draw: ImageDraw.ImageDraw, x: int, y: int, text: str, font,
                 max_w: int, fill=(255, 255, 255, 255), highlight: str | None = None,
                 hi_color=(220, 0, 0, 255), line_gap: int = 6) -> int:
    """
    Draw word-wrapped text, optionally highlighting a specific phrase in red.
    Returns the y position after the last line.
    """
    words = text.split()
    lines, cur = [], ""
    for w in words:
        test = (cur + " " + w).strip()
        bb   = draw.textbbox((0, 0), test, font=font)
        if bb[2] - bb[0] <= max_w:
            cur = test
        else:
            if cur:
                lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)

    cy = y
    for ln in lines:
        if highlight and highlight in ln:
            before, _, after = ln.partition(highlight)
            cx = x
            for seg, col in [(before, fill), (highlight, hi_color), (after, fill)]:
                if seg:
                    draw.text((cx, cy), seg, fill=col, font=font)
                    bb = draw.textbbox((cx, cy), seg, font=font)
                    cx = bb[2]
        else:
            draw.text((x, cy), ln, fill=fill, font=font)
        bb  = draw.textbbox((0, 0), ln, font=font)
        cy += (bb[3] - bb[1]) + line_gap
    return cy


def draw_circle_icon(draw: ImageDraw.ImageDraw, cx: int, cy: int,
                     r: int, fill: tuple, icon_type: int = 0) -> None:
    """Draw a coloured circle icon with a decorative inner shape."""
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], fill=(*fill, 255))
    draw.ellipse([cx-r, cy-r, cx+r, cy+r], outline=(200, 0, 0, 255), width=3)
    s = r // 2
    if icon_type == 0:
        pts = [(cx, cy-s), (cx+s, cy-s//2),
               (cx+s, cy+s//3), (cx, cy+s), (cx-s, cy+s//3), (cx-s, cy-s//2)]
        draw.polygon(pts, outline=(255, 255, 255, 200), width=2)
    elif icon_type == 1:
        for dy in [-s//2, 0, s//2]:
            draw.line([(cx-s+4, cy+dy), (cx+s-4, cy+dy)],
                      fill=(255, 255, 255, 200), width=2)
    else:
        draw.ellipse([cx-s//2, cy-s, cx+s//2, cy],
                     outline=(255, 255, 255, 200), width=2)
        draw.arc([cx-s, cy, cx+s, cy+s+s//2], 0, 180,
                 fill=(255, 255, 255, 200), width=2)
