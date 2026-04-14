#!/usr/bin/env python3
"""
Context Window Monitor

Detects when operational LLM is running low on context and warns user
to switch to a higher-context model for better performance.

This is important for users with Groq+Groq (131K) who may want to
use OpenClaw for general work.
"""

import os
import sys
from pathlib import Path
from typing import Optional, Dict


CONFIG_FILE = Path.home() / ".investorclaw" / "setup_config.json"

# Model context windows and warning thresholds are now in lib/context_budget.py.
# Import from there to avoid drift between modules.
from models.context_budget import MODEL_CONTEXT_WINDOWS, WARNINGS


def get_operational_model() -> Optional[Dict]:
    """Load operational LLM config from setup."""
    try:
        import json
        config_file = CONFIG_FILE
        if config_file.exists():
            with open(config_file, 'r') as f:
                config = json.load(f)
                return config.get("operational", {})
    except Exception:
        pass
    return None


def get_model_context_window(provider: str, model: str) -> Optional[int]:
    """Get context window for a model."""
    # Try full model name first
    if model in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[model]

    # Try provider/model format
    full_name = f"{provider.lower()}/{model.lower()}"
    if full_name in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[full_name]

    # Try just provider
    if provider.lower() in MODEL_CONTEXT_WINDOWS:
        return MODEL_CONTEXT_WINDOWS[provider.lower()]

    # Unknown model
    return None


def estimate_context_usage(
    conversation_turns: int = 5,
    portfolio_size: int = 50,
    include_history: bool = True,
    output_mode: str = "compact",
) -> int:
    """
    Estimate context tokens needed for an OpenClaw session.

    Args:
        conversation_turns: Number of back-and-forth turns so far
        portfolio_size: Number of holdings in portfolio (for InvestorClaw)
        include_history: Whether conversation history is preserved
        output_mode: "compact" (default, all scripts emit compact JSON stdout)
                     or "verbose" (legacy full CDM output mode)

    Returns:
        Estimated tokens needed

    Compact mode calibration (measured against UBS 215-equity portfolio, Apr 2026):
        holdings stdout:    ~1,050 tokens  (top-25 + totals, fixed regardless of size)
        performance stdout: ~750 tokens    (portfolio-level metrics only)
        analyst compact:    ~15 tokens/sym (top-25 rated symbols shown)
        news compact:       ~3,000 tokens  (posture, top-5 movers, top-20 digest, themes)
        bond compact:       ~500 tokens    (summary + maturity ladder)
        SKILL.md injection: ~3,000 tokens  (system prompt)

    Verbose mode calibration (pre-compact, CDM full output):
        ~200 tokens per holding (full CDM position JSON)
    """
    # Base system instructions, identity, skills, SKILL.md
    base_context = 8000  # includes SKILL.md injection (~3K) + OpenClaw overhead

    # Conversation history (~1000 tokens per turn)
    conversation_context = conversation_turns * 1000 if include_history else 1000

    if output_mode == "compact":
        # Fixed compact cores (don't scale with portfolio size)
        _holdings_core    = 1050   # top-25 equity + sector weights + bond/cash summary
        _performance_core = 750    # portfolio-level metrics only
        _news_core        = 3000   # posture + top-5 movers + top-20 digest + themes
        _bond_core        = 500    # metrics + maturity ladder + recommendations

        # Analyst output scales with symbols shown (capped at 25 in compact)
        _analyst_tokens = min(portfolio_size, 25) * 15

        # Consultation synthesis block (if enabled): ~500 tokens per command
        _consultation = 500

        portfolio_context = (
            _holdings_core + _performance_core + _news_core + _bond_core
            + _analyst_tokens + _consultation
        )
    else:
        # Verbose / legacy: full CDM output, ~200 tokens per holding
        portfolio_context = portfolio_size * 200

    # Reasoning/intermediate steps
    reasoning_context = 3000

    total = base_context + conversation_context + portfolio_context + reasoning_context
    return total


