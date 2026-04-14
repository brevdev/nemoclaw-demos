#!/usr/bin/env python3
"""
Deployment Modes Architecture

Defines operational modes for InvestorClaw with associated features,
guardrails, and LLM recommendations.

Modes:
  - SINGLE_INVESTOR: Individual portfolio management (retail)
  - FA_PROFESSIONAL: Financial advisor portfolio management
  - ROBO_ADVISOR: (Future) Automated portfolio recommendations
  - HEDGE_FUND: (Future) Institutional portfolio management
"""

from enum import Enum
from typing import List, Dict, Set
from dataclasses import dataclass, field


class DeploymentMode(Enum):
    """Deployment modes for InvestorClaw."""
    SINGLE_INVESTOR = "single_investor"
    FA_PROFESSIONAL = "fa_professional"
    # Future modes:
    # ROBO_ADVISOR = "robo_advisor"
    # HEDGE_FUND = "hedge_fund"


class Feature(Enum):
    """Available features in InvestorClaw."""
    # Core features (all modes)
    HOLDINGS_SNAPSHOT = "holdings_snapshot"
    PERFORMANCE_ANALYSIS = "performance_analysis"
    NEWS_SENTIMENT = "news_sentiment"
    ANALYST_RATINGS = "analyst_ratings"
    SESSION_CALIBRATION = "session_calibration"
    REPORTS_EXPORT = "reports_export"
    BASIC_BOND_REPORTING = "basic_bond_reporting"  # Holdings snapshot + simple metrics

    # Educational features
    REBALANCING_EDUCATIONAL = "rebalancing_educational"
    SECTOR_ANALYSIS_EDUCATIONAL = "sector_analysis_educational"

    # Advanced features (FA mode)
    ETF_EXPANSION = "etf_expansion"
    ETF_CONSTITUENT_ANALYSIS = "etf_constituent_analysis"
    TAX_LOSS_HARVESTING = "tax_loss_harvesting"
    SECTOR_REBALANCING_TACTICAL = "sector_rebalancing_tactical"
    MODEL_PORTFOLIO_COMPARISON = "model_portfolio_comparison"
    COMPLIANCE_DOCUMENTATION = "compliance_documentation"
    MULTI_PORTFOLIO_MANAGEMENT = "multi_portfolio_management"
    AUDIT_TRAIL = "audit_trail"
    BOND_ANALYSIS = "bond_analysis"
    FIXED_INCOME_ANALYSIS = "fixed_income_analysis"

    # Future features
    # RISK_ATTRIBUTION = "risk_attribution"
    # FACTOR_ANALYSIS = "factor_analysis"
    # INSTITUTIONAL_BENCHMARKING = "institutional_benchmarking"


class GuardrailLevel(Enum):
    """Guardrail enforcement levels."""
    EDUCATIONAL = "educational"           # "may indicate", "for educational purposes"
    ADVISORY = "advisory"                 # "consider", "you might evaluate"
    INSTITUTIONAL = "institutional"       # Full recommendations with audit trail


@dataclass
class GuardrailRule:
    """A guardrail rule for a deployment mode."""
    name: str
    description: str
    enforcement_level: GuardrailLevel
    example_safe: str
    example_unsafe: str


@dataclass
class PortfolioHandlingConfig:
    """Portfolio handling configuration per mode."""
    expand_etfs: bool
    max_holdings_without_upgrade: int  # When to suggest premium tier
    context_estimation_multiplier: float  # How many tokens per holding


@dataclass
class LLMRecommendation:
    """LLM recommendation for mode + complexity."""
    complexity_level: str  # "simple", "medium", "complex", "enterprise"
    model: str
    reason: str
    cost_per_month: float
    max_holdings: int


@dataclass
class ModeDefinition:
    """Complete definition of a deployment mode."""
    mode: DeploymentMode
    display_name: str
    description: str
    user_profile: str

    # Feature set
    enabled_features: Set[Feature] = field(default_factory=set)

    # Portfolio handling
    portfolio_handling: PortfolioHandlingConfig = None

    # Guardrails
    guardrail_level: GuardrailLevel = GuardrailLevel.EDUCATIONAL
    guardrail_rules: List[GuardrailRule] = field(default_factory=list)

    # LLM recommendations
    llm_recommendations: Dict[str, LLMRecommendation] = field(default_factory=dict)

    # Compliance
    requires_business_license: bool = False
    audit_trail_enabled: bool = False
    data_retention_days: int = 90


# ============================================================================
# MODE DEFINITIONS
# ============================================================================

