"""
Unit tests for the HMAC-based anti-fabrication fingerprinting system.

Covers:
  services/consultation_policy.update_session_fingerprint()
  internal/tier3_enrichment._compute_fingerprint()

These functions are the core of the anti-fabrication guarantee: each LLM
synthesis is cryptographically tagged so it cannot be silently swapped with
a fabricated value after-the-fact.
"""
import hashlib
import hmac
import os
import re
import sys
from pathlib import Path

_skill_root = Path(__file__).parent.parent
if str(_skill_root) not in sys.path:
    sys.path.insert(0, str(_skill_root))

import pytest
from services.consultation_policy import update_session_fingerprint
from internal.tier3_enrichment import _compute_fingerprint


_HEX_RE = re.compile(r'^[0-9a-f]+$')


# ---------------------------------------------------------------------------
# update_session_fingerprint (consultation_policy)
# ---------------------------------------------------------------------------

def test_session_fp_returns_16_char_hex(monkeypatch):
    monkeypatch.setenv("INVESTORCLAW_CONSULTATION_HMAC_KEY", "testkey")
    fp = update_session_fingerprint("0000000000000000", "AAPL", "Bullish outlook.")
    assert len(fp) == 16
    assert _HEX_RE.match(fp), f"Fingerprint is not lowercase hex: {fp!r}"


def test_session_fp_deterministic_with_fixed_key(monkeypatch):
    monkeypatch.setenv("INVESTORCLAW_CONSULTATION_HMAC_KEY", "fixed-key")
    fp1 = update_session_fingerprint("0000000000000000", "AAPL", "Bullish.")
    fp2 = update_session_fingerprint("0000000000000000", "AAPL", "Bullish.")
    assert fp1 == fp2


def test_session_fp_differs_for_different_symbols(monkeypatch):
    monkeypatch.setenv("INVESTORCLAW_CONSULTATION_HMAC_KEY", "fixed-key")
    fp_aapl = update_session_fingerprint("0000000000000000", "AAPL", "Same text.")
    fp_msft = update_session_fingerprint("0000000000000000", "MSFT", "Same text.")
    assert fp_aapl != fp_msft


def test_session_fp_differs_for_different_synthesis(monkeypatch):
    monkeypatch.setenv("INVESTORCLAW_CONSULTATION_HMAC_KEY", "fixed-key")
    fp1 = update_session_fingerprint("0000000000000000", "AAPL", "Bullish.")
    fp2 = update_session_fingerprint("0000000000000000", "AAPL", "Bearish.")
    assert fp1 != fp2


def test_session_fp_chaining_is_order_dependent(monkeypatch):
    """HMAC chain: processing AAPL then MSFT must differ from MSFT then AAPL."""
    monkeypatch.setenv("INVESTORCLAW_CONSULTATION_HMAC_KEY", "chain-key")
    seed = "0000000000000000"
    fp_ab = update_session_fingerprint(
        update_session_fingerprint(seed, "AAPL", "A"), "MSFT", "M"
    )
    fp_ba = update_session_fingerprint(
        update_session_fingerprint(seed, "MSFT", "M"), "AAPL", "A"
    )
    assert fp_ab != fp_ba


def test_session_fp_uses_env_key_when_set(monkeypatch):
    """With a fixed env key the fingerprint must match a locally computed HMAC."""
    monkeypatch.setenv("INVESTORCLAW_CONSULTATION_HMAC_KEY", "well-known-key")
    prev_fp, symbol, synthesis = "0000000000000000", "TSLA", "Strong buy."
    got = update_session_fingerprint(prev_fp, symbol, synthesis)
    expected = hmac.new(
        b"well-known-key",
        f"{prev_fp}{symbol}{synthesis}".encode(),
        hashlib.sha256,
    ).hexdigest()[:16]
    assert got == expected


def test_session_fp_without_env_key_still_returns_valid_hex(monkeypatch):
    """When env key is absent the session key is used — output is still valid hex."""
    monkeypatch.delenv("INVESTORCLAW_CONSULTATION_HMAC_KEY", raising=False)
    fp = update_session_fingerprint("0000000000000000", "NVDA", "Positive.")
    assert len(fp) == 16
    assert _HEX_RE.match(fp)


# ---------------------------------------------------------------------------
# _compute_fingerprint (tier3_enrichment)
# ---------------------------------------------------------------------------

def test_compute_fp_returns_16_char_hex(monkeypatch):
    monkeypatch.setenv("INVESTORCLAW_CONSULTATION_HMAC_KEY", "testkey")
    fp = _compute_fingerprint("AAPL", "gemma4-consult", "Bullish outlook.")
    assert len(fp) == 16
    assert _HEX_RE.match(fp), f"Fingerprint is not lowercase hex: {fp!r}"


def test_compute_fp_deterministic_with_fixed_key(monkeypatch):
    monkeypatch.setenv("INVESTORCLAW_CONSULTATION_HMAC_KEY", "fixed-key")
    fp1 = _compute_fingerprint("AAPL", "gemma4-consult", "Bullish.")
    fp2 = _compute_fingerprint("AAPL", "gemma4-consult", "Bullish.")
    assert fp1 == fp2


def test_compute_fp_differs_for_different_symbols(monkeypatch):
    monkeypatch.setenv("INVESTORCLAW_CONSULTATION_HMAC_KEY", "fixed-key")
    fp_aapl = _compute_fingerprint("AAPL", "gemma4-consult", "Same.")
    fp_msft = _compute_fingerprint("MSFT", "gemma4-consult", "Same.")
    assert fp_aapl != fp_msft


def test_compute_fp_differs_for_different_models(monkeypatch):
    monkeypatch.setenv("INVESTORCLAW_CONSULTATION_HMAC_KEY", "fixed-key")
    fp1 = _compute_fingerprint("AAPL", "gemma4-consult", "Same.")
    fp2 = _compute_fingerprint("AAPL", "nemotron-super-49b", "Same.")
    assert fp1 != fp2


def test_compute_fp_uses_env_key_when_set(monkeypatch):
    """With a fixed env key the fingerprint must match a locally computed HMAC."""
    monkeypatch.setenv("INVESTORCLAW_CONSULTATION_HMAC_KEY", "well-known-key")
    symbol, model, synthesis = "GOOG", "gemma4-consult", "Neutral."
    got = _compute_fingerprint(symbol, model, synthesis)
    expected = hmac.new(
        b"well-known-key",
        f"{symbol}|{model}|{synthesis}".encode(),
        hashlib.sha256,
    ).hexdigest()[:16]
    assert got == expected


def test_session_fp_and_compute_fp_use_different_msg_formats(monkeypatch):
    """update_session_fingerprint and _compute_fingerprint intentionally use
    different message formats (no pipe vs pipe-separated) — they must not collide
    even with identical inputs."""
    monkeypatch.setenv("INVESTORCLAW_CONSULTATION_HMAC_KEY", "same-key")
    symbol = "AAPL"
    # Treat model as prev_fp for session, synthesis same
    session_fp = update_session_fingerprint("gemma4-consult", symbol, "Text.")
    compute_fp = _compute_fingerprint("gemma4-consult", symbol, "Text.")
    assert session_fp != compute_fp, (
        "Session FP and compute FP must not produce identical output: "
        "they bind different fields and collisions would weaken authentication."
    )
