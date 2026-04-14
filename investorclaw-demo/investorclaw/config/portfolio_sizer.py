#!/usr/bin/env python3
"""
Portfolio Analyzer - Size-aware LLM configuration recommender

Analyzes portfolio characteristics to recommend optimal LLM configuration.
"""

import csv
import json
from pathlib import Path
from typing import Dict, Optional, Tuple
from collections import defaultdict


def load_portfolio(portfolio_file: str) -> Optional[list]:
    """Load portfolio from CSV."""
    try:
        with open(portfolio_file) as f:
            reader = csv.DictReader(f)
            return list(reader)
    except Exception as e:
        print(f"Error loading portfolio: {e}")
        return None


def analyze_portfolio(portfolio_file: str) -> Dict:
    """
    Analyze portfolio to determine optimal LLM sizing.

    Returns: {
        "holdings_count": int,
        "total_aum": float,
        "sector_distribution": {sector: count},
        "top_3_concentration": float,  # % in top 3 sectors
        "estimated_context_tokens": int,
        "complexity_level": "simple|medium|complex|enterprise",
        "recommendations": {
            "model": str,
            "reason": str
        }
    }
    """

    holdings = load_portfolio(portfolio_file)
    if not holdings:
        return None

    # Basic metrics
    holdings_count = len(holdings)

    # Calculate AUM (sum of quantity * price)
    total_aum = 0.0
    sector_counts = defaultdict(int)

    for holding in holdings:
        try:
            # Handle different field name conventions
            quantity = float(holding.get("Quantity") or holding.get("Shares") or 0)
            price = float(holding.get("Price") or holding.get("Current Price") or 0)
            total_aum += quantity * price
        except (ValueError, TypeError):
            pass

        sector = holding.get("Sector", "Unknown")
        if sector and sector.strip():
            sector_counts[sector] += 1

    # Sector concentration (top 3)
    sorted_sectors = sorted(sector_counts.items(), key=lambda x: x[1], reverse=True)
    top_3_count = sum(count for _, count in sorted_sectors[:3])
    top_3_concentration = (top_3_count / holdings_count * 100) if holdings_count > 0 else 0

    # Estimate context tokens needed
    # Rough estimate: 500 tokens per holding + 5000 base
    estimated_context_tokens = (holdings_count * 500) + 5000

    # Determine complexity level
    if holdings_count < 20:
        complexity_level = "simple"
    elif holdings_count < 50:
        complexity_level = "medium"
    elif holdings_count < 100:
        complexity_level = "complex"
    else:
        complexity_level = "enterprise"

    # Determine recommendations
    recommendations = _get_recommendations(
        holdings_count,
        top_3_concentration,
        estimated_context_tokens,
        complexity_level
    )

    return {
        "holdings_count": holdings_count,
        "total_aum": total_aum,
        "sector_count": len(sector_counts),
        "sector_distribution": dict(sorted_sectors),
        "top_3_concentration": round(top_3_concentration, 1),
        "estimated_context_tokens": estimated_context_tokens,
        "complexity_level": complexity_level,
        "recommendations": recommendations,
    }


def _get_recommendations(
    holdings_count: int,
    sector_concentration: float,
    context_tokens: int,
    complexity_level: str
) -> Dict:
    """
    Generate LLM recommendations based on portfolio characteristics.
    """

    # Base recommendations by complexity
    config = {
        "simple": {
            "model": "openai/gpt-4.1-nano",
            "reason": "Simple portfolio - GPT-4.1-nano handles all analysis efficiently"
        },
        "medium": {
            "model": "openai/gpt-4.1-nano",
            "reason": "Medium portfolio - GPT-4.1-nano provides excellent analysis quality"
        },
        "complex": {
            "model": "together/MiniMaxAI/MiniMax-M2.7",
            "reason": "Complex portfolio - MiniMax-M2.7 (hybrid) provides best QC4=97 synthesis quality with consultation"
        },
        "enterprise": {
            "model": "xai/grok-4-1-fast",
            "reason": "Large portfolio (500+ holdings) - Grok 4.1 Fast 2M context + 4M TPM for enterprise scale"
        },
    }

    rec = config[complexity_level].copy()

    # Upgrade to higher-context model if high sector concentration (concentration risk)
    if sector_concentration > 60 and complexity_level in ["simple", "medium"]:
        rec["model"] = "together/MiniMaxAI/MiniMax-M2.7"
        rec["reason"] += " [Upgraded to MiniMax-M2.7: high sector concentration]"

    return rec


