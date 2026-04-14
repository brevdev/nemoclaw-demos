#!/usr/bin/env python3
"""
Canonical data models for InvestorClaw output.

Defines standardized dataclasses for all analysis outputs:
- HoldingsReport
- PerformanceReport
- PortfolioAnalysisReport
- NewsReport
- AnalystReport
- AnalysisResult (unified wrapper)

These models normalize data flow across all scripts and eliminate scattered
JSON wrapping/unwrapping logic.
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import List, Dict, Any, Optional
from enum import Enum


# ============================================================================
# Enums
# ============================================================================

class FindingSeverity(str, Enum):
    """Severity levels for portfolio findings."""
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class FindingStatus(str, Enum):
    """Status levels for portfolio findings."""
    BELOW_BENCHMARK = "below_benchmark"
    WITHIN_BENCHMARK = "within_benchmark"
    ABOVE_BENCHMARK = "above_benchmark"
    MATERIALLY_ABOVE_BENCHMARK = "materially_above_benchmark"


# ============================================================================
# Holdings Report Models
# ============================================================================

@dataclass
class HoldingDetail:
    """Detail for a single holding."""
    symbol: str
    asset_type: str  # Equity, Bond, Cash, Margin
    shares: float
    current_price: float
    purchase_price: float
    purchase_date: Optional[str]  # ISO 8601 date
    sector: Optional[str] = None
    market_value: float = 0.0
    cost_basis: float = 0.0
    unrealized_gain_loss: float = 0.0
    unrealized_gain_loss_pct: float = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PortfolioSummary:
    """Summary of portfolio composition."""
    total_portfolio_value: float
    equity_value: float
    bond_value: float
    cash_value: float
    margin_value: float = 0.0
    net_worth: float = 0.0
    total_unrealized_gain_loss: float = 0.0
    total_unrealized_gain_loss_pct: float = 0.0
    equity_pct: float = 0.0
    bond_pct: float = 0.0
    cash_pct: float = 0.0

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class HoldingsReport:
    """Portfolio holdings snapshot."""
    timestamp: datetime
    holdings: Dict[str, HoldingDetail]  # symbol -> HoldingDetail
    summary: PortfolioSummary
    errors: Optional[List[str]] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "holdings": {k: v.to_dict() for k, v in self.holdings.items()},
            "summary": self.summary.to_dict(),
            "errors": self.errors,
            "metadata": self.metadata,
        }


# ============================================================================
# Performance Report Models
# ============================================================================

@dataclass
class ReturnMetrics:
    """Return metrics for portfolio."""
    ytd_return_pct: float
    one_year_return_pct: float
    three_year_return_pct: Optional[float] = None
    five_year_return_pct: Optional[float] = None
    inception_return_pct: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class RiskMetrics:
    """Risk metrics for portfolio."""
    volatility_annual_pct: float  # Standard deviation of returns
    sharpe_ratio: Optional[float] = None
    max_drawdown_pct: Optional[float] = None
    beta: Optional[float] = None
    var_95: Optional[float] = None  # Value at Risk at 95% confidence

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class PerformanceReport:
    """Performance analysis output."""
    timestamp: datetime
    returns: ReturnMetrics
    risk: RiskMetrics
    holdings_analyzed: int
    holding_details: List[HoldingDetail] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "returns": self.returns.to_dict(),
            "risk": self.risk.to_dict(),
            "holdings_analyzed": self.holdings_analyzed,
            "holding_details": [h.to_dict() for h in self.holding_details],
            "metadata": self.metadata,
        }


# ============================================================================
# Portfolio Analysis Report Models
# ============================================================================

@dataclass
class Finding:
    """A single finding from portfolio analysis."""
    finding_type: str  # e.g., "position_concentration", "sector_concentration"
    status: FindingStatus
    severity: FindingSeverity
    symbol: Optional[str] = None
    sector: Optional[str] = None
    measured_value: Optional[float] = None
    benchmark_value: Optional[float] = None
    observation: Optional[str] = None  # Fact: what was observed
    educational_consideration: Optional[str] = None  # Educational framing
    questions_for_review: List[str] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "finding_type": self.finding_type,
            "status": self.status.value,
            "severity": self.severity.value,
            "symbol": self.symbol,
            "sector": self.sector,
            "measured_value": self.measured_value,
            "benchmark_value": self.benchmark_value,
            "observation": self.observation,
            "educational_consideration": self.educational_consideration,
            "questions_for_review": self.questions_for_review,
            "metadata": self.metadata,
        }


@dataclass
class PortfolioAnalysisReport:
    """Portfolio analysis output (multi-factor analysis, opportunities, risks)."""
    timestamp: datetime
    portfolio_value: float
    findings: List[Finding] = field(default_factory=list)
    summary: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "portfolio_value": self.portfolio_value,
            "findings": [f.to_dict() for f in self.findings],
            "summary": self.summary,
            "metadata": self.metadata,
        }


# ============================================================================
# News Report Models
# ============================================================================

@dataclass
class NewsItem:
    """A single news article correlated to holdings."""
    symbol: str
    headline: str
    source: str
    published_date: str  # ISO 8601
    url: str
    sentiment: Optional[str] = None  # positive, negative, neutral
    summary: Optional[str] = None
    relevance_score: Optional[float] = None  # 0-1

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class NewsReport:
    """News correlated to portfolio holdings."""
    timestamp: datetime
    holdings_covered: int
    news_items: List[NewsItem] = field(default_factory=list)
    cache_status: Optional[str] = None  # fresh, cached, etc.
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "holdings_covered": self.holdings_covered,
            "news_items": [n.to_dict() for n in self.news_items],
            "cache_status": self.cache_status,
            "metadata": self.metadata,
        }


# ============================================================================
# Analyst Report Models
# ============================================================================

@dataclass
class AnalystRating:
    """Analyst rating for a security."""
    symbol: str
    target_price: Optional[float] = None
    rating: Optional[str] = None  # Buy, Hold, Sell, etc.
    number_of_analysts: Optional[int] = None
    consensus_rating: Optional[str] = None
    mean_target: Optional[float] = None
    high_target: Optional[float] = None
    low_target: Optional[float] = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class AnalystReport:
    """Analyst ratings and price targets for holdings."""
    timestamp: datetime
    holdings_covered: int
    ratings: List[AnalystRating] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "holdings_covered": self.holdings_covered,
            "ratings": [r.to_dict() for r in self.ratings],
            "metadata": self.metadata,
        }


# ============================================================================
# Unified Analysis Result Model
# ============================================================================

@dataclass
class AnalysisResult:
    """
    Unified wrapper for all InvestorClaw outputs.

    Every script returns this structure with appropriate sub-reports filled in.
    Ensures consistent disclaimer, metadata, and error handling.
    """
    analysis_type: str  # "Holdings", "Performance", "Portfolio Analysis", etc.
    timestamp: datetime
    data: Dict[str, Any]  # Flexible dict containing analysis-specific data
    is_investment_advice: bool = False
    disclaimer: str = "⚠️  EDUCATIONAL ANALYSIS - NOT INVESTMENT ADVICE"
    consult_professional: str = "Consult a qualified financial adviser before making any investment decisions"
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        """Serialize to dict for JSON output."""
        return {
            "analysis_type": self.analysis_type,
            "timestamp": self.timestamp.isoformat(),
            "data": self.data,
            "is_investment_advice": self.is_investment_advice,
            "disclaimer": self.disclaimer,
            "consult_professional": self.consult_professional,
            "metadata": self.metadata,
        }

    @staticmethod
    def from_holdings_report(report: HoldingsReport) -> "AnalysisResult":
        """Create AnalysisResult from HoldingsReport."""
        return AnalysisResult(
            analysis_type="Portfolio Holdings Snapshot",
            timestamp=report.timestamp,
            data=report.to_dict(),
            metadata={"source": "fetch_holdings.py"}
        )

    @staticmethod
    def from_performance_report(report: PerformanceReport) -> "AnalysisResult":
        """Create AnalysisResult from PerformanceReport."""
        return AnalysisResult(
            analysis_type="Performance Analysis",
            timestamp=report.timestamp,
            data=report.to_dict(),
            metadata={"source": "analyze_performance_polars.py"}
        )

    @staticmethod
    def from_portfolio_analysis_report(report: PortfolioAnalysisReport) -> "AnalysisResult":
        """Create AnalysisResult from PortfolioAnalysisReport."""
        return AnalysisResult(
            analysis_type="Portfolio Asset Allocation Analysis",
            timestamp=report.timestamp,
            data=report.to_dict(),
            metadata={"source": "portfolio_analyzer.py"}
        )

    @staticmethod
    def from_news_report(report: NewsReport) -> "AnalysisResult":
        """Create AnalysisResult from NewsReport."""
        return AnalysisResult(
            analysis_type="Portfolio News & Sentiment",
            timestamp=report.timestamp,
            data=report.to_dict(),
            metadata={"source": "fetch_portfolio_news.py"}
        )

    @staticmethod
    def from_analyst_report(report: AnalystReport) -> "AnalysisResult":
        """Create AnalysisResult from AnalystReport."""
        return AnalysisResult(
            analysis_type="Analyst Ratings & Targets",
            timestamp=report.timestamp,
            data=report.to_dict(),
            metadata={"source": "fetch_analyst_recommendations_parallel.py"}
        )
