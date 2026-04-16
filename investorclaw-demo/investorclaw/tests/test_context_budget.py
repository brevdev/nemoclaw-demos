"""
Unit tests for lib/context_budget.py.

Validates model context window lookups, capability classification,
and provider TPM lookups.  All values are tested against the public
specifications documented in lib/context_budget.py (Apr 2026).
"""
import sys
from pathlib import Path

_skill_root = Path(__file__).parent.parent
if str(_skill_root) not in sys.path:
    sys.path.insert(0, str(_skill_root))

import pytest
from models.context_budget import (
    MODEL_CONTEXT_WINDOWS,
    OPTIMAL_CONTEXT,
    PROVIDER_TPM_UNKNOWN,
    ModelCapability,
    get_model_capability,
    get_model_context_window,
    get_provider_tpm,
)


# ---------------------------------------------------------------------------
# get_model_context_window — exact matches
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model_id, expected", [
    ("gpt-4.1",               1_047_576),
    ("gpt-4.1-mini",          1_047_576),
    ("gpt-4.1-nano",          1_047_576),
    ("gpt-4o",                  128_000),
    ("gpt-4o-mini",             128_000),
    ("gpt-4",                   128_000),
    ("o3",                      200_000),
    ("claude-sonnet-4-6",     1_048_576),
    ("claude-opus-4-6",       1_048_576),
    ("claude-opus-4-5",         200_000),
    ("claude-haiku-4-5",        200_000),
    ("claude-sonnet",           200_000),
    ("gemini-2.5-flash",      1_048_576),
    ("gemini-2.5-flash-lite", 1_048_576),  # was 4M (bug), now 1M per spec
    ("gemini-2.5-pro",        1_048_576),
    ("grok-4-1-fast",         2_000_000),
    ("grok-4",                  262_144),
    ("grok-3",                  131_072),
    ("llama-3.3-70b-versatile", 131_072),
    ("sonar",                   128_000),
    ("sonar-pro",               200_000),
])
def test_exact_lookup(model_id, expected):
    assert get_model_context_window(model_id) == expected


# ---------------------------------------------------------------------------
# get_model_context_window — case-insensitivity and provider prefix
# ---------------------------------------------------------------------------

def test_case_insensitive():
    assert get_model_context_window("GPT-4.1") == get_model_context_window("gpt-4.1")


def test_provider_prefix_openai():
    assert get_model_context_window("openai/gpt-4.1") == 1_047_576


def test_provider_prefix_xai():
    assert get_model_context_window("xai/grok-4-1-fast") == 2_000_000


def test_unknown_model_returns_default():
    assert get_model_context_window("completely-unknown-xyz-model") == 128_000


def test_empty_model_id_returns_default():
    assert get_model_context_window("") == 128_000


def test_custom_default():
    assert get_model_context_window("unknown", default=64_000) == 64_000


# ---------------------------------------------------------------------------
# Removed / speculative models should NOT be in the registry
# ---------------------------------------------------------------------------

def test_gpt5_removed():
    """gpt-5 was removed as it was not released at time of spec."""
    key = "gpt-5"
    assert key not in MODEL_CONTEXT_WINDOWS, (
        f"'{key}' should not be in MODEL_CONTEXT_WINDOWS (unreleased model)"
    )


def test_gpt5_4_removed():
    """gpt-5.4 was removed as it was unverified."""
    key = "gpt-5.4"
    assert key not in MODEL_CONTEXT_WINDOWS, (
        f"'{key}' should not be in MODEL_CONTEXT_WINDOWS (unverified model)"
    )


def test_speculative_grok_checkpoint_removed():
    """Speculative xAI checkpoint IDs should not be in the registry."""
    for key in ("grok-4.20-0309-reasoning", "grok-4.1-reasoning"):
        assert key not in MODEL_CONTEXT_WINDOWS, (
            f"'{key}' should not be in MODEL_CONTEXT_WINDOWS (unverified checkpoint)"
        )


# ---------------------------------------------------------------------------
# get_model_capability
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model_id, expected_cap", [
    ("grok-4-1-fast",     ModelCapability.EXCELLENT),    # 2M ≥ 1M
    ("claude-sonnet-4-6", ModelCapability.EXCELLENT),    # 1M ≥ 1M
    ("claude-opus-4-5",   ModelCapability.RECOMMENDED),  # 200K ≥ 200K
    ("claude-sonnet",     ModelCapability.RECOMMENDED),  # 200K ≥ 200K
    ("llama-3.1-8b-instant", ModelCapability.MINIMUM),  # 131K ≥ 128K
    ("gemma3:12b",        ModelCapability.MINIMUM),      # 131K ≥ 128K
    ("ollama-default",    ModelCapability.INSUFFICIENT), # 4K < 128K
])
def test_capability_classification(model_id, expected_cap):
    assert get_model_capability(model_id) == expected_cap


# ---------------------------------------------------------------------------
# get_provider_tpm
# ---------------------------------------------------------------------------

def test_anthropic_tier1_default():
    """Anthropic default is Tier 1 = 20K TPM (conservative baseline)."""
    assert get_provider_tpm("anthropic", "claude-sonnet-4-6") == 20_000


def test_openai_gpt41_tier1():
    assert get_provider_tpm("openai", "gpt-4.1") == 1_000_000


def test_google_gemini_flash():
    assert get_provider_tpm("google", "gemini-2.5-flash") == 1_000_000


def test_groq_llama():
    assert get_provider_tpm("groq", "llama-3.3-70b-versatile") == 6_000_000


def test_unknown_provider_returns_fallback():
    assert get_provider_tpm("unknown_provider", "some-model") == PROVIDER_TPM_UNKNOWN


def test_ollama_local():
    assert get_provider_tpm("ollama", "gemma4:26b") == 50_000
