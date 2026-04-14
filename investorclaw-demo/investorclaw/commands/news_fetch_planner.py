#!/usr/bin/env python3
"""
News Fetch Planner — adaptive pre-flight calibration for /portfolio news.

Determines how many symbols to fetch, how many articles per symbol, and
which output mode to use based on three independent inputs:

  1. Portfolio concentration — top-N coverage curve from holdings.json
  2. Model context window   — via OPENCLAW_MODEL env or explicit arg
  3. Provider TPM ceiling   — lookup table keyed by provider prefix

The planner is called automatically by fetch_portfolio_news.py when
--top-n is not explicitly set.  It can also be run standalone:

    python3 news_fetch_planner.py ~/portfolio_reports/holdings.json

Or imported as a module:

    from news_fetch_planner import NewsFetchPlanner
    plan = NewsFetchPlanner.make_plan(holdings, model_id)
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Token budget constants — sourced from lib/context_budget.py
# Do NOT redefine these here; update lib/context_budget.py instead.
# ---------------------------------------------------------------------------
from models.context_budget import (
    SESSION_OVERHEAD,
    OTHER_COMMANDS_BUDGET,
    NEWS_COMPACT_FIXED,
    NEWS_COMPACT_PER_SYMBOL,
    NEWS_STANDARD_PER_SYMBOL,
    PROVIDER_TPM,
    PROVIDER_TPM_UNKNOWN,
    get_model_context_window,
)


# ---------------------------------------------------------------------------
# Data class for the fetch plan
# ---------------------------------------------------------------------------

@dataclass
class NewsFetchPlan:
    # How many symbols to fetch (sorted by portfolio weight descending)
    recommended_top_n: int
    # Articles to store per symbol in the cache (does not affect digest size)
    recommended_articles_per_symbol: int
    # 'compact' | 'standard' — controls digest verbosity
    output_mode: str
    # Portfolio value coverage at recommended_top_n (0-100)
    coverage_pct: float
    # Estimated tokens the news digest will consume in agent context
    estimated_news_tokens: int
    # Token budget allocated to news within this model's context
    news_budget_tokens: int
    # Full context window of the detected model
    model_context_tokens: int
    # Provider string (google / anthropic / xai / …)
    provider: str
    # Model identifier used for the lookup
    model_id: str
    # Provider TPM (tokens per minute) limit
    provider_tpm: int
    # True if estimated session tokens approach the TPM ceiling
    tpm_warning: bool
    # Human-readable explanation
    reason: str

    def to_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Planner
# ---------------------------------------------------------------------------

class NewsFetchPlanner:
    """Compute an adaptive news-fetch plan."""

    # Minimum/maximum top_n guards
    TOP_N_MIN = 5
    TOP_N_MAX = 150

    # Portfolio coverage targets by context tier (stop adding symbols once
    # this % of total value is covered, even if budget allows more)
    COVERAGE_TARGET: Dict[str, float] = {
        "minimal":     70.0,   # < 128K
        "compact":     82.0,   # 128K – 1M
        "standard":    92.0,   # 1M+
    }

    @staticmethod
    def _detect_model() -> str:
        """Read the active model from environment, falling back to a sentinel."""
        for env_key in ("OPENCLAW_MODEL", "LLM_MODEL", "MODEL"):
            val = os.environ.get(env_key, "").strip()
            if val:
                return val
        return "unknown"

    @staticmethod
    def _parse_provider(model_id: str) -> str:
        """Extract provider prefix from 'provider/model-name' or model name."""
        if "/" in model_id:
            return model_id.split("/")[0].lower()
        model_lower = model_id.lower()
        if "gemini" in model_lower:
            return "google"
        if "claude" in model_lower:
            return "anthropic"
        if "grok" in model_lower:
            return "xai"
        if "gpt" in model_lower or "o3" in model_lower or "o4" in model_lower:
            return "openai"
        if "llama" in model_lower or "mistral" in model_lower or "qwen" in model_lower:
            return "ollama"
        return "unknown"

    @staticmethod
    def _get_model_context(model_id: str) -> int:
        """Return context window for a model ID (tokens)."""
        # Allow explicit override
        override = os.environ.get("LLM_CONTEXT_TOKENS", "").strip()
        if override:
            try:
                return int(override)
            except ValueError:
                pass
        return get_model_context_window(model_id)

    @staticmethod
    def _get_provider_tpm(provider: str, model_id: str) -> int:
        """Return TPM limit for the provider/model."""
        provider_map = PROVIDER_TPM.get(provider, {})
        name = model_id.split("/")[-1].lower() if "/" in model_id else model_id.lower()
        # Best substring match within provider
        best_key, best_tpm = "_default", provider_map.get("_default", PROVIDER_TPM_UNKNOWN)
        for key, tpm in provider_map.items():
            if key != "_default" and key in name and len(key) > len(best_key):
                best_key, best_tpm = key, tpm
        return best_tpm

    # Asset types that have news feeds (bonds/cash do not)
    NEWS_ELIGIBLE_TYPES = {"equity", "etf", "mutual_fund", ""}

    @classmethod
    def _concentration_curve(
        cls,
        holdings: Dict[str, dict]
    ) -> List[Tuple[str, float, float]]:
        """
        Return [(symbol, holding_value, cumulative_coverage_pct), …]
        sorted by holding value descending.

        Only equity/ETF positions are included — bonds and cash have no
        news feeds and should not count toward the coverage target.
        """
        eligible = {
            sym: h for sym, h in holdings.items()
            if h.get("asset_type", "equity").lower() in cls.NEWS_ELIGIBLE_TYPES
        }
        total = sum(h.get("value", 0) for h in eligible.values()) or 1.0
        ranked = sorted(eligible.items(), key=lambda kv: kv[1].get("value", 0), reverse=True)
        cumulative = 0.0
        curve = []
        for sym, h in ranked:
            cumulative += h.get("value", 0)
            curve.append((sym, h.get("value", 0), cumulative / total * 100))
        return curve

    @classmethod
    def make_plan(
        cls,
        holdings: Dict[str, dict],
        model_id: Optional[str] = None,
    ) -> NewsFetchPlan:
        """
        Compute and return a NewsFetchPlan.

        Args:
            holdings: Dict of {symbol: {value, asset_type, …}} from holdings.json
            model_id: Model identifier string.  If None, reads from environment.
        """
        if model_id is None:
            model_id = cls._detect_model()

        provider = cls._parse_provider(model_id)
        model_ctx = cls._get_model_context(model_id)
        provider_tpm = cls._get_provider_tpm(provider, model_id)

        # Available context after session overhead and other commands
        news_budget = max(0, model_ctx - SESSION_OVERHEAD - OTHER_COMMANDS_BUDGET)

        # Choose output mode based on news budget
        if news_budget < 8_000:
            mode = "minimal"
            articles_per_sym = 3
        elif news_budget < 50_000:
            mode = "compact"
            articles_per_sym = 5
        else:
            mode = "compact"   # compact by default even with large context;
            articles_per_sym = 10  # more articles stored in cache, not in digest

        # Coverage target for this mode
        coverage_target = cls.COVERAGE_TARGET[mode]

        # Walk the concentration curve to find the smallest top_n that
        # meets both the coverage target and the token budget
        curve = cls._concentration_curve(holdings)
        top_n = cls.TOP_N_MIN
        for i, (sym, val, cov_pct) in enumerate(curve):
            n = i + 1
            est_tokens = NEWS_COMPACT_FIXED + n * NEWS_COMPACT_PER_SYMBOL
            if est_tokens > news_budget:
                break
            top_n = n
            if cov_pct >= coverage_target:
                break

        top_n = max(cls.TOP_N_MIN, min(cls.TOP_N_MAX, top_n))

        # Coverage at recommended top_n
        coverage_pct = curve[top_n - 1][2] if top_n <= len(curve) else 100.0

        # Estimated tokens the compact digest will consume
        est_news_tokens = NEWS_COMPACT_FIXED + top_n * NEWS_COMPACT_PER_SYMBOL

        # TPM warning: would this session exhaust >80% of the per-minute quota?
        est_session_tokens = SESSION_OVERHEAD + OTHER_COMMANDS_BUDGET + est_news_tokens
        tpm_warning = est_session_tokens > provider_tpm * 0.8

        reason = (
            f"{model_ctx // 1_000}K context window ({provider}), "
            f"{mode} mode — top {top_n} symbols covers "
            f"{coverage_pct:.1f}% of portfolio value "
            f"(~{est_news_tokens:,} tokens for news digest)"
        )
        if tpm_warning:
            reason += (
                f". ⚠️  Session ~{est_session_tokens:,} tokens approaches "
                f"provider TPM limit ({provider_tpm:,}/min) — "
                "add delay between commands if running multiple sessions."
            )

        return NewsFetchPlan(
            recommended_top_n=top_n,
            recommended_articles_per_symbol=articles_per_sym,
            output_mode=mode,
            coverage_pct=round(coverage_pct, 1),
            estimated_news_tokens=est_news_tokens,
            news_budget_tokens=news_budget,
            model_context_tokens=model_ctx,
            provider=provider,
            model_id=model_id,
            provider_tpm=provider_tpm,
            tpm_warning=tpm_warning,
            reason=reason,
        )

    @classmethod
    def make_plan_from_holdings_file(
        cls,
        holdings_file: str,
        model_id: Optional[str] = None,
    ) -> NewsFetchPlan:
        """Load holdings.json and compute a plan."""
        path = Path(holdings_file).expanduser()
        with open(path) as f:
            data = json.load(f)

        # Unwrap disclaimer wrapper
        if "data" in data and isinstance(data["data"], dict):
            data = data["data"]

        # Build symbol → {value, asset_type} dict from whichever schema is present
        holdings: Dict[str, dict] = {}

        if "holdings" in data:
            for h in data["holdings"]:
                sym = h.get("symbol", "").strip()
                if sym:
                    holdings[sym] = {
                        "value": float(h.get("value", 0) or 0),
                        "asset_type": h.get("asset_type", "equity"),
                    }
        elif "portfolio" in data:
            for asset_type, assets in data["portfolio"].items():
                if isinstance(assets, dict):
                    for sym, asset_data in assets.items():
                        holdings[sym] = {
                            "value": float(asset_data.get("value", 0) if isinstance(asset_data, dict) else 0),
                            "asset_type": asset_type,
                        }

        return cls.make_plan(holdings, model_id)


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.WARNING)

    parser = argparse.ArgumentParser(
        description="Compute adaptive news-fetch plan for a portfolio."
    )
    parser.add_argument("holdings_file", help="Path to holdings.json")
    parser.add_argument("--model", "-m", default=None,
                        help="Model ID (default: reads OPENCLAW_MODEL env)")
    parser.add_argument("--json", action="store_true",
                        help="Output raw JSON (for scripting)")
    args = parser.parse_args()

    plan = NewsFetchPlanner.make_plan_from_holdings_file(
        args.holdings_file, model_id=args.model
    )

    if args.json:
        print(json.dumps(plan.to_dict(), separators=(',',':')))
    else:
        p = plan
        print(f"\n{'='*60}")
        print(f"  InvestorClaw News Fetch Plan")
        print(f"{'='*60}")
        print(f"  Model:          {p.model_id}")
        print(f"  Provider:       {p.provider}")
        print(f"  Context window: {p.model_context_tokens:,} tokens")
        print(f"  Provider TPM:   {p.provider_tpm:,} tokens/min")
        print(f"")
        print(f"  News budget:    {p.news_budget_tokens:,} tokens")
        print(f"  Output mode:    {p.output_mode}")
        print(f"  Fetch top N:    {p.recommended_top_n} symbols")
        print(f"  Articles/sym:   {p.recommended_articles_per_symbol} (cache only)")
        print(f"  Coverage:       {p.coverage_pct}% of portfolio value")
        print(f"  Est. tokens:    {p.estimated_news_tokens:,}")
        print(f"")
        if p.tpm_warning:
            print(f"  ⚠️  TPM WARNING: session may approach provider limit")
        else:
            print(f"  ✅ TPM: session well within provider limit")
        print(f"")
        print(f"  {p.reason}")
        print(f"{'='*60}")
