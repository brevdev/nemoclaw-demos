#!/usr/bin/env python3
"""
SVG consultation card renderer for InvestorClaw.

Pure Python stdlib — no external dependencies.
Renders a dark-theme SVG card for a consultation synthesis result.

Usage:
    from render_consultation_card import render_card
    path = render_card("MSFT", synthesis_text, attribution, fingerprint,
                       timestamp, output_dir)
"""
from __future__ import annotations

import re
import textwrap
from pathlib import Path


# Card dimensions
_WIDTH = 480
_HEIGHT = 280
_BG = "#1a1a2e"
_TICKER_COLOR = "#e8e8e8"
_TEXT_COLOR = "#b0b8c8"
_ATTR_COLOR = "#6b7280"
_BADGE_BG = "#4a9eff"
_BADGE_TEXT = "#ffffff"

_LOGO_SVG_PATH = Path(__file__).resolve().parent.parent / "assets" / "investorclaw-logo.svg"


def _load_logo_element() -> str:
    """Inline the SVG logo as a <g> element, or return empty string if unavailable."""
    if not _LOGO_SVG_PATH.exists():
        return ""
    try:
        raw = _LOGO_SVG_PATH.read_text(encoding="utf-8")
        # Extract inner content from <svg …>…</svg> — strip the outer svg wrapper
        inner_match = re.search(r'<svg[^>]*>(.*?)</svg>', raw, re.DOTALL)
        if not inner_match:
            return ""
        inner = inner_match.group(1).strip()
        # Place wordmark top-right: card is 480px wide, logo viewBox 120px, 10px right margin
        return f'  <!-- Logo (inline SVG wordmark — no raster embed) -->\n  <g transform="translate(350,10)">\n{inner}\n  </g>\n'
    except OSError:
        return ""


def _escape_xml(text: str) -> str:
    return (
        text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
            .replace('"', "&quot;")
            .replace("'", "&apos;")
    )


def render_card(
    symbol: str,
    synthesis: str,
    attribution: str,
    fingerprint: str,
    timestamp: str,
    output_dir: Path,
) -> Path:
    """
    Render an SVG consultation card and write it to output_dir/consultation_cards/{symbol}.svg.

    Args:
        symbol:      Ticker symbol (e.g. "MSFT")
        synthesis:   Full synthesis text from the consultation model
        attribution: Attribution string (e.g. "gemma4-consult via local-inference (3420ms)")
        fingerprint: 16-char HMAC fingerprint hex string
        timestamp:   ISO timestamp of the consultation
        output_dir:  Parent directory — card goes into output_dir/consultation_cards/

    Returns:
        Path to the written SVG file.
    """
    cards_dir = Path(output_dir) / "consultation_cards"
    cards_dir.mkdir(parents=True, exist_ok=True)
    # Strip any characters that could escape the target directory (path traversal)
    safe_symbol = re.sub(r'[^A-Z0-9.\-]', '_', symbol.upper()) or "UNKNOWN"
    out_path = cards_dir / f"{safe_symbol}.svg"

    # Wrap synthesis into lines of ~56 chars, max 7 lines
    # Card is 480px wide, text starts at x=24 → 456px available.
    # Monospace 13px ≈ 7.7px/char → 56 chars ≈ 431px (safe margin).
    wrapped_lines = textwrap.wrap(synthesis, 56)[:7]

    # Build synthesis text elements (y starts at 80, 22px line-height)
    synthesis_elements = ""
    for i, line in enumerate(wrapped_lines):
        y = 80 + i * 22
        synthesis_elements += (
            f'  <text x="24" y="{y}" font-family="monospace" font-size="13" '
            f'fill="{_TEXT_COLOR}">{_escape_xml(line)}</text>\n'
        )

    # Logo element (top-right) — inline SVG, gracefully absent if asset not bundled
    logo_element = _load_logo_element()

    # Fingerprint badge (bottom-right)
    badge_x = _WIDTH - 160
    badge_y = _HEIGHT - 32

    svg = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        f'<svg xmlns="http://www.w3.org/2000/svg"\n'
        f'     xmlns:xlink="http://www.w3.org/1999/xlink"\n'
        f'     width="{_WIDTH}" height="{_HEIGHT}"\n'
        f'     viewBox="0 0 {_WIDTH} {_HEIGHT}"\n'
        f'     data-fingerprint="{_escape_xml(fingerprint)}"\n'
        f'     data-symbol="{_escape_xml(symbol.upper())}"\n'
        f'     data-timestamp="{_escape_xml(timestamp)}">\n'
        '\n'
        '  <!-- Background -->\n'
        f'  <rect width="{_WIDTH}" height="{_HEIGHT}" rx="12" ry="12" fill="{_BG}"/>\n'
        '\n'
        '  <!-- Ticker -->\n'
        f'  <text x="24" y="48" font-family="monospace" font-size="28" font-weight="bold"\n'
        f'        fill="{_TICKER_COLOR}">{_escape_xml(symbol.upper())}</text>\n'
        '\n'
        '  <!-- Logo (top-right, gracefully absent if not bundled) -->\n'
        f'{logo_element}'
        '  <!-- Synthesis lines -->\n'
        f'{synthesis_elements}'
        '  <!-- Attribution -->\n'
        f'  <text x="24" y="248" font-family="monospace" font-size="11" font-style="italic"\n'
        f'        fill="{_ATTR_COLOR}">{_escape_xml(attribution)}</text>\n'
        '\n'
        '  <!-- Fingerprint badge -->\n'
        f'  <rect x="{badge_x}" y="{badge_y}" width="140" height="20" rx="4" fill="{_BADGE_BG}"/>\n'
        f'  <text x="{badge_x + 8}" y="{badge_y + 14}" font-family="monospace" font-size="10"\n'
        f'        fill="{_BADGE_TEXT}">{_escape_xml(fingerprint)}</text>\n'
        '</svg>\n'
    )

    out_path.write_text(svg, encoding="utf-8")
    return out_path


if __name__ == "__main__":
    import sys
    import os

    # Quick smoke test
    _out = Path(os.environ.get("INVESTOR_CLAW_REPORTS_DIR", "/tmp")) / ".raw"
    _path = render_card(
        "TEST", "Analyst consensus is Buy with 42 analysts. Main risk is macro uncertainty.",
        "gemma4-consult via local-inference (3420ms)", "abcd1234efgh5678",
        "2026-04-10T00:00:00", _out,
    )
    print(f"Card written: {_path}")
    sys.exit(0)
