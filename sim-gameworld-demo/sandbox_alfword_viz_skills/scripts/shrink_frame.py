#!/usr/bin/env python3
"""
shrink_frame.py — Shrink ALFWorld game step PNGs for inline chat display.

Converts a step PNG to a smaller JPEG (or optionally base64 data URI)
that can be embedded in chat UIs with limited image support.

Usage:
    # Shrink a specific frame (saves _thumb.jpg next to it)
    python shrink_frame.py step_0001.png

    # Shrink with custom max dimension and quality
    python shrink_frame.py step_0001.png --max-dim 320 --quality 60

    # Output as base64 data URI (for markdown embedding)
    python shrink_frame.py step_0001.png --base64

    # Shrink the latest frame in assets/
    python shrink_frame.py --latest

    # Shrink ALL frames in assets/
    python shrink_frame.py --all

    # Custom output path
    python shrink_frame.py step_0001.png -o /tmp/preview.jpg
"""

import argparse
import base64
import glob
import os
import sys

from PIL import Image

# Defaults
DEFAULT_MAX_DIM = 400       # max width or height in pixels
DEFAULT_QUALITY = 65        # JPEG quality (1-95)
ASSETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "assets",
)


def shrink(
    input_path: str,
    output_path: str | None = None,
    max_dim: int = DEFAULT_MAX_DIM,
    quality: int = DEFAULT_QUALITY,
    as_base64: bool = False,
) -> str:
    """
    Shrink a PNG frame to a smaller JPEG.

    Args:
        input_path:  Path to the source PNG.
        output_path: Where to save the JPEG. Defaults to <stem>_thumb.jpg
                     in the same directory.
        max_dim:     Maximum width or height in pixels.
        quality:     JPEG quality (1-95, lower = smaller file).
        as_base64:   If True, return a data URI string instead of saving.

    Returns:
        The output file path, or the data URI string if as_base64=True.
    """
    img = Image.open(input_path)

    # Convert RGBA -> RGB (JPEG doesn't support alpha)
    if img.mode in ("RGBA", "P"):
        img = img.convert("RGB")

    # Resize preserving aspect ratio
    w, h = img.size
    if max(w, h) > max_dim:
        scale = max_dim / max(w, h)
        new_w = int(w * scale)
        new_h = int(h * scale)
        img = img.resize((new_w, new_h), Image.LANCZOS)

    if as_base64:
        import io
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        b64 = base64.b64encode(buf.getvalue()).decode("ascii")
        return f"data:image/jpeg;base64,{b64}"

    if output_path is None:
        stem, _ = os.path.splitext(input_path)
        output_path = f"{stem}_thumb.jpg"

    img.save(output_path, format="JPEG", quality=quality, optimize=True)

    orig_size = os.path.getsize(input_path)
    new_size = os.path.getsize(output_path)
    ratio = (1 - new_size / orig_size) * 100
    print(
        f"{os.path.basename(input_path)}: "
        f"{orig_size:,}B → {new_size:,}B "
        f"({ratio:.0f}% smaller) → {output_path}"
    )
    return output_path


def find_latest() -> str | None:
    """Find the most recent step_*.png in assets/."""
    pngs = sorted(glob.glob(os.path.join(ASSETS_DIR, "step_*.png")))
    return pngs[-1] if pngs else None


def find_all() -> list[str]:
    """Find all step_*.png in assets/."""
    return sorted(glob.glob(os.path.join(ASSETS_DIR, "step_*.png")))


def main():
    parser = argparse.ArgumentParser(description="Shrink ALFWorld step frames")
    parser.add_argument("input", nargs="?", help="Path to PNG file")
    parser.add_argument("--latest", action="store_true", help="Shrink latest frame")
    parser.add_argument("--all", action="store_true", help="Shrink all frames")
    parser.add_argument("--max-dim", type=int, default=DEFAULT_MAX_DIM,
                        help=f"Max width/height (default: {DEFAULT_MAX_DIM})")
    parser.add_argument("--quality", "-q", type=int, default=DEFAULT_QUALITY,
                        help=f"JPEG quality 1-95 (default: {DEFAULT_QUALITY})")
    parser.add_argument("--base64", "-b", action="store_true",
                        help="Output base64 data URI to stdout")
    parser.add_argument("-o", "--output", help="Output file path")
    args = parser.parse_args()

    targets: list[str] = []

    if args.all:
        targets = find_all()
        if not targets:
            print(f"No step_*.png found in {ASSETS_DIR}", file=sys.stderr)
            sys.exit(1)
    elif args.latest:
        latest = find_latest()
        if not latest:
            print(f"No step_*.png found in {ASSETS_DIR}", file=sys.stderr)
            sys.exit(1)
        targets = [latest]
    elif args.input:
        # Resolve relative to assets dir if not absolute
        p = args.input
        if not os.path.isabs(p) and not os.path.exists(p):
            p = os.path.join(ASSETS_DIR, p)
        if not os.path.exists(p):
            print(f"File not found: {args.input}", file=sys.stderr)
            sys.exit(1)
        targets = [p]
    else:
        parser.print_help()
        sys.exit(1)

    for t in targets:
        result = shrink(
            t,
            output_path=args.output if len(targets) == 1 else None,
            max_dim=args.max_dim,
            quality=args.quality,
            as_base64=args.base64,
        )
        if args.base64:
            print(result)


if __name__ == "__main__":
    main()