def check_context_available(
    conversation_turns: int = 5,
    portfolio_size: int = 50
) -> Dict:
    """
    Check if operational model has enough context.

    Returns:
        {
            "model": "model_name",
            "context_window": 131072,
            "estimated_usage": 45000,
            "usage_percent": 34.3,
            "status": "OK" | "INFO" | "CAUTION" | "CRITICAL",
            "message": "...",
            "recommendation": "..."
        }
    """
    operational = get_operational_model()
    if not operational:
        return {
            "status": "UNKNOWN",
            "message": "No operational model configured",
            "recommendation": "Run setup wizard: python3 skill/setup_wizard.py"
        }

    provider = operational.get("provider", "unknown")
    model = operational.get("model", "unknown")

    context_window = get_model_context_window(provider, model)
    if not context_window:
        return {
            "status": "UNKNOWN",
            "model": f"{provider}/{model}",
            "message": "Unknown model context window",
            "recommendation": "Check DEPLOYMENT_ARCHITECTURE.md for model specs"
        }

    estimated_usage = estimate_context_usage(
        conversation_turns=conversation_turns,
        portfolio_size=portfolio_size,
        include_history=True
    )

    usage_percent = (estimated_usage / context_window) * 100

    # Determine status
    if usage_percent > WARNINGS["critical"]:
        status = "CRITICAL"
        message = f"⚠️  CRITICAL: Context usage at {usage_percent:.1f}% ({estimated_usage:,} / {context_window:,} tokens)"
    elif usage_percent > WARNINGS["caution"]:
        status = "CAUTION"
        message = f"⚠️  CAUTION: Context usage at {usage_percent:.1f}% ({estimated_usage:,} / {context_window:,} tokens)"
    elif usage_percent > WARNINGS["info"]:
        status = "INFO"
        message = f"ℹ️  INFO: Context usage at {usage_percent:.1f}% ({estimated_usage:,} / {context_window:,} tokens)"
    else:
        status = "OK"
        message = f"✓ Context available: {usage_percent:.1f}% used ({estimated_usage:,} / {context_window:,} tokens)"

    # Recommendation
    if status in ["CAUTION", "CRITICAL"]:
        recommendation = (
            f"Your operational model ({model}, {context_window:,} tokens) is getting tight.\n"
            f"   Consider switching to a higher-context model:\n"
            f"   • xAI Grok: 2M tokens (~$15/month)\n"
            f"   • Google Gemini: 1M tokens (~$25/month)\n"
            f"   • Claude: 200K tokens (~$50-100/month)\n"
            f"   Or use focused InvestorClaw-only sessions."
        )
    else:
        recommendation = "Context is sufficient for current session."

    return {
        "status": status,
        "model": f"{provider}/{model}",
        "context_window": context_window,
        "estimated_usage": estimated_usage,
        "usage_percent": usage_percent,
        "message": message,
        "recommendation": recommendation
    }


def warn_if_low_context() -> None:
    """
    Check context and print warning to stderr if needed.

    Prints to stderr so it never corrupts JSON stdout from analysis commands.
    Only prints when status is INFO, CAUTION, or CRITICAL (not OK).
    """
    import sys as _sys
    check = check_context_available()

    if check["status"] in ("UNKNOWN", "OK"):
        return  # No warning needed

    print(check["message"], file=_sys.stderr)

    if check["status"] in ["CAUTION", "CRITICAL"]:
        print(f"\n{check['recommendation']}\n", file=_sys.stderr)


if __name__ == "__main__":
    # Test script
    print("Context Window Monitor")
    print("=" * 70)

    operational = get_operational_model()
    if not operational:
        print("No operational model configured.")
        print("Run setup wizard: python3 skill/setup_wizard.py")
        sys.exit(1)

    print(f"\nOperational Model: {operational.get('provider')} / {operational.get('model')}")

    # Test different scenarios
    scenarios = [
        ("Quick session", 3, 20),
        ("Normal session", 10, 50),
        ("Long research", 30, 100),
        ("Large portfolio", 5, 500),
    ]

    for scenario_name, turns, holdings in scenarios:
        check = check_context_available(turns, holdings)
        print(f"\n{scenario_name} ({turns} turns, {holdings} holdings):")
        print(f"  {check['message']}")
        print(f"  Status: {check['status']}")
