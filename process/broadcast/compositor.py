"""
Per-frame compositor — returns a make_frame(t) closure.
All rendering state is passed in; nothing is read from globals.
"""
from typing import Callable
import numpy as np
from PIL import Image, ImageDraw, ImageOps

from . import constants as C
from .animations import reveal, composite_revealed
from .text import draw_wrapped, draw_circle_icon
from .ticker import draw_ticker


def make_frame_func(
    data:       dict,
    bg_clip,                    # VideoFileClip — background video
    frame_img:  Image.Image,    # frame.png RGBA overlay
    win_mask:   Image.Image,    # pre-computed left-window clipping mask (L mode)
    left_clip,                  # VideoFileClip | None — left window video
    ticker_img: Image.Image,
    ticker_w:   int,
    dp_anim:    list,           # output of animations.build_dp_anim()
    date_str:   str,
) -> Callable[[float], np.ndarray]:
    """Return a make_frame(t) function suitable for moviepy.VideoClip."""

    win_mask_arr = np.array(win_mask)

    def make_frame(t: float) -> np.ndarray:
        # 1. Background — ping-pong video loop
        cycle = t % (2 * bg_clip.duration)
        bg_t  = cycle if cycle <= bg_clip.duration else 2 * bg_clip.duration - cycle
        bg_np = bg_clip.get_frame(bg_t)
        img   = Image.fromarray(bg_np).convert("RGBA")
        if img.size != (C.W, C.H):
            img = img.resize((C.W, C.H), Image.LANCZOS)

        # 2. Left window video — clipped to transparent window area
        if left_clip is not None:
            lv_t   = t % left_clip.duration
            lv_np  = left_clip.get_frame(lv_t)
            lv_img = ImageOps.fit(
                Image.fromarray(lv_np).convert("RGBA"),
                (C.VID_W, C.VID_H), Image.LANCZOS,
            )
            layer  = Image.new("RGBA", (C.W, C.H), (0, 0, 0, 0))
            layer.paste(lv_img, (C.VID_X1, C.VID_Y1))
            l_arr  = np.array(layer)
            l_arr[:, :, 3] = np.minimum(l_arr[:, :, 3], win_mask_arr)
            img = Image.alpha_composite(img, Image.fromarray(l_arr))

        # 3. Frame overlay — borders cover video bleed outside window
        img  = Image.alpha_composite(img, frame_img)
        draw = ImageDraw.Draw(img)

        # 4. Static text/graphics
        draw.text((C.DATE_X, C.DATE_Y), date_str,
                  fill=(220, 220, 220, 255), font=C.F_SRC)

        tb_r  = draw.textbbox((0, 0), data["breaking_label"], font=C.F_BRK_R)
        txt_x = C.BRK_R_CX - (tb_r[2] - tb_r[0]) // 2
        txt_y = C.BRK_R_CY - (tb_r[3] - tb_r[1]) // 2 - tb_r[1]
        draw.text((txt_x, txt_y), data["breaking_label"],
                  fill=(255, 255, 255, 255), font=C.F_BRK_R)
        if int(t * 2) % 2 == 0:
            dot_r  = 7
            dot_cx = txt_x - dot_r - 30
            draw.ellipse([dot_cx - dot_r, C.BRK_R_CY - dot_r,
                          dot_cx + dot_r, C.BRK_R_CY + dot_r],
                         fill=(255, 0, 0, 255))

        draw.text((C.DEAL_LBL_X, C.DEAL_LBL_Y), data["deal_label"],
                  fill=(255, 255, 255, 255), font=C.F_DEAL)

        # Bottom badge
        tb_brk = draw.textbbox((0, 0), "BREAKING", font=C.F_BADGE)
        bx = C.BADGE_CX - (tb_brk[2] - tb_brk[0]) // 2
        by = C.BADGE_CY - (tb_brk[3] - tb_brk[1]) // 2 - tb_brk[1]
        draw.text((bx, by), "BREAKING", fill=(255, 255, 255, 255), font=C.F_BADGE)

        # Top-left badge
        tb_top = draw.textbbox((0, 0), data["breaking_label"], font=C.F_BADGE)
        tx = C.TOP_BADGE_CX - (tb_top[2] - tb_top[0]) // 2
        ty = C.TOP_BADGE_CY - (tb_top[3] - tb_top[1]) // 2 - tb_top[1]
        draw.text((tx, ty), data["breaking_label"],
                  fill=(255, 255, 255, 255), font=C.F_BADGE)

        # Separator lines (always visible)
        for sy in C.SEP_Y:
            draw.line([(C.SEP_X1, sy), (C.SEP_X2, sy)],
                      fill=(200, 0, 0, 255), width=3)

        # 5. Animated text — headline white wipe (t=0.0–0.7s)
        bb1   = draw.textbbox((C.HL_X, C.HL_Y), data["headline_white"], font=C.F_HL1)
        frac1 = reveal(t, 0.0, C.ANIM_DUR)
        if frac1 > 0:
            tmp = Image.new("RGBA", (C.W, C.H), (0, 0, 0, 0))
            ImageDraw.Draw(tmp).text((C.HL_X, C.HL_Y), data["headline_white"],
                                     fill=(255, 255, 255, 255), font=C.F_HL1)
            composite_revealed(img, tmp, C.HL_X, bb1[2], frac1)

        # Headline red wipe (t=0.7–1.4s)
        hl2_y = bb1[3] + 4
        bb2   = draw.textbbox((C.HL_X, hl2_y), data["headline_red"], font=C.F_HL2)
        frac2 = reveal(t, C.ANIM_DUR, C.ANIM_DUR)
        if frac2 > 0:
            tmp = Image.new("RGBA", (C.W, C.H), (0, 0, 0, 0))
            ImageDraw.Draw(tmp).text((C.HL_X, hl2_y), data["headline_red"],
                                     fill=(220, 0, 0, 255), font=C.F_HL2)
            composite_revealed(img, tmp, C.HL_X, bb2[2], frac2)

        # Source wipe (t=1.4–2.1s)
        bb_src   = draw.textbbox((C.SRC_X, C.SRC_Y), data["source"], font=C.F_SRC)
        frac_src = reveal(t, 2 * C.ANIM_DUR, C.ANIM_DUR)
        if frac_src > 0:
            tmp = Image.new("RGBA", (C.W, C.H), (0, 0, 0, 0))
            ImageDraw.Draw(tmp).text((C.SRC_X, C.SRC_Y), data["source"],
                                     fill=(200, 200, 200, 255), font=C.F_SRC)
            composite_revealed(img, tmp, C.SRC_X, bb_src[2], frac_src)

        # Deal points — line-by-line wipe; circle with each point's first line
        for dp_i, dp_cy, dp_pt, dp_lines in dp_anim:
            for line_t, is_first, ln, line_y in dp_lines:
                frac = reveal(t, line_t, C.LINE_DUR)
                if frac <= 0:
                    continue
                tmp  = Image.new("RGBA", (C.W, C.H), (0, 0, 0, 0))
                dtmp = ImageDraw.Draw(tmp)
                if is_first:
                    draw_circle_icon(dtmp, C.CIRC_X, dp_cy, C.CIRC_R,
                                     dp_pt["icon_fill"], icon_type=dp_i)
                draw_wrapped(dtmp, C.TEXT_X, line_y, ln, C.F_PT, C.TEXT_W,
                             fill=(255, 255, 255, 255),
                             highlight=dp_pt.get("highlight"),
                             line_gap=5)
                composite_revealed(img, tmp, C.SEP_X1, C.SEP_X2, frac)

        # 6. Ticker scroll
        img = draw_ticker(img, ticker_img, ticker_w, t)

        return np.array(img)[:, :, :3]

    return make_frame