SINGLE_INVESTOR_MODE = ModeDefinition(
    mode=DeploymentMode.SINGLE_INVESTOR,
    display_name="Single Investor",
    description="Personal portfolio management for individual investors",
    user_profile="Individual managing their own investment portfolio",

    enabled_features={
        Feature.HOLDINGS_SNAPSHOT,
        Feature.PERFORMANCE_ANALYSIS,
        Feature.NEWS_SENTIMENT,
        Feature.ANALYST_RATINGS,
        Feature.SESSION_CALIBRATION,
        Feature.REPORTS_EXPORT,
        Feature.BASIC_BOND_REPORTING,  # All modes can see bond holdings
        Feature.BOND_ANALYSIS,         # Single investors with bonds need YTM/duration
        Feature.REBALANCING_EDUCATIONAL,
        Feature.SECTOR_ANALYSIS_EDUCATIONAL,
    },

    portfolio_handling=PortfolioHandlingConfig(
        expand_etfs=False,  # Don't expand ETFs
        max_holdings_without_upgrade=300,  # Compact outputs: 300 holdings ≈ 6K tokens total
        context_estimation_multiplier=5,   # ~5 tokens per holding in compact mode (not 500)
    ),

    guardrail_level=GuardrailLevel.EDUCATIONAL,
    guardrail_rules=[
        GuardrailRule(
            name="no_directives",
            description="Avoid directive language (buy, sell, rebalance)",
            enforcement_level=GuardrailLevel.EDUCATIONAL,
            example_safe="Positions over 20% may indicate concentration risk. "
                        "An advisor might evaluate diversification for your goals.",
            example_unsafe="Reduce your MSFT position by 50%. Rebalance to 10% per sector."
        ),
        GuardrailRule(
            name="educational_framing",
            description="Frame all analysis as educational, not advice",
            enforcement_level=GuardrailLevel.EDUCATIONAL,
            example_safe="For educational purposes, if an investor moved to 60/40, "
                        "they might expect different volatility.",
            example_unsafe="You should move to a 60/40 portfolio to reduce risk."
        ),
        GuardrailRule(
            name="disclaimer_required",
            description="Always include financial advice disclaimer",
            enforcement_level=GuardrailLevel.EDUCATIONAL,
            example_safe="⚠️ This analysis is educational only. Consult a financial advisor.",
            example_unsafe="Based on my analysis, here's your optimal portfolio allocation..."
        ),
    ],

    llm_recommendations={
        # Breakpoints calibrated for compact output mode (Apr 2026):
        # holdings+perf+analyst+news+bonds ≈ 6K tokens total regardless of size.
        # Per-session token budget dominated by conversation history, not portfolio data.
        # Default: MiniMax-M2.7 hybrid (consultation enabled) for complex. Grok for enterprise (500+ holdings / 2M context).
        "simple": LLMRecommendation(
            complexity_level="simple",
            model="openai/gpt-4.1-nano",
            reason="GPT-4.1-nano (1M context, 30K TPM) handles simple portfolios with compact outputs",
            cost_per_month=10.0,
            max_holdings=50,
        ),
        "medium": LLMRecommendation(
            complexity_level="medium",
            model="openai/gpt-4.1-nano",
            reason="GPT-4.1-nano handles medium portfolios — compact outputs keep full session under 15K tokens",
            cost_per_month=15.0,
            max_holdings=150,
        ),
        "complex": LLMRecommendation(
            complexity_level="complex",
            model="together/MiniMaxAI/MiniMax-M2.7",
            reason="MiniMax-M2.7 hybrid (QC4=97) — best synthesis quality for standard portfolios with consultation enabled",
            cost_per_month=15.0,
            max_holdings=300,
        ),
        "enterprise": LLMRecommendation(
            complexity_level="enterprise",
            model="xai/grok-4-1-fast",
            reason="500+ holdings or extended multi-session history: Grok 4.1 Fast 2M context and 4M TPM",
            cost_per_month=20.0,
            max_holdings=500,
        ),
    },

    requires_business_license=False,
    audit_trail_enabled=False,
    data_retention_days=90,
)


