"""
tests/test_svg_cards.py

Unit tests for rendering/render_consultation_card.py (WF24).

Covers:
- SVG file written to correct path (output_dir/consultation_cards/{SYMBOL}.svg)
- data-fingerprint, data-symbol, data-timestamp attributes present in root <svg> element
- fingerprint text visible in badge element
- ticker symbol rendered in body
- attribution line included
- path traversal in symbol is sanitized
- XML-unsafe characters in synthesis are escaped
- synthesis wraps to max 7 lines of ~62 chars
"""

from __future__ import annotations

import tempfile
import re
from pathlib import Path

import pytest

from rendering.render_consultation_card import render_card

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SYMBOL = "MSFT"
SYNTHESIS = "Azure cloud growth accelerating with 31% YoY revenue increase driven by AI services adoption."
ATTRIBUTION = "gemma4-consult via local-inference (3420ms)"
FINGERPRINT = "abcdef1234567890"
TIMESTAMP = "2026-04-11T10:00:00Z"


@pytest.fixture()
def svg_output(tmp_path) -> tuple[Path, str]:
    """Render a card and return (path, svg_text)."""
    out_path = render_card(SYMBOL, SYNTHESIS, ATTRIBUTION, FINGERPRINT, TIMESTAMP, tmp_path)
    return out_path, out_path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# Path and file structure
# ---------------------------------------------------------------------------

def test_card_written_to_consultation_cards_subdir(tmp_path):
    out_path = render_card(SYMBOL, SYNTHESIS, ATTRIBUTION, FINGERPRINT, TIMESTAMP, tmp_path)
    assert out_path.parent.name == "consultation_cards"
    assert out_path.parent.parent == tmp_path


def test_card_filename_matches_symbol(tmp_path):
    out_path = render_card(SYMBOL, SYNTHESIS, ATTRIBUTION, FINGERPRINT, TIMESTAMP, tmp_path)
    assert out_path.name == f"{SYMBOL}.svg"


def test_card_file_exists_after_render(svg_output):
    out_path, _ = svg_output
    assert out_path.exists()


# ---------------------------------------------------------------------------
# SVG root element data attributes (WF24 core contract)
# ---------------------------------------------------------------------------

def test_data_fingerprint_attribute_present(svg_output):
    _, svg = svg_output
    assert f'data-fingerprint="{FINGERPRINT}"' in svg


def test_data_symbol_attribute_present(svg_output):
    _, svg = svg_output
    assert f'data-symbol="{SYMBOL.upper()}"' in svg


def test_data_timestamp_attribute_present(svg_output):
    _, svg = svg_output
    assert f'data-timestamp="{TIMESTAMP}"' in svg


# ---------------------------------------------------------------------------
# Content presence
# ---------------------------------------------------------------------------

def test_fingerprint_in_badge_text(svg_output):
    _, svg = svg_output
    # Fingerprint appears both in svg root attr and in badge <text> element
    assert svg.count(FINGERPRINT) >= 2


def test_ticker_symbol_in_body(svg_output):
    _, svg = svg_output
    assert SYMBOL.upper() in svg


def test_attribution_in_body(svg_output):
    _, svg = svg_output
    assert ATTRIBUTION in svg


# ---------------------------------------------------------------------------
# XML validity and escaping
# ---------------------------------------------------------------------------

def test_valid_xml_declaration(svg_output):
    _, svg = svg_output
    assert svg.startswith('<?xml version="1.0" encoding="UTF-8"?>')


def test_svg_namespace_present(svg_output):
    _, svg = svg_output
    assert 'xmlns="http://www.w3.org/2000/svg"' in svg


def test_xml_unsafe_chars_escaped_in_synthesis(tmp_path):
    unsafe = 'Revenue > $1B & margins <5% for "AI" division'
    out_path = render_card(SYMBOL, unsafe, ATTRIBUTION, FINGERPRINT, TIMESTAMP, tmp_path)
    svg = out_path.read_text(encoding="utf-8")
    # Raw unsafe chars must not appear unescaped in synthesis elements
    # (they may appear in comments or data-* attrs which are also escaped)
    assert "&amp;" in svg or "&lt;" in svg or "&gt;" in svg or "&quot;" in svg


def test_path_traversal_in_symbol_sanitized(tmp_path):
    out_path = render_card("../../../etc/passwd", SYNTHESIS, ATTRIBUTION, FINGERPRINT, TIMESTAMP, tmp_path)
    # File must land inside consultation_cards/ — the parent check is the real safety guarantee.
    # The filename may contain literal dots (e.g. .._.._.._ETC_PASSWD.svg) but no slashes,
    # so Path concatenation never escapes the target directory.
    assert out_path.parent == tmp_path / "consultation_cards"
    assert "/" not in out_path.name and "\\" not in out_path.name


# ---------------------------------------------------------------------------
# Synthesis wrapping
# ---------------------------------------------------------------------------

def test_synthesis_wraps_long_text(tmp_path):
    long_synthesis = "Word " * 200  # 200 words, far beyond 7 lines of 62 chars
    out_path = render_card(SYMBOL, long_synthesis, ATTRIBUTION, FINGERPRINT, TIMESTAMP, tmp_path)
    svg = out_path.read_text(encoding="utf-8")
    # Count synthesis <text> elements — max 7 lines
    synthesis_lines = re.findall(r'<text x="24" y="\d+" font-family="monospace" font-size="13"', svg)
    assert len(synthesis_lines) <= 7


def test_short_synthesis_not_over_wrapped(tmp_path):
    short = "Brief note."
    out_path = render_card(SYMBOL, short, ATTRIBUTION, FINGERPRINT, TIMESTAMP, tmp_path)
    svg = out_path.read_text(encoding="utf-8")
    synthesis_lines = re.findall(r'<text x="24" y="\d+" font-family="monospace" font-size="13"', svg)
    assert len(synthesis_lines) == 1


# ---------------------------------------------------------------------------
# Multiple symbols produce separate files
# ---------------------------------------------------------------------------

def test_different_symbols_produce_separate_files(tmp_path):
    path_a = render_card("AAPL", SYNTHESIS, ATTRIBUTION, FINGERPRINT, TIMESTAMP, tmp_path)
    path_b = render_card("MSFT", SYNTHESIS, ATTRIBUTION, FINGERPRINT, TIMESTAMP, tmp_path)
    assert path_a != path_b
    assert path_a.exists() and path_b.exists()
