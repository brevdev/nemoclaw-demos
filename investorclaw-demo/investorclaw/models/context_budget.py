#!/usr/bin/env python3
"""
Context Budget — single source of truth for model context windows,
token budgets, capability thresholds, and provider TPM limits.

Previously these constants were scattered across:
  context_window_monitor.py  (model windows + warning thresholds)
  model_context_detector.py  (model windows + capability enum)
  commands/news_fetch_planner.py  (session overhead + provider TPM)

All three import from here.  Update model windows and budget constants
in this file only.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, Optional


# ---------------------------------------------------------------------------
# Capability tiers
# ---------------------------------------------------------------------------

class ModelCapability(Enum):
    """Context window capability categories for InvestorClaw operations."""
    INSUFFICIENT = "insufficient"   # < 128K  — not recommended
    MINIMUM      = "minimum"        # 128K–200K
    RECOMMENDED  = "recommended"    # 200K–1M
    EXCELLENT    = "excellent"      # 1M+


# Absolute token thresholds for capability classification
MIN_CONTEXT         = 128_000   # Minimum viable for full command set
RECOMMENDED_CONTEXT = 200_000   # Full feature support
OPTIMAL_CONTEXT     = 1_000_000 # Complex agentic / multi-command sessions


# ---------------------------------------------------------------------------
# Model context windows (tokens)
# Merged from context_window_monitor.py + model_context_detector.py.
# Keys are exact model identifiers as reported by providers.
# ---------------------------------------------------------------------------

MODEL_CONTEXT_WINDOWS: Dict[str, int] = {
    # Values sourced from official provider documentation (Apr 2026).
    # Context windows that are unverified or based on pre-release claims are
    # marked with a comment.  Remove or update entries when models are
    # officially released with confirmed specifications.

    # ── Groq-hosted (Meta Llama) ──────────────────────────────────────────
    # Source: console.groq.com/docs/models
    "llama-3.1-8b-instant":       131_072,
    "llama-3.3-70b-versatile":    131_072,
    "llama-3.1-70b-versatile":    131_072,
    "mixtral-8x7b-32768":          32_768,

    # ── xAI Grok ──────────────────────────────────────────────────────────
    # Source: docs.x.ai/docs/models
    "grok-3":                     131_072,   # 128K; grok-3 family baseline
    "grok-3-mini":                131_072,   # same family
    "grok-4":                     262_144,   # 256K; verified for grok-4
    "grok-4-1-fast":            2_000_000,   # 2M context
    "grok-4-1-fast-reasoning":  2_000_000,
    "xai/grok-4-1-fast":        2_000_000,
    "xai/grok-4-1-fast-reasoning":2_000_000,

    # ── Anthropic Claude ──────────────────────────────────────────────────
    # Source: docs.anthropic.com/en/docs/about-claude/models
    # 4.x generation (Sonnet/Opus 4.6): 1M context window
    "claude-opus-4-6":          1_048_576,
    "claude-sonnet-4-6":        1_048_576,
    # 4.5 generation: 200K context window
    "claude-opus-4-5":            200_000,
    "claude-sonnet-4-5":          200_000,
    "claude-haiku-4-5":           200_000,
    # Family-level aliases (maps to most recent known spec)
    "claude-opus":                200_000,   # pre-4.6 default
    "claude-sonnet":              200_000,   # pre-4.6 default
    "claude-haiku":               200_000,

    # ── Google Gemini ─────────────────────────────────────────────────────
    # Source: ai.google.dev/gemini-api/docs/models (Apr 2026)
    "gemini-2.0-flash":         1_048_576,
    "gemini-2.0":               1_048_576,
    "gemini-2.5-pro":           1_048_576,
    "gemini-2.5-flash":         1_048_576,
    "gemini-2.5-flash-lite":    1_048_576,
    "gemini-pro":                  32_000,

    # ── OpenAI ────────────────────────────────────────────────────────────
    # Source: platform.openai.com/docs/models (Apr 2026)
    "gpt-4.1":                  1_047_576,
    "gpt-4.1-mini":             1_047_576,
    "gpt-4.1-nano":             1_047_576,
    "openai/gpt-4.1":           1_047_576,
    "openai/gpt-4.1-mini":      1_047_576,
    "openai/gpt-4.1-nano":      1_047_576,
    "gpt-4o":                     128_000,
    "gpt-4o-mini":                128_000,
    "gpt-4":                      128_000,
    "gpt-3.5":                     16_000,
    "o3":                         200_000,   # exact limit not public; estimate
    "o4-mini":                    200_000,   # exact limit not public; estimate

    # ── Perplexity ────────────────────────────────────────────────────────
    # Source: docs.perplexity.ai/models (Apr 2026)
    "sonar":                      128_000,
    "sonar-pro":                  200_000,
    "sonar-reasoning":            128_000,

    # ── Nvidia Nemotron ───────────────────────────────────────────────────
    # Source: build.nvidia.com/explore/reasoning (Apr 2026)
    "nemotron-super-49b":         131_072,
    "nemotron-super-120b":        131_072,
    "nemotron-3-nano":            131_072,

    # ── Together AI ───────────────────────────────────────────────────────
    "together-llama":              32_000,
    "qwen3":                      131_072,
    "qwen-plus":                  131_072,

    # ── Ollama (local) ────────────────────────────────────────────────────
    "qwen:14b":                    32_768,
    "qwen2.5:14b":                 32_768,
    "mixtral:latest":              32_768,
    "gemma4:26b":                 131_072,
    "gemma4:27b":                 131_072,
    "gemma4:e4b":                 131_072,
    "gemma3:27b":                 131_072,
    "gemma3:12b":                 131_072,
    "ollama-default":               4_000,
}


# ---------------------------------------------------------------------------
# Context-usage warning thresholds  (fraction of total context window, 0–100)
# ---------------------------------------------------------------------------

WARNINGS: Dict[str, float] = {
    "info":     70.0,   # informational nudge
    "caution":  85.0,   # recommend switching to higher-context model
    "critical": 95.0,   # output quality likely degraded
}


# ---------------------------------------------------------------------------
# Session token budget constants (all values in tokens)
# Source: docs/MODEL_CONTEXT_REQUIREMENTS.md + empirical calibration
# ---------------------------------------------------------------------------

# Fixed overhead every InvestorClaw session consumes regardless of portfolio
# size: system prompt, guardrails, SKILL.md, conversation history, reasoning.
SESSION_OVERHEAD = 65_000

# Budget consumed by other commands already in session
# (holdings snapshot + performance + analyst summary + bonds summary).
OTHER_COMMANDS_BUDGET = 30_000

# News-specific compact digest constants
NEWS_COMPACT_FIXED       = 2_000   # digest header, top-movers, timestamps
NEWS_COMPACT_PER_SYMBOL  =    55   # tokens per symbol row (compact mode)
NEWS_STANDARD_PER_SYMBOL =   220   # tokens per symbol when summaries included


# ---------------------------------------------------------------------------
# Provider TPM limits (tokens per minute) — tier-dependent
#
# Values below are for the entry-level paid tier (Tier 1) unless noted.
# Most providers have multiple tiers; higher tiers offer proportionally more
# throughput.  These constants are used for the tpm_warning heuristic in
# NewsFetchPlanner — a warning fires when a session approaches 80% of the
# per-minute budget.  If you are on a higher tier, override via env var:
#   INVESTORCLAW_PROVIDER_TPM=<provider>:<tpm_int>
#
# Sources: provider rate-limits pages, Apr 2026.
# ---------------------------------------------------------------------------

PROVIDER_TPM_UNKNOWN = 200_000   # conservative fallback for unknown providers

PROVIDER_TPM: Dict[str, Dict[str, int]] = {
    # ── Google Gemini ─────────────────────────────────────────────────────
    # Source: ai.google.dev/gemini-api/docs/rate-limits (Apr 2026)
    # Pay-as-you-go (Tier 1 equivalent): 1M–4M TPM depending on model.
    "google": {
        "gemini-2.5-pro":          1_000_000,
        "gemini-2.5-flash":        1_000_000,
        "gemini-2.5-flash-lite":   4_000_000,
        "gemini-2.0-flash":        1_000_000,
        "_default":                1_000_000,
    },
    # ── Anthropic Claude ──────────────────────────────────────────────────
    # Source: docs.anthropic.com/en/api/rate-limits (Apr 2026)
    # Tier 1 (< $100 cumulative spend):  20K input TPM / 4K output TPM.
    # Tier 2 (> $100 cumulative spend):  40K input TPM / 8K output TPM.
    # Tier 3 (> $1K  cumulative spend): 200K input TPM / 40K output TPM.
    # Tier 4 (> $5K  cumulative spend): 400K input TPM / 80K output TPM.
    # Prompt-cache reads do NOT count against input TPM.
    # The _default here uses Tier 1 as the conservative baseline.  Update to
    # match your account tier to avoid spurious warnings.
    "anthropic": {
        # Tier 1:  20K / 4K   Tier 2:  40K / 8K
        # Tier 3: 200K / 40K  Tier 4: 400K / 80K  (input/output TPM respectively)
        "_default":  20_000,   # Tier 1 (conservative baseline)
    },
    # ── xAI Grok ──────────────────────────────────────────────────────────
    # Source: docs.x.ai/docs/key-information/consumption-and-rate-limits
    # Tier-based on cumulative API spend; range 4M–10M TPM for production.
    "xai": {
        "_default": 4_000_000,   # entry-level paid tier
    },
    # ── Together AI ───────────────────────────────────────────────────────
    "together": {
        "_default": 500_000,
    },
    # ── Groq ──────────────────────────────────────────────────────────────
    # Source: console.groq.com/docs/rate-limits (Apr 2026)
    # Developer (paid) tier: 6M TPM for llama family; free tier is 6K TPM.
    "groq": {
        "llama-3.1-8b-instant":    6_000_000,
        "llama-3.3-70b-versatile": 6_000_000,
        "_default":                6_000_000,
    },
    # ── OpenAI ────────────────────────────────────────────────────────────
    # Source: platform.openai.com/docs/guides/rate-limits (Apr 2026)
    # Tier 1 (< $100 cumulative spend): ~1M TPM for GPT-4.1 family.
    # Tier 2 (> $100):  2M TPM; Tier 4 (> $5K): 10M TPM.
    "openai": {
        "gpt-4.1":      1_000_000,   # Tier 1
        "gpt-4.1-mini": 1_000_000,
        "gpt-4.1-nano": 1_000_000,
        "gpt-4o":       1_000_000,
        "_default":     1_000_000,   # Tier 1 baseline
    },
    # ── Ollama (local) ────────────────────────────────────────────────────
    # Local inference; TPM is hardware-bound, not a provider quota.
    "ollama": {
        "_default":     50_000,
    },
    # ── Perplexity ────────────────────────────────────────────────────────
    # Source: docs.perplexity.ai/docs/admin/rate-limits-usage-tiers
    # Rate-limited by RPM (50–500 RPM) rather than TPM; 200K is an estimate.
    "perplexity": {
        "_default": 200_000,
    },
}


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def get_model_context_window(model_id: str, default: int = 128_000) -> int:
    """
    Return the context window size for model_id.

    Performs an exact lookup first, then a prefix/substring match for
    provider-prefixed identifiers (e.g. "openai/gpt-4.1-nano").
    Falls back to *default* when the model is not in the table.
    """
    if not model_id:
        return default
    key = model_id.strip().lower()
    if key in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[key]
    # Prefix match for aliases like "openai/gpt-4o"
    for registered, size in MODEL_CONTEXT_WINDOWS.items():
        if key.endswith(registered) or registered.endswith(key):
            return size
    return default


def get_model_capability(model_id: str) -> ModelCapability:
    """Classify a model by its context window size."""
    window = get_model_context_window(model_id)
    if window >= OPTIMAL_CONTEXT:
        return ModelCapability.EXCELLENT
    if window >= RECOMMENDED_CONTEXT:
        return ModelCapability.RECOMMENDED
    if window >= MIN_CONTEXT:
        return ModelCapability.MINIMUM
    return ModelCapability.INSUFFICIENT


def get_provider_tpm(provider: str, model: str) -> int:
    """Return the TPM limit for a provider+model pair."""
    provider_map = PROVIDER_TPM.get(provider.lower(), {})
    return provider_map.get(model, provider_map.get("_default", PROVIDER_TPM_UNKNOWN))