FA_PROFESSIONAL_MODE = ModeDefinition(
    mode=DeploymentMode.FA_PROFESSIONAL,
    display_name="Financial Advisor — Dangerous Mode",
    description="Professional advisory portfolio management — elevated guardrails, fiduciary framing required",
    user_profile="Registered financial advisor or investment professional (licensed, fiduciary duty applies)",

    enabled_features={
        # All single investor features
        Feature.HOLDINGS_SNAPSHOT,
        Feature.PERFORMANCE_ANALYSIS,
        Feature.NEWS_SENTIMENT,
        Feature.ANALYST_RATINGS,
        Feature.SESSION_CALIBRATION,
        Feature.REPORTS_EXPORT,
        Feature.BASIC_BOND_REPORTING,  # All modes
        Feature.REBALANCING_EDUCATIONAL,
        Feature.SECTOR_ANALYSIS_EDUCATIONAL,
        # FA-specific features
        Feature.ETF_EXPANSION,
        Feature.ETF_CONSTITUENT_ANALYSIS,
        Feature.TAX_LOSS_HARVESTING,
        Feature.SECTOR_REBALANCING_TACTICAL,
        Feature.MODEL_PORTFOLIO_COMPARISON,
        Feature.COMPLIANCE_DOCUMENTATION,
        Feature.MULTI_PORTFOLIO_MANAGEMENT,
        Feature.AUDIT_TRAIL,
        Feature.BOND_ANALYSIS,
        Feature.FIXED_INCOME_ANALYSIS,
    },

    portfolio_handling=PortfolioHandlingConfig(
        expand_etfs=True,  # Expand ETFs to constituents
        max_holdings_without_upgrade=500,  # Compact outputs: 500 holdings still ≈ 8K tokens
        context_estimation_multiplier=5,   # ~5 tokens per holding in compact mode
    ),

    guardrail_level=GuardrailLevel.ADVISORY,
    guardrail_rules=[
        GuardrailRule(
            name="professional_recommendations",
            description="Specific recommendations acceptable with caveats",
            enforcement_level=GuardrailLevel.ADVISORY,
            example_safe="Consider rebalancing to align with client's stated 60/40 target. "
                        "Tax-loss harvesting opportunity: MSFT position down 15%.",
            example_unsafe="Buy Tesla, sell Microsoft. Client must follow this exactly."
        ),
        GuardrailRule(
            name="compliance_framing",
            description="All recommendations must cite compliance/suitability basis",
            enforcement_level=GuardrailLevel.ADVISORY,
            example_safe="Based on client's risk tolerance (moderate) and 20-year horizon, "
                        "recommend equity allocation of 70%.",
            example_unsafe="Recommend 70% equities."
        ),
        GuardrailRule(
            name="audit_trail_required",
            description="All analysis must be logged for audit",
            enforcement_level=GuardrailLevel.ADVISORY,
            example_safe="[AUDIT] Recommendation on 2026-04-06 for client XYZ: "
                        "Rebalance energy allocation from 8% to 5% [REASON] sector concentration risk",
            example_unsafe="Quick note to self about client's portfolio..."
        ),
        GuardrailRule(
            name="fiduciary_language",
            description="Recommendations must reference fiduciary duty",
            enforcement_level=GuardrailLevel.ADVISORY,
            example_safe="As your fiduciary, I recommend reviewing your concentrated AAPL position "
                        "for diversification benefits.",
            example_unsafe="Consider your AAPL position."
        ),
    ],

    llm_recommendations={
        # FA mode breakpoints (compact output, Apr 2026):
        # Advisory-level analysis quality is the constraint, not context size.
        # GPT-4.1-nano or GPT-4.1-mini handle up to 500 holdings within TPM budget.
        # Grok justified for multi-client sessions or portfolios requiring 2M context accumulation.
        "simple": LLMRecommendation(
            complexity_level="simple",
            model="openai/gpt-4.1-nano",
            reason="FA mode simple: GPT-4.1-nano handles advisory analysis with compact outputs",
            cost_per_month=15.0,
            max_holdings=200,
        ),
        "medium": LLMRecommendation(
            complexity_level="medium",
            model="openai/gpt-4.1-nano",
            reason="FA mode medium: compact outputs keep multi-client session within 30K TPM budget",
            cost_per_month=15.0,
            max_holdings=500,
        ),
        "complex": LLMRecommendation(
            complexity_level="complex",
            model="xai/grok-4-1-fast",
            reason="FA mode complex: Grok 4.1 Fast for multi-client portfolios with long session history",
            cost_per_month=20.0,
            max_holdings=1000,
        ),
        "enterprise": LLMRecommendation(
            complexity_level="enterprise",
            model="xai/grok-4-1-fast",
            reason="FA enterprise: Grok 4.1 Fast 2M context + 4M TPM for large multi-client workloads",
            cost_per_month=20.0,
            max_holdings=2000,
        ),
    },

    requires_business_license=True,
    audit_trail_enabled=True,
    data_retention_days=2555,  # 7 years (compliance requirement)
)


# ============================================================================
# MODE REGISTRY
# ============================================================================

MODE_REGISTRY: Dict[DeploymentMode, ModeDefinition] = {
    DeploymentMode.SINGLE_INVESTOR: SINGLE_INVESTOR_MODE,
    DeploymentMode.FA_PROFESSIONAL: FA_PROFESSIONAL_MODE,
}


def get_mode(mode: DeploymentMode) -> ModeDefinition:
    """Get mode definition by enum."""
    return MODE_REGISTRY.get(mode)


def get_mode_by_name(name: str) -> ModeDefinition:
    """Get mode definition by string name."""
    try:
        mode = DeploymentMode(name)
        return get_mode(mode)
    except ValueError:
        return None


def list_modes() -> List[ModeDefinition]:
    """List all available modes."""
    return list(MODE_REGISTRY.values())
