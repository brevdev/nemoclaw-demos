"""
Model ID normalization tests for lib/context_budget.get_model_context_window().

Verifies that the lookup handles edge cases correctly: provider prefixes,
mixed case, whitespace, partial names, and that previously incorrect or
speculative values have been fixed to match public specifications.
"""
import sys
from pathlib import Path

_skill_root = Path(__file__).parent.parent
if str(_skill_root) not in sys.path:
    sys.path.insert(0, str(_skill_root))

import pytest
from models.context_budget import get_model_context_window


# ---------------------------------------------------------------------------
# Provider-prefix stripping
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("prefixed, bare", [
    ("openai/gpt-4.1",           "gpt-4.1"),
    ("openai/gpt-4.1-mini",      "gpt-4.1-mini"),
    ("openai/gpt-4.1-nano",      "gpt-4.1-nano"),
    ("xai/grok-4-1-fast",        "grok-4-1-fast"),
    ("xai/grok-4-1-fast-reasoning", "grok-4-1-fast-reasoning"),
])
def test_provider_prefix_gives_same_result_as_bare(prefixed, bare):
    assert get_model_context_window(prefixed) == get_model_context_window(bare)


# ---------------------------------------------------------------------------
# Case normalization
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model_id", [
    "GPT-4.1", "Gpt-4.1", "gpt-4.1",
    "CLAUDE-SONNET-4-6", "Claude-Sonnet-4-6",
    "GEMINI-2.5-FLASH",
])
def test_case_insensitive_lookup(model_id):
    lower = model_id.lower()
    assert get_model_context_window(model_id) == get_model_context_window(lower)


# ---------------------------------------------------------------------------
# Whitespace stripping
# ---------------------------------------------------------------------------

def test_leading_trailing_whitespace_stripped():
    assert get_model_context_window("  gpt-4.1  ") == get_model_context_window("gpt-4.1")


# ---------------------------------------------------------------------------
# Corrections from public-spec audit (Apr 2026)
# ---------------------------------------------------------------------------

def test_gemini_2_5_flash_lite_is_1m_not_4m():
    """gemini-2.5-flash-lite was incorrectly set to 4M; spec says 1_048_576."""
    assert get_model_context_window("gemini-2.5-flash-lite") == 1_048_576


def test_claude_sonnet_4_6_is_1m():
    """claude-sonnet-4-6 context upgraded to 1M with the 4.6 generation."""
    assert get_model_context_window("claude-sonnet-4-6") == 1_048_576


def test_claude_opus_4_6_is_1m():
    assert get_model_context_window("claude-opus-4-6") == 1_048_576


def test_claude_4_5_family_is_200k():
    for model in ("claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"):
        assert get_model_context_window(model) == 200_000, f"Failed for {model}"


def test_grok_4_is_256k():
    """grok-4 (not grok-4-1-fast) has 256K context per xAI docs."""
    assert get_model_context_window("grok-4") == 262_144


def test_sonar_pro_is_200k():
    """sonar-pro has 200K context vs sonar at 128K."""
    assert get_model_context_window("sonar") == 128_000
    assert get_model_context_window("sonar-pro") == 200_000


# ---------------------------------------------------------------------------
# Fallback behaviour
# ---------------------------------------------------------------------------

def test_completely_unknown_model_falls_back_to_128k():
    assert get_model_context_window("zz-fake-model-9999") == 128_000


def test_none_like_empty_string_falls_back():
    assert get_model_context_window("") == 128_000


def test_custom_default_respected():
    assert get_model_context_window("zz-fake-model-9999", default=32_000) == 32_000