def print_analysis(analysis: Dict) -> None:
    """Pretty-print portfolio analysis and recommendations."""

    if not analysis:
        print("❌ Could not analyze portfolio")
        return

    print("\n" + "="*70)
    print("📊 PORTFOLIO ANALYSIS")
    print("="*70)

    print(f"\n📈 Portfolio Characteristics:")
    print(f"   Holdings: {analysis['holdings_count']:,}")
    print(f"   Total AUM: ${analysis['total_aum']:,.0f}")
    print(f"   Sectors: {analysis['sector_count']}")
    print(f"   Top 3 concentration: {analysis['top_3_concentration']:.1f}%")
    print(f"   Complexity level: {analysis['complexity_level'].upper()}")

    print(f"\n💾 Context Requirements:")
    print(f"   Estimated tokens: {analysis['estimated_context_tokens']:,}")
    if analysis['estimated_context_tokens'] < 50000:
        print(f"   Status: ✅ Low (most models sufficient)")
    elif analysis['estimated_context_tokens'] < 100000:
        print(f"   Status: ⚠️  Medium (Groq 131K recommended)")
    elif analysis['estimated_context_tokens'] < 500000:
        print(f"   Status: ⚠️  High (2M context needed)")
    else:
        print(f"   Status: ❌ Very high (enterprise plan needed)")

    print(f"\n🎯 LLM Recommendation:")
    rec = analysis['recommendations']
    print(f"   Model: {rec['model']}")
    print(f"   Reason: {rec['reason']}")

    print(f"\n💰 Cost Estimate (monthly, 100 queries):")
    cost_estimate = _estimate_cost(rec['model'], analysis['holdings_count'])
    print(f"   {cost_estimate}")

    print("="*70 + "\n")


def _estimate_cost(model: str, holdings_count: int) -> str:
    """Rough cost estimate for monthly usage (single-model architecture)."""

    # Rough token averages per workflow for different portfolio sizes
    if holdings_count < 20:
        avg_tokens_per_workflow = 5000
    elif holdings_count < 50:
        avg_tokens_per_workflow = 25000
    elif holdings_count < 100:
        avg_tokens_per_workflow = 50000
    else:
        avg_tokens_per_workflow = 75000

    # Estimate: 8 workflows per query, 100 queries/month
    monthly_tokens = avg_tokens_per_workflow * 8 * 100

    # Pricing (very rough, per 1M tokens)
    pricing = {
        "openai/gpt-4.1-nano": 0.10,
        "together/MiniMaxAI/MiniMax-M2.7": 0.30,
        "xai/grok-4-1-fast": 0.20,
    }

    total_cost = (monthly_tokens / 1_000_000) * pricing.get(model, 0.20)

    if total_cost < 1:
        return f"${total_cost:.2f}/month (very cheap - free tier likely covers)"
    elif total_cost < 10:
        return f"${total_cost:.2f}/month (micro-transaction tier)"
    elif total_cost < 50:
        return f"${total_cost:.2f}/month (standard developer tier)"
    else:
        return f"${total_cost:.2f}/month (premium tier recommended)"


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python3 portfolio_sizer.py <portfolio.csv>")
        sys.exit(1)

    portfolio_file = sys.argv[1]
    analysis = analyze_portfolio(portfolio_file)
    print_analysis(analysis)
