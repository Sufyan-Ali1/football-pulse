"""
Add a bottom-right watermark logo to video clips in a folder.

Examples:
    python scripts/add_watermark_to_clips.py --input-dir "C:\clips" --logo "C:\logo.png"
    python scripts/add_watermark_to_clips.py --input-dir "C:\clips" --logo "C:\logo.png" --output-dir "C:\clips\watermarked"
    python scripts/add_watermark_to_clips.py --input-dir "C:\clips" --logo "C:\logo.png" --suffix "_wm"
"""

from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def _output_path(video_path: Path, output_dir: Path | None, suffix: str) -> Path:
    if output_dir is None:
        return video_path.with_name(f"{video_path.stem}{suffix}{video_path.suffix}")
    return output_dir / f"{video_path.stem}{suffix}{video_path.suffix}"


def add_watermark(
    video_path: Path,
    logo_path: Path,
    output_path: Path,
    logo_width: int,
    right_margin: int,
    bottom_margin: int,
) -> None:
    if not video_path.is_file():
        raise FileNotFoundError(f"video file not found: {video_path}")
    if not logo_path.is_file():
        raise FileNotFoundError(f"logo file not found: {logo_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    filter_complex = (
        f"[1:v]scale={logo_width}:-1[logo];"
        f"[0:v][logo]overlay=W-w-{right_margin}:H-h-{bottom_margin}"
    )
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-i",
        str(logo_path),
        "-filter_complex",
        filter_complex,
        "-c:v",
        "libx264",
        "-preset",
        "medium",
        "-crf",
        "18",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    subprocess.run(command, check=True)


def batch_add_watermark(
    input_dir: Path,
    logo_path: Path,
    output_dir: Path | None = None,
    suffix: str = "_wm",
    logo_width: int = 120,
    right_margin: int = 20,
    bottom_margin: int = 20,
) -> None:
    if not input_dir.is_dir():
        raise FileNotFoundError(f"input folder not found: {input_dir}")
    if not logo_path.is_file():
        raise FileNotFoundError(f"logo file not found: {logo_path}")
    if output_dir is not None:
        output_dir.mkdir(parents=True, exist_ok=True)

    video_files = sorted(input_dir.glob("*.mp4"), key=lambda path: path.name.lower())
    if not video_files:
        print("No .mp4 files found.")
        return

    for video_path in video_files:
        target_path = _output_path(video_path, output_dir, suffix)
        print(f"Watermarking {video_path.name} -> {target_path.name}")
        add_watermark(
            video_path=video_path,
            logo_path=logo_path,
            output_path=target_path,
            logo_width=logo_width,
            right_margin=right_margin,
            bottom_margin=bottom_margin,
        )


def main() -> None:
    parser = argparse.ArgumentParser(description="Add a bottom-right watermark to all mp4 clips in a folder.")
    parser.add_argument("--input-dir", required=True, help="Folder containing source clips.")
    parser.add_argument("--logo", required=True, help="Path to the watermark logo image, usually a PNG.")
    parser.add_argument("--output-dir", help="Optional output folder. If omitted, files are saved next to originals.")
    parser.add_argument("--suffix", default="_wm", help="Suffix for output filenames. Default: _wm")
    parser.add_argument("--logo-width", type=int, default=120, help="Watermark width in pixels. Default: 120")
    parser.add_argument("--right-margin", type=int, default=20, help="Right margin in pixels. Default: 20")
    parser.add_argument("--bottom-margin", type=int, default=20, help="Bottom margin in pixels. Default: 20")
    args = parser.parse_args()

    input_dir = Path(args.input_dir).expanduser().resolve()
    logo_path = Path(args.logo).expanduser().resolve()
    output_dir = Path(args.output_dir).expanduser().resolve() if args.output_dir else None

    batch_add_watermark(
        input_dir=input_dir,
        logo_path=logo_path,
        output_dir=output_dir,
        suffix=args.suffix,
        logo_width=args.logo_width,
        right_margin=args.right_margin,
        bottom_margin=args.bottom_margin,
    )


if __name__ == "__main__":
    main()
