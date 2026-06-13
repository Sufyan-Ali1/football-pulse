"""
Generate one Football Pulse test thumbnail from a fixed FIFA World Cup prompt.

Usage:
    venv\Scripts\python scripts\generate_test_thumbnail.py
    venv\Scripts\python scripts\generate_test_thumbnail.py --hook-text "WORLD CUP SHOCKER"
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from publish.thumbnail import create_test_thumbnail_from_prompt


PROMPT = """Generate a highly clickable, premium YouTube thumbnail for a football news channel called "Football Pulse."

Create a professional FIFA World Cup themed thumbnail with a bold, dramatic, modern football-news style. The thumbnail should be visually powerful, highly attractive, and optimized for YouTube click-through rate, especially on mobile screens.

Main style:
- dark dramatic football background
- premium sports-broadcast look
- black base tones
- neon green highlights
- white bold text
- strong contrast
- modern football-news graphics
- cinematic lighting
- clean but powerful composition

The thumbnail must match the Football Pulse brand identity:
- black
- neon green
- white
- premium football news aesthetic

Main subject:
- focus on a FIFA World Cup story
- include 1 to 3 famous football players if relevant
- include national team names, flags, crests, or FIFA World Cup trophy if relevant
- if players are included, make them large and dominant with strong emotional expressions
- use subtle glow or rim light so they stand out

Background:
- stadium at night
- glowing floodlights
- crowd lights
- smoke or fog
- subtle green light streaks
- football-news broadcast graphics
- tactical lines
- sports HUD overlays
- scoreboard-style details
- subtle World Cup atmosphere

Hook text guidance:
- short, curiosity-driven, catchy
- bold, easy to read, high contrast, emotionally strong, mobile-friendly
- 2 to 5 words
- examples: HUGE WORLD CUP UPDATE, THIS CHANGES EVERYTHING, OFFICIAL NOW, MAJOR TWIST, WORLD CUP SHOCKER, FINAL CALL

Layout:
- clean but dynamic
- player on left, hook text on right, or two players facing each other with hook text in center
- subject must be large and text immediately readable

Branding:
- include a small Football Pulse logo/brand mark in the lower-right corner
- make it look integrated, clean, and non-distracting

Visual effects:
- green glow accents
- white bold text with dark shadow or stroke
- subtle outline around players
- dramatic rim lighting
- smoke and particles
- light flares
- football-news HUD graphics
- tactical pitch overlays
- digital sports interface elements
- scoreboard-style details
- strong contrast and depth

Mood:
- urgent
- dramatic
- exciting
- premium
- FIFA World Cup focused
- modern
- professional
- highly clickable

Important restrictions:
- do not clutter the thumbnail
- do not use too much text
- do not make text small
- do not use dull colors
- do not make the background too busy
- do not make players too small
- do not use cartoon style
- do not make the design flat
- do not make it look like a poster
- do not reduce readability

Output requirements:
- aspect ratio 16:9
- resolution 1280x720
- style premium FIFA World Cup YouTube thumbnail
- quality ultra sharp, high contrast, highly clickable"""


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate a Football Pulse test thumbnail.")
    parser.add_argument("--output-name", default="football_pulse_test_thumbnail")
    parser.add_argument("--hook-text", default="HUGE WORLD CUP UPDATE")
    parser.add_argument("--kicker", default="FIFA WORLD CUP")
    parser.add_argument("--source-label", default="Football Pulse")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(message)s")

    thumbnail_path = create_test_thumbnail_from_prompt(
        prompt=PROMPT,
        output_stem=args.output_name,
        hook_text=args.hook_text,
        kicker=args.kicker,
        source_label=args.source_label,
    )
    if not thumbnail_path:
        print("Thumbnail generation failed.")
        return 1

    print(f"Thumbnail generated: {thumbnail_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
