"""
tests/test_enricher_lifecycle.py

Unit tests for enrichment_progress.json state machine (WF22).

Covers:
- get_enrichment_status defaults when file absent
- in_progress=True with live PID → in_progress preserved
- in_progress=True with dead PID → stalled=True, in_progress=False
- enriched_count >= total_symbols → complete display suffix
- partial completion → no 'complete' or 'stalled' suffix
- display string format: emoji · count/total · pct% · fp8chars [· suffix]
- session_fingerprint is 16-char hex
- bonds_covered flag propagated
- update_session_fingerprint chains correctly across enrichments
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from services.consultation_policy import get_enrichment_status, update_session_fingerprint

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FP = "abcdef1234567890"
_FP_SHORT = _FP[:8]


def _write_progress(tmpdir: Path, **fields) -> Path:
    raw = tmpdir / ".raw"
    raw.mkdir(exist_ok=True)
    pf = raw / "enrichment_progress.json"
    pf.write_text(json.dumps(fields))
    return pf


# ---------------------------------------------------------------------------
# Absent file → defaults
# ---------------------------------------------------------------------------

def test_absent_progress_file_returns_defaults(tmp_path):
    status = get_enrichment_status(tmp_path)
    assert status["in_progress"] is False
    assert status["stalled"] is False
    assert status["enriched_count"] == 0
    assert status["total_symbols"] == 0
    assert status["session_fingerprint"] == "0000000000000000"
    assert status["bonds_covered"] is False


def test_absent_progress_file_display_is_unknown(tmp_path):
    status = get_enrichment_status(tmp_path)
    assert "unknown" in status["display"].lower() or "⚠️" in status["display"]


# ---------------------------------------------------------------------------
# Dead PID → stalled
# ---------------------------------------------------------------------------

def test_dead_pid_marks_stalled(tmp_path):
    _write_progress(tmp_path,
                    total_symbols=10, enriched_count=3, in_progress=True,
                    background_pid=999999, session_fingerprint=_FP, bonds_covered=False)
    status = get_enrichment_status(tmp_path)
    assert status["stalled"] is True
    assert status["in_progress"] is False


def test_dead_pid_display_has_warning_emoji(tmp_path):
    _write_progress(tmp_path,
                    total_symbols=10, enriched_count=3, in_progress=True,
                    background_pid=999999, session_fingerprint=_FP, bonds_covered=False)
    status = get_enrichment_status(tmp_path)
    assert status["display"].startswith("⚠️")
    assert "stalled" in status["display"]


# ---------------------------------------------------------------------------
# Live PID → in_progress preserved
# ---------------------------------------------------------------------------

def test_live_pid_preserves_in_progress(tmp_path):
    _write_progress(tmp_path,
                    total_symbols=50, enriched_count=10, in_progress=True,
                    background_pid=os.getpid(), session_fingerprint=_FP, bonds_covered=False)
    status = get_enrichment_status(tmp_path)
    assert status["in_progress"] is True
    assert status["stalled"] is False


def test_live_pid_display_has_hourglass(tmp_path):
    _write_progress(tmp_path,
                    total_symbols=50, enriched_count=10, in_progress=True,
                    background_pid=os.getpid(), session_fingerprint=_FP, bonds_covered=False)
    status = get_enrichment_status(tmp_path)
    assert status["display"].startswith("⏳")
    assert "updating" in status["display"]


# ---------------------------------------------------------------------------
# Complete → checkmark with 'complete' suffix
# ---------------------------------------------------------------------------

def test_fully_enriched_display_has_complete_suffix(tmp_path):
    _write_progress(tmp_path,
                    total_symbols=20, enriched_count=20, in_progress=False,
                    background_pid=None, session_fingerprint=_FP, bonds_covered=True)
    status = get_enrichment_status(tmp_path)
    assert status["display"].startswith("✅")
    assert "complete" in status["display"]


def test_fully_enriched_not_stalled(tmp_path):
    _write_progress(tmp_path,
                    total_symbols=20, enriched_count=20, in_progress=False,
                    background_pid=None, session_fingerprint=_FP, bonds_covered=True)
    status = get_enrichment_status(tmp_path)
    assert status["stalled"] is False
    assert status["in_progress"] is False


# ---------------------------------------------------------------------------
# Partial completion (no 'complete' or 'stalled' suffix)
# ---------------------------------------------------------------------------

def test_partial_enrichment_display(tmp_path):
    _write_progress(tmp_path,
                    total_symbols=20, enriched_count=5, in_progress=False,
                    background_pid=None, session_fingerprint=_FP, bonds_covered=False)
    status = get_enrichment_status(tmp_path)
    assert status["display"].startswith("✅")
    assert "complete" not in status["display"]
    assert "stalled" not in status["display"]


# ---------------------------------------------------------------------------
# Display format: emoji · N/T · P% · fp8chars [· suffix]
# ---------------------------------------------------------------------------

import re

_DISPLAY_PATTERN = re.compile(
    r'^[✅⏳⚠️].+\d+/\d+\s*·\s*[\d.]+%\s*·\s*[0-9a-f]{8}'
)


@pytest.mark.parametrize("enriched,total,in_progress,pid,expected_emoji", [
    (10, 50, True,  os.getpid(),  "⏳"),
    (0,  10, True,  999999,       "⚠️"),
    (10, 10, False, None,         "✅"),
    (5,  10, False, None,         "✅"),
])
def test_display_format_matches_pattern(tmp_path, enriched, total, in_progress, pid, expected_emoji):
    _write_progress(tmp_path,
                    total_symbols=total, enriched_count=enriched,
                    in_progress=in_progress, background_pid=pid,
                    session_fingerprint=_FP, bonds_covered=False)
    status = get_enrichment_status(tmp_path)
    assert _DISPLAY_PATTERN.search(status["display"]), \
        f"display {status['display']!r} doesn't match pattern"
    assert status["display"].startswith(expected_emoji)


# ---------------------------------------------------------------------------
# session_fingerprint is 16-char hex
# ---------------------------------------------------------------------------

def test_fingerprint_16_char_hex(tmp_path):
    _write_progress(tmp_path,
                    total_symbols=5, enriched_count=2, in_progress=False,
                    background_pid=None, session_fingerprint=_FP, bonds_covered=False)
    status = get_enrichment_status(tmp_path)
    fp = status["session_fingerprint"]
    assert len(fp) == 16
    assert all(c in "0123456789abcdef" for c in fp)


# ---------------------------------------------------------------------------
# bonds_covered propagated
# ---------------------------------------------------------------------------

def test_bonds_covered_true_propagated(tmp_path):
    _write_progress(tmp_path,
                    total_symbols=10, enriched_count=5, in_progress=False,
                    background_pid=None, session_fingerprint=_FP, bonds_covered=True)
    status = get_enrichment_status(tmp_path)
    assert status["bonds_covered"] is True


def test_bonds_covered_false_propagated(tmp_path):
    _write_progress(tmp_path,
                    total_symbols=10, enriched_count=5, in_progress=False,
                    background_pid=None, session_fingerprint=_FP, bonds_covered=False)
    status = get_enrichment_status(tmp_path)
    assert status["bonds_covered"] is False


# ---------------------------------------------------------------------------
# update_session_fingerprint — chain correctness (WF23)
# ---------------------------------------------------------------------------

def test_chain_changes_each_enrichment():
    fp0 = "0000000000000000"
    fp1 = update_session_fingerprint(fp0, "MSFT", "Cloud growth strong.")
    fp2 = update_session_fingerprint(fp1, "AAPL", "iPhone cycle solid.")
    assert fp0 != fp1
    assert fp1 != fp2
    assert fp0 != fp2


def test_chain_is_deterministic():
    fp0 = "0000000000000000"
    fp1a = update_session_fingerprint(fp0, "MSFT", "Cloud growth strong.")
    fp1b = update_session_fingerprint(fp0, "MSFT", "Cloud growth strong.")
    assert fp1a == fp1b


def test_chain_is_order_dependent():
    fp0 = "0000000000000000"
    fp_msft_first = update_session_fingerprint(
        update_session_fingerprint(fp0, "MSFT", "synthesis A"),
        "AAPL", "synthesis B"
    )
    fp_aapl_first = update_session_fingerprint(
        update_session_fingerprint(fp0, "AAPL", "synthesis B"),
        "MSFT", "synthesis A"
    )
    assert fp_msft_first != fp_aapl_first


def test_each_fp_is_16_char_hex():
    fp0 = "0000000000000000"
    fp1 = update_session_fingerprint(fp0, "NVDA", "AI GPU demand robust.")
    assert len(fp1) == 16
    assert all(c in "0123456789abcdef" for c in fp1)
