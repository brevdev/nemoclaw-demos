#!/usr/bin/env python3
"""
Portfolio Analyzer Module - Informational Portfolio Analysis
Provides educational asset allocation analysis for portfolio understanding.

⚠️  NOT FINANCIAL ADVICE: This module performs educational portfolio analysis
only. It does NOT constitute investment advice, is NOT a registered adviser,
and does NOT assess suitability. See README.md for complete disclaimers.
"""
import polars as pl
import yfinance as yf
import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass, asdict

from models.holdings import Holding
from rendering.disclaimer_wrapper import DisclaimerWrapper

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Phase 9: Mode and feature enforcement
try:
    from config.feature_manager import FeatureManager, FeatureNotAvailableError
    from config.config_loader import get_deployment_mode
    from config.deployment_modes import DeploymentMode, Feature
    from config.guardrail_enforcer import GuardrailEnforcer
    _features_available = True
except ImportError as e:
    logger.warning(f"Feature manager not available: {e}")
    _features_available = False

# Output validation hook — not yet implemented; call site is preserved for v1.x.
validate_all_guardrails = None

@dataclass
class RiskAlert:
    """Represents a risk alert with educational consideration (not a recommendation)"""
    severity: str  # 'critical', 'medium', 'info'
    category: str  # 'concentration', 'sector', 'allocation', 'diversification'
    message: str
    current_value: float
    target_value: float
    educational_consideration: str  # Educational framing (no directives)
    impact: str  # explanation of why this matters

@dataclass
class AllocationScenario:
    """Asset allocation scenario"""
    name: str
    description: str
    equities: float  # percentage
    bonds: float
    cash: float
    suitability: str  # who this is for

class FinancialEducation:
    """Financial terminology explanations in plain English"""

    TERMS = {
        "Concentration Risk": {
            "what": "When too much of your portfolio is in one stock or small group of stocks",
            "why": "If that company has problems, your entire portfolio suffers significantly",
            "threshold": "A prudent guideline: keeping any single stock under 5% of your portfolio value may reduce concentration risk",
            "example": "If your $2.5M portfolio has $150k in one stock (6%), this may indicate concentration above typical diversification guidelines. An investor might consider whether this aligns with their target allocation."
        },
        "Diversification": {
            "what": "Spreading your money across many different stocks, bonds, and sectors",
            "why": "When some investments do poorly, others do well - this smooths out your returns",
            "threshold": "A well-diversified portfolio has 40+ different holdings",
            "example": "Your 260+ holdings across multiple sectors means if Tech drops 20%, you still have Healthcare, Financials, Consumer Staples performing"
        },
        "Sector Concentration": {
            "what": "When too much of your stock portfolio is in one industry (like Technology)",
            "why": "Industry downturns affect all stocks in that sector, so you lose broadly",
            "threshold": "We recommend keeping any sector under 30% of your equity portfolio",
            "example": "If your equities are 65% Technology but only 5% Healthcare, you're too exposed to tech problems"
        },
        "Asset Allocation": {
            "what": "Your plan for dividing money between stocks (equities), bonds, and cash",
            "why": "This fundamental decision determines your risk level and return potential more than stock picking",
            "threshold": "Pre-retirement (45-60): Typically 70-80% equities, 15-25% bonds, 5% cash (varies by risk tolerance)",
            "example": "Example: $100,000 portfolio → $75,000 stocks, $20,000 bonds, $5,000 cash (diversified allocation)"
        },
        "Volatility": {
            "what": "How much your portfolio's value goes up and down in the short term",
            "why": "Higher volatility means bigger swings - you might need to stay invested through 20% drops",
            "threshold": "18-25% annual volatility is normal for 97%+ equity portfolios",
            "example": "18.2% volatility means in a typical year, 68% of the time your returns fall within +18% and -18% of average"
        },
        "Beta": {
            "what": "How your portfolio moves compared to the stock market overall",
            "why": "Beta of 1.0 means you move exactly with the market; >1.0 means you're more volatile",
            "threshold": "For a 97% equity portfolio, beta around 0.95-1.05 is expected",
            "example": "Beta of 1.05 means when the S&P 500 drops 10%, your portfolio typically drops about 10.5%"
        },
        "Sharpe Ratio": {
            "what": "How much return you get for each unit of risk you take",
            "why": "Higher is better - it means you're getting well-compensated for the volatility",
            "threshold": "A Sharpe Ratio above 1.0 is good, above 1.5 is excellent",
            "example": "Your 1.42 Sharpe Ratio means you're earning good returns relative to the risk you're taking"
        },
        "Value at Risk (VaR)": {
            "what": "The maximum amount you might lose in one bad year (95% confidence)",
            "why": "This tells you the downside scenario to plan for - what could actually happen",
            "threshold": "For a 97% equity portfolio, expect VaR of 15-25% of portfolio value",
            "example": "VaR of -$125k on $2.5M portfolio means worst 1 in 20 years you'd lose about $125k"
        },
        "Max Drawdown": {
            "what": "The biggest loss from peak to bottom during a market crisis",
            "why": "This shows you what happened in past crashes - helps prepare mentally",
            "threshold": "Historical: 2008 financial crisis was -57% for S&P 500; 2020 COVID crash was -34%",
            "example": "If your max drawdown is -35%, you experienced something like the 2020 COVID crash"
        },
        "Tax-Loss Harvesting": {
            "what": "A strategy of identifying positions with unrealized losses and evaluating whether to realize those losses for tax purposes, while potentially reinvesting to maintain exposure",
            "why": "Realized losses may provide tax benefits that could offset capital gains or income, subject to wash-sale rules and individual circumstances",
            "threshold": "Generally, up to $3k per year of losses can offset other income; excess carries forward; wash-sale rules apply",
            "example": "An investor might review a position with a $5k unrealized loss and evaluate whether realizing this loss aligns with their tax strategy while respecting wash-sale rules. A tax professional can help determine suitability for your situation."
        },
        "Dividend Yield": {
            "what": "Annual cash payments companies make to shareholders as a percentage of stock price",
            "why": "Provides regular income on top of stock price appreciation",
            "threshold": "2-4% dividend yield is healthy for blue-chip stocks",
            "example": "Procter & Gamble at $150/share paying $5.97/year dividend = 3.98% yield"
        }
    }

    @staticmethod
    def explain(term: str) -> Dict:
        """Return explanation for a financial term"""
        if term in FinancialEducation.TERMS:
            return FinancialEducation.TERMS[term]
        return {"error": f"Unknown term: {term}"}

class PortfolioAnalyzer:
    """Informational portfolio analyzer for educational analysis and metrics.

    ⚠️  IMPORTANT: This tool does NOT provide investment advice, is not a fiduciary
    adviser, and cannot assess suitability. It performs educational portfolio
    analysis only. See README.md for complete disclaimers and limitations.
    """

    # Recommended target allocation for 45-60 pre-retirement (balanced growth)
    # NOTE: This is a standard industry benchmark, NOT personalized to your situation.
    # Actual suitable allocation depends on your age, goals, risk tolerance, time horizon,
    # and existing assets in other accounts. Consult a financial adviser.
    RECOMMENDED_ALLOCATION = {
        "equities": 0.75,  # 75% equities (balanced growth with moderate protection)
        "bonds": 0.20,     # 20% bonds (diversification and stability)
        "cash": 0.05       # 5% cash (liquidity buffer)
    }

    # Risk thresholds (educational benchmarks, NOT personalized recommendations)
    # NOTE: These are industry benchmarks from academic research and FINRA guidance.
    # Whether they are suitable depends on your specific situation.
    THRESHOLDS = {
        "concentration_per_position": 0.05,  # 5% max per stock
                                              # Evidence: FINRA guidance, institutional policies
                                              # Rationale: Balances diversification with meaningful positions
        "sector_concentration": 0.30,  # 30% max per sector
                                      # Evidence: S&P 500 max sector weight (Tech ~30% as of 2025)
                                      # Rationale: Prevents single-sector downturns from dominating returns
        "min_holdings": 40,  # minimum for diversification
                            # Evidence: Statman (1987), Evans & Archer (1968)
                            # Rationale: Captures most diversification benefit; diminishing returns above 40
        "cash_range": (0.005, 0.15),  # 0.5% to 15% is acceptable
                                      # Evidence: Lifecycle fund benchmarks
                                      # Rationale: Provides liquidity while maintaining growth orientation
    }

    # Asset allocation scenarios
    SCENARIOS = [
        AllocationScenario(
            name="Conservative (60/30/10)",
            description="For investors near retirement or with low risk tolerance. Emphasizes stability.",
            equities=0.60,
            bonds=0.30,
            cash=0.10,
            suitability="Age 60+, low risk tolerance, near retirement"
        ),
        AllocationScenario(
            name="Balanced (70/20/10)",
            description="Moderate growth with meaningful downside protection. Good for mid-career investors.",
            equities=0.70,
            bonds=0.20,
            cash=0.10,
            suitability="Age 45-55, moderate risk tolerance, stable income"
        ),
        AllocationScenario(
            name="Aggressive Growth (90/8/2)",
            description="Growth-focused with minimal defensive positions. For healthy investors with high risk tolerance and 100+ diversified holdings.",
            equities=0.90,
            bonds=0.08,
            cash=0.02,
            suitability="Age 45-60, high risk tolerance, 100+ diversified holdings"
        ),
    ]

    def __init__(self):
        self.portfolio_df = None
        self.portfolio_stats = {}
        self.alerts = []
        self.education_needed = []


    def load_portfolio(self, holdings_json: str) -> None:
        """Load portfolio from holdings.json file (CDM-compatible current format)"""
        try:
            from pathlib import Path
            path = Path(holdings_json).expanduser()

            from config.schema import normalize_portfolio

            with open(path, 'r') as f:
                data = json.load(f)

            data = normalize_portfolio(data)

            # Support both schemas
            if 'holdings' in data:
                holdings = data.get('holdings', [])
            elif 'portfolio' in data:
                # Convert portfolio schema to holdings list
                holdings = []
                portfolio = data['portfolio']
                ASSET_CLASS_KEYS = {'equity', 'bond', 'cash', 'margin'}
                for asset_type, assets in portfolio.items():
                    if asset_type not in ASSET_CLASS_KEYS:
                        continue  # Skip non-asset-class keys (e.g., 'summary')
                    if isinstance(assets, dict):
                        for symbol, asset_data in assets.items():
                            entry = {'symbol': symbol, 'asset_type': asset_type}
                            if isinstance(asset_data, dict):
                                entry.update(asset_data)
                            holdings.append(entry)
            else:
                holdings = []

            # Convert dicts to Holding objects (CDM-compatible interface)
            # Then convert back to dicts for Polars DataFrame (which doesn't know about Holding)
            # This preserves data fidelity while enabling future CDM adoption
            if holdings:
                holding_objs = [Holding.from_dict(h) for h in holdings]
                # Convert back to dicts for Polars, using the Holding's computed properties
                holdings = [h.to_dict() for h in holding_objs]

            self.portfolio_df = pl.DataFrame(holdings)

            # Add 'value' column alias from 'market_value' for backward compatibility with analysis functions
            if 'market_value' in self.portfolio_df.columns and 'value' not in self.portfolio_df.columns:
                self.portfolio_df = self.portfolio_df.with_columns(pl.col('market_value').alias('value'))

            # Collapse ETF holdings in SINGLE_INVESTOR mode (group duplicate symbols by aggregating quantities)
            try:
                mode_str = get_deployment_mode()
                mode = DeploymentMode(mode_str)
                if mode == DeploymentMode.SINGLE_INVESTOR:
                    self._collapse_etf_holdings()
            except Exception as e:
                logger.debug(f"ETF collapsing not available: {e}")

            logger.info(f"Loaded {len(holdings)} holdings for analysis")

        except FileNotFoundError:
            logger.error(f"Holdings file not found: {holdings_json}")
            raise
        except Exception as e:
            logger.error(f"Error loading portfolio: {e}")
            raise

    def _collapse_etf_holdings(self) -> None:
        """Collapse duplicate holdings by symbol, preserving ESPP status.

        For SINGLE_INVESTOR mode, multiple purchases of the same security should be
        shown as a single aggregate holding with combined shares and value.

        IMPORTANT: Group by both symbol AND espp_status to keep ESPP holdings
        separate from regular holdings (different tax treatment, holding periods).

        Example:
        - MSFT: 39 shares (IRA, espp_status=None) + 451 shares (Brokerage, espp_status=None)
          → Collapses to 1 entry with 490 shares
        - MSFT ESPP: 100 shares (espp_status='vested')
          → Remains separate (different tax/holding rules)
        """
        if self.portfolio_df is None or len(self.portfolio_df) == 0:
            return

        try:
            # Group by symbol AND espp_status to preserve ESPP distinction
            group_cols = ['symbol']
            if 'espp_status' in self.portfolio_df.columns:
                group_cols.append('espp_status')

            # Aggregate numeric columns
            agg_dict = {}
            for col in self.portfolio_df.columns:
                if col in group_cols:
                    # Skip grouping columns
                    continue
                elif col in ['asset_type', 'sector', 'purchase_date', 'type', 'cost_basis_method']:
                    # Keep first value for string columns
                    agg_dict[col] = 'first'
                elif col in ['shares', 'market_value', 'value']:
                    # Sum quantities and values
                    agg_dict[col] = 'sum'
                else:
                    # current_price, other numeric: keep first/latest
                    agg_dict[col] = 'first'

            original_count = len(self.portfolio_df)
            # pl.col(col).agg(str) is not valid Polars API; use getattr to call
            # the named aggregation method (e.g. .first(), .sum()) directly.
            agg_exprs = [getattr(pl.col(col), agg)() for col, agg in agg_dict.items()]
            self.portfolio_df = self.portfolio_df.group_by(group_cols).agg(agg_exprs)
            collapsed_count = len(self.portfolio_df)

            if collapsed_count < original_count:
                logger.info(f"Holdings collapsed: {original_count} → {collapsed_count} (preserved ESPP status separation)")
        except Exception as e:
            logger.debug(f"Holdings collapsing failed (non-critical): {e}")
            # Continue without collapsing if there's an error

    def analyze_concentration(self) -> Tuple[List[RiskAlert], Dict]:
        """Analyze position concentration risks (excluding ESPP holdings)"""
        alerts = []
        concentration_report = {}

        if 'value' not in self.portfolio_df.columns:
            logger.warning("current_value column not found - skipping concentration analysis")
            return alerts, concentration_report

        # Phase 9: Exclude ESPP holdings from concentration analysis
        # ESPP shares are forced holdings and not a diversification choice
        try:
            from config.config_loader import get_espp_symbols
            espp_symbols = [s.upper() for s in get_espp_symbols()]
            is_espp = self.portfolio_df['symbol'].str.to_uppercase().is_in(espp_symbols)
            portfolio_for_analysis = self.portfolio_df.filter(~is_espp)
            espp_count = is_espp.sum()
            if espp_count > 0:
                logger.info(f"Excluding {espp_count} ESPP holding(s) from concentration analysis")
        except Exception:
            portfolio_for_analysis = self.portfolio_df
            espp_count = 0

        total_value = portfolio_for_analysis['value'].sum() if len(portfolio_for_analysis) > 0 else 1.0
        portfolio_for_analysis = portfolio_for_analysis.with_columns([
            (pl.col('value') / total_value).alias('portfolio_pct')
        ])

        # Check for over-concentrated positions (ESPP excluded)
        threshold = self.THRESHOLDS['concentration_per_position']
        concentrated = portfolio_for_analysis.filter(
            pl.col('portfolio_pct') > threshold
        ).sort('portfolio_pct', descending=True)

        if len(concentrated) > 0:
            for row in concentrated.to_dicts():
                alerts.append(RiskAlert(
                    severity="medium",
                    category="concentration",
                    message=f"{row['symbol']} is {row['portfolio_pct']*100:.1f}% of portfolio (diversification guideline: 5%)",
                    current_value=row['portfolio_pct'],
                    target_value=threshold,
                    educational_consideration=f"This position may indicate concentration above typical diversification guidelines. An investor might evaluate whether this aligns with their target allocation and risk tolerance. A financial adviser can help determine appropriate position sizing for your situation.",
                    impact="If this company faces problems, a concentration above diversification guidelines means more of your wealth is exposed to that single position's risks."
                ))

            self.education_needed.append("Concentration Risk")

        # Report top holdings (from full portfolio including ESPP)
        total_value_full = self.portfolio_df['value'].sum()
        full_portfolio_pct = self.portfolio_df.with_columns([
            (pl.col('value') / total_value_full).alias('portfolio_pct')
        ])
        top_10 = full_portfolio_pct.sort('value', descending=True).head(10)

        concentration_report = {
            "top_holdings": top_10.select(['symbol', 'shares', 'value', 'portfolio_pct']).to_dicts(),
            "holdings_over_5_pct": len(concentrated),
            "espp_holdings_excluded": espp_count > 0,
            "espp_holdings_note": f"Note: {espp_count} ESPP holding(s) excluded from concentration warnings as they represent forced employer compensation" if espp_count > 0 else None,
            "largest_holding_pct": top_10.head(1)['portfolio_pct'].item()
        }

        return alerts, concentration_report

    def analyze_sector_concentration(self) -> Tuple[List[RiskAlert], Dict]:
        """Analyze sector concentration risks"""
        alerts = []
        sector_report = {}

        if 'sector' not in self.portfolio_df.columns:
            logger.warning("sector column not found - cannot analyze sector concentration")
            return alerts, sector_report

        total_equity_value = self.portfolio_df.filter(
            pl.col('asset_type') == 'equity'
        )['value'].sum()

        if total_equity_value == 0:
            return alerts, sector_report

        # Group by sector
        sector_breakdown = self.portfolio_df.filter(
            pl.col('asset_type') == 'equity'
        ).group_by('sector').agg([
            pl.col('value').sum().alias('sector_value'),
            pl.col('symbol').count().alias('position_count')
        ]).with_columns([
            (pl.col('sector_value') / total_equity_value).alias('sector_pct')
        ]).sort('sector_value', descending=True)

        # Check for over-concentrated sectors
        threshold = self.THRESHOLDS['sector_concentration']
        over_concentrated = sector_breakdown.filter(pl.col('sector_pct') > threshold)

        if len(over_concentrated) > 0:
            for row in over_concentrated.to_dicts():
                alerts.append(RiskAlert(
                    severity="medium",
                    category="sector",
                    message=f"{row['sector']} is {row['sector_pct']*100:.1f}% of equities (diversification guideline: 30%)",
                    current_value=row['sector_pct'],
                    target_value=threshold,
                    educational_consideration=f"This sector concentration may indicate exposure above diversification guidelines. An investor might evaluate whether {row['sector']} concentration aligns with their investment goals, considering their age, risk tolerance, and time horizon. A financial adviser can help assess suitability for your situation.",
                    impact=f"If {row['sector']} experiences an industry downturn, {row['sector_pct']*100:.0f}% of your equity portfolio is affected. Diversification across sectors may reduce single-sector concentration risk."
                ))

            self.education_needed.append("Sector Concentration")

        sector_report = {
            "breakdown": sector_breakdown.to_dicts(),
            "over_concentrated_count": len(over_concentrated),
            "largest_sector_pct": sector_breakdown.head(1)['sector_pct'].item() if len(sector_breakdown) > 0 else 0
        }

        return alerts, sector_report

    def analyze_diversification(self) -> Tuple[List[RiskAlert], Dict]:
        """Analyze portfolio diversification"""
        alerts = []
        diversity_report = {}

        num_holdings = len(self.portfolio_df)
        min_holdings = self.THRESHOLDS['min_holdings']

        diversity_report = {
            "total_holdings": num_holdings,
            "minimum_recommended": min_holdings,
            "status": "Well-diversified" if num_holdings >= min_holdings else "Consider adding more positions"
        }

        if num_holdings < min_holdings:
            alerts.append(RiskAlert(
                severity="medium",
                category="diversification",
                message=f"Portfolio has {num_holdings} holdings (diversification guideline: 40+)",
                current_value=num_holdings,
                target_value=min_holdings,
                educational_consideration=f"This holding count may indicate below-guideline diversification. An investor might evaluate whether adding positions across underrepresented sectors aligns with their diversification strategy. A financial adviser can help assess diversification goals for your situation.",
                impact="Fewer holdings may indicate higher single-position concentration risk and potentially fewer diversification benefits"
            ))
            self.education_needed.append("Diversification")
        else:
            alerts.append(RiskAlert(
                severity="info",
                category="diversification",
                message=f"Portfolio has {num_holdings} holdings - strong diversification",
                current_value=num_holdings,
                target_value=min_holdings,
                educational_consideration="Your diversification across 260+ holdings demonstrates a professional-level approach to spreading investment risk across multiple positions.",
                impact="Broad diversification across many holdings may help reduce single-position risk and provide more stable portfolio outcomes"
            ))

        return alerts, diversity_report

    def analyze_asset_allocation(self) -> Tuple[List[RiskAlert], Dict]:
        """Analyze current asset allocation vs educational target allocation.

        FORMULA - ASSET ALLOCATION PERCENTAGE:
        ----------------------------------------
        Allocation % = Asset Class Value / Total Portfolio Value

        where:
        - Asset Class = Equities (stocks), Bonds, Cash/Money Market
        - Total Portfolio = Sum of all holdings across all asset classes

        EDUCATIONAL TARGET (NOT PERSONALIZED):
        ----------------------------------------
        Current target: 75% Equities / 20% Bonds / 5% Cash
        Based on: Balanced growth portfolio for pre-retirement phase
        Assumption: 45-60 age range, moderate risk tolerance, long time horizon

        SOURCES & REFERENCES:
        --------------------
        - Target allocation: Industry standard lifecycle funds (Vanguard, Fidelity, Schwab)
        - Rebalancing guidance: Financial Industry Regulatory Authority (FINRA)
        - Academic basis: Markowitz (1952) Modern Portfolio Theory
        - Lifecycle investing: Bodie et al. (2009) Investment textbook
        - Asset allocation impact: ~90% of return variation (Brinson et al., 1986)

        IMPORTANT DISCLAIMERS:
        --------------------
        - This target is NOT personalized to your situation
        - Your suitable allocation depends on: age, goals, risk tolerance, time horizon,
          existing assets in other accounts, income stability, health, family situation
        - This is educational only - consult a financial adviser for your situation
        - Regular rebalancing needed but consult on optimal frequency
        """
        alerts = []
        allocation_report = {}

        total_value = self.portfolio_df['value'].sum()

        # Calculate actual allocation
        equity_value = self.portfolio_df.filter(
            pl.col('asset_type') == 'equity'
        )['value'].sum()

        bond_value = self.portfolio_df.filter(
            pl.col('asset_type').str.to_lowercase().str.contains('bond')
        )['value'].sum()

        cash_value = self.portfolio_df.filter(
            pl.col('asset_type').is_in(['cash', 'margin'])
        )['value'].sum()

        actual = {
            "equities": equity_value / total_value if total_value > 0 else 0,
            "bonds": bond_value / total_value if total_value > 0 else 0,
            "cash": cash_value / total_value if total_value > 0 else 0
        }

        allocation_report = {
            "actual": {
                "equities": f"{actual['equities']*100:.1f}%",
                "bonds": f"{actual['bonds']*100:.1f}%",
                "cash": f"{actual['cash']*100:.1f}%"
            },
            "recommended_target": {
                "equities": f"{self.RECOMMENDED_ALLOCATION['equities']*100:.1f}%",
                "bonds": f"{self.RECOMMENDED_ALLOCATION['bonds']*100:.1f}%",
                "cash": f"{self.RECOMMENDED_ALLOCATION['cash']*100:.1f}%"
            },
            "alignment": "Excellent" if abs(actual['equities'] - self.RECOMMENDED_ALLOCATION['equities']) < 0.05 else "Good" if abs(actual['equities'] - self.RECOMMENDED_ALLOCATION['equities']) < 0.10 else "Rebalance needed"
        }

        # Check for drift from recommended allocation
        equity_drift = abs(actual['equities'] - self.RECOMMENDED_ALLOCATION['equities'])
        if equity_drift > 0.10:
            direction = "below" if actual['equities'] < self.RECOMMENDED_ALLOCATION['equities'] else "above"
            alternative = "increase equity exposure toward the 75% guideline" if actual['equities'] < self.RECOMMENDED_ALLOCATION['equities'] else "move away from equity concentration toward the 75% guideline"
            alerts.append(RiskAlert(
                severity="medium",
                category="allocation",
                message=f"Equity allocation is {direction} target: {actual['equities']*100:.1f}% vs benchmark {self.RECOMMENDED_ALLOCATION['equities']*100:.1f}%",
                current_value=actual['equities'],
                target_value=self.RECOMMENDED_ALLOCATION['equities'],
                educational_consideration=f"This allocation drift may indicate movement away from the 75% equity benchmark. An investor might evaluate whether their current allocation still aligns with their goals, risk tolerance, and time horizon. Market movements naturally cause allocation drift over time. A financial adviser can help assess whether rebalancing decisions are appropriate for your situation.",
                impact="Allocation drift away from your target can unintentionally change your portfolio's risk profile or expected return characteristics"
            ))
        else:
            alerts.append(RiskAlert(
                severity="info",
                category="allocation",
                message=f"Allocation is well-aligned with benchmark ({actual['equities']*100:.1f}% equities)",
                current_value=actual['equities'],
                target_value=self.RECOMMENDED_ALLOCATION['equities'],
                educational_consideration="Your allocation closely tracks the 75/20/5 benchmark for balanced growth. As markets move, periodic review of whether your allocation still matches your goals is a practice many investors follow.",
                impact="This allocation aligns with industry benchmarks for 45-60 pre-retirement growth with moderate risk management"
            ))

        self.education_needed.append("Asset Allocation")

        return alerts, allocation_report

    def get_allocation_recommendations(self) -> List[AllocationScenario]:
        """Return suitable allocation scenarios for the investor"""
        return self.SCENARIOS

    def generate_report(self, holdings_json: str, output_file: str = None) -> Dict:
        """Generate comprehensive financial analysis report with guardrails validation"""

        # Phase 9: Check feature availability
        if _features_available:
            try:
                mode_str = get_deployment_mode()
                mode = DeploymentMode(mode_str)
                fm = FeatureManager(mode)
                fm.require_feature(Feature.HOLDINGS_SNAPSHOT)  # Core feature, all modes
                logger.info(f"Portfolio analysis enabled for {mode_str} mode")
            except FeatureNotAvailableError as e:
                logger.error(f"Portfolio analysis not available: {e}")
                raise

        self.load_portfolio(holdings_json)

        # Run all analyses
        concentration_alerts, concentration_report = self.analyze_concentration()
        self.alerts.extend(concentration_alerts)

        sector_alerts, sector_report = self.analyze_sector_concentration()
        self.alerts.extend(sector_alerts)

        diversity_alerts, diversity_report = self.analyze_diversification()
        self.alerts.extend(diversity_alerts)

        allocation_alerts, allocation_report = self.analyze_asset_allocation()
        self.alerts.extend(allocation_alerts)

        # Build comprehensive report with mandatory disclaimer
        analysis_data = {
            "portfolio_summary": {
                "total_holdings": len(self.portfolio_df),
                "total_value": float(self.portfolio_df['value'].sum()),
                "asset_allocation": allocation_report
            },
            "analysis": {
                "concentration": concentration_report,
                "sectors": sector_report,
                "diversification": diversity_report,
                "allocation": allocation_report
            },
            "alerts": [asdict(alert) for alert in self.alerts],
            "recommendations": {
                "allocation_scenarios": [asdict(s) for s in self.SCENARIOS],
                "questions_for_advisor": self._get_questions_for_advisor(),
                "benchmark_context": self._get_benchmark_context()
            },
            "education": {
                "terms_explained": [FinancialEducation.explain(term) for term in self.education_needed],
                "key_concepts": {
                    "concentration_risk": FinancialEducation.explain("Concentration Risk"),
                    "diversification": FinancialEducation.explain("Diversification"),
                    "asset_allocation": FinancialEducation.explain("Asset Allocation")
                }
            },
            "bonds": self._get_basic_bond_report()  # Phase 9: Basic bond reporting (all modes)
        }

        # Phase 9: Apply guardrails based on deployment mode
        if _features_available:
            try:
                mode_str = get_deployment_mode()
                mode = DeploymentMode(mode_str)
                enforcer = GuardrailEnforcer(mode)

                # Apply appropriate disclaimer based on mode
                recommendations_text = json.dumps(analysis_data['recommendations'], indent=2)
                enforcer.add_professional_disclaimer(recommendations_text)
                logger.info(f"Applied {mode_str} guardrails and disclaimers")
            except Exception as e:
                logger.warning(f"Could not apply mode-specific guardrails: {e}")

        # Wrap with compliance disclaimers (mode-aware: FA Dangerous Mode gets expanded disclaimer)
        _mode_str = get_deployment_mode() if _features_available else None
        report = DisclaimerWrapper.wrap_output(analysis_data, "Portfolio Asset Allocation Analysis", compact=True, deployment_mode=_mode_str)

        # Validate output with guardrails if available
        if validate_all_guardrails:
            is_valid, violations = validate_all_guardrails(report)
            if not is_valid:
                logger.warning(f"Output guardrail violations detected: {violations}")
                report["guardrail_warnings"] = violations
            else:
                logger.info("Output passed all guardrail validations")

        # Save report if output file specified
        if output_file:
            DisclaimerWrapper.wrap_and_save(analysis_data, output_file, "Portfolio Asset Allocation Analysis", deployment_mode=_mode_str)
            logger.info(f"Report saved to {output_file}")

        return report

    def _get_questions_for_advisor(self) -> List[str]:
        """Get questions to discuss with a financial advisor based on portfolio analysis"""
        questions = []

        critical_alerts = [a for a in self.alerts if a.severity == 'critical']
        if critical_alerts:
            questions.append("Are there any concentration issues in my portfolio that I should discuss with a professional?")

        concentration_alerts = [a for a in self.alerts if a.category == 'concentration']
        if concentration_alerts:
            questions.append("Do any of my positions exceed the typical 5% diversification guideline, and if so, is this intentional for my strategy?")

        sector_alerts = [a for a in self.alerts if a.category == 'sector']
        if sector_alerts:
            questions.append("Are there sector concentrations that I should review to ensure they align with my risk tolerance?")

        if not questions:
            questions.append("My portfolio appears well-balanced relative to industry benchmarks. Should I continue with periodic reviews to maintain my target allocation?")

        return questions

    def _get_basic_bond_report(self) -> Dict:
        """Get basic bond reporting for all modes.

        Shows bond holdings snapshot + simple metrics, no professional analysis.
        Used for single investors with bonds in their portfolio.
        """
        bond_report = {"bonds_found": False, "bonds": []}

        if self.portfolio_df is None or len(self.portfolio_df) == 0:
            return bond_report

        # Look for bonds in portfolio (asset_type = 'bond' or symbol patterns)
        try:
            bonds = self.portfolio_df.filter(
                (pl.col('asset_type').str.contains('bond', case_insensitive=True)) |
                (pl.col('symbol').str.contains(r'^(TLT|SHV|AGG|BND|LQD|HYG)$', case_insensitive=True))
            )

            if len(bonds) == 0:
                return bond_report

            bond_report["bonds_found"] = True
            bond_data = []

            total_bond_value = bonds['value'].sum()
            portfolio_total = self.portfolio_df['value'].sum()
            bond_allocation_pct = (total_bond_value / portfolio_total * 100) if portfolio_total > 0 else 0

            for row in bonds.to_dicts():
                bond_data.append({
                    "symbol": row.get('symbol', 'N/A'),
                    "shares": row.get('shares', 0),
                    "value": row.get('value', 0),
                    "allocation_pct": (row.get('value', 0) / portfolio_total * 100) if portfolio_total > 0 else 0,
                    "asset_type": row.get('asset_type', 'bond'),
                    "note": "⚠️ Maturity/YTM not available. See Bond Analysis for detailed metrics." if len(bonds) > 0 else None
                })

            bond_report["bonds"] = bond_data
            bond_report["total_bond_value"] = float(total_bond_value)
            bond_report["bond_allocation_pct"] = float(bond_allocation_pct)
            bond_report["simple_alerts"] = [
                "For detailed bond analysis (duration, laddering, credit quality), see Bond Analysis feature (FA Professional mode)"
            ]

        except Exception as e:
            logger.warning(f"Error analyzing bonds: {e}")

        return bond_report

    def _get_benchmark_context(self) -> Dict:
        """Get benchmark context and educational considerations for portfolio management

        ⚠️  NOTE: Target allocation shown is a benchmark, not personalized to your
        situation. Your suitable allocation depends on your age, goals, risk tolerance,
        time horizon, and existing assets in other accounts. Consult a financial adviser.
        """
        return {
            "rebalancing_context": "Many investors review their allocation quarterly and evaluate rebalancing if drift exceeds 5%. Whether and when to rebalance depends on your goals and tax situation. A financial adviser can help determine appropriate timing for your situation.",
            "diversification_context": "An industry benchmark for diversification is 40+ holdings across 8+ sectors. Whether this target is appropriate for you depends on your specific situation and investment goals.",
            "tax_planning_context": "Tax-loss harvesting is a strategy some investors evaluate in taxable accounts to offset capital gains. IMPORTANT: Wash-sale rules prohibit repurchasing the same security (or 'substantially identical' security) within 30 days before or after the sale. Consult your tax professional before evaluating any harvesting strategy.",
            "contribution_context": "Regular contributions are a strategy many investors use to maintain allocation discipline over time and benefit from dollar-cost averaging.",
            "target_allocation_benchmark": {
                "equities": f"{self.RECOMMENDED_ALLOCATION['equities']*100:.0f}% (growth orientation)",
                "bonds": f"{self.RECOMMENDED_ALLOCATION['bonds']*100:.0f}% (stability and diversification)",
                "cash": f"{self.RECOMMENDED_ALLOCATION['cash']*100:.0f}% (liquidity reserve)"
            },
            "important_disclaimer": "This target allocation is a benchmark for pre-retirement investors age 45-60. Whether it is suitable for you depends on your complete situation. Any allocation changes should be made in consultation with a qualified financial adviser."
        }

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 portfolio_analyzer.py <holdings.json> [output.json]")
        print("\nExample:")
        print("  python3 portfolio_analyzer.py ~/portfolio_reports/holdings.json ~/portfolio_reports/analysis.json")
        sys.exit(1)

    holdings_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None
    verbose = True

    analyzer = PortfolioAnalyzer()
    report = analyzer.generate_report(holdings_file, output_file)

    _data = report.get('data', report)
    _alerts = _data['alerts']
    _critical = sum(1 for a in _alerts if a['severity'] == 'critical')
    _medium = sum(1 for a in _alerts if a['severity'] == 'medium')
    _questions = _data['recommendations']['questions_for_advisor']

    # Compact summary (default) — full data is in the JSON output file
    print(f"Portfolio: ${_data['portfolio_summary']['total_value']:,.2f} | "
          f"{_data['portfolio_summary']['total_holdings']} holdings | "
          f"{len(_alerts)} alerts ({_critical} critical, {_medium} medium) | "
          f"{len(_questions)} advisor questions")
    print(f"Report: {output_file or 'stdout'}")

    if verbose:
        print("\nALERTS & RECOMMENDATIONS (educational only — not financial advice)")
        for alert in _alerts:
            icon = "[CRITICAL]" if alert['severity'] == 'critical' else "[MEDIUM]" if alert['severity'] == 'medium' else "[INFO]"
            print(f"\n{icon} {alert['category'].upper()}")
            print(f"  {alert['message']}")
            print(f"  -> {alert['educational_consideration']}")
        print("\nQUESTIONS FOR YOUR FINANCIAL ADVISER")
        for question in _questions:
            print(f"  * {question}")

        # Cross-step context injection: load key figures from earlier pipeline steps
        # so the operational LLM has specific data to cite in its synthesis response.
        try:
            from config.path_resolver import get_reports_dir as _get_reports_dir
            _rdir = _get_reports_dir()

            # Top holdings from W1 — dated dir uses holdings_summary.json; root uses holdings.json
            _h_file = _rdir / "holdings_summary.json"
            if not _h_file.exists():
                _h_file = _rdir / "holdings.json"
            if _h_file.exists():
                _h = json.loads(_h_file.read_text())
                _top_eq = _h.get("top_equity", [])
                _sectors = _h.get("sector_weights", {})
                if _top_eq:
                    print("\nSESSION CONTEXT — top holdings (from W1):")
                    for p in _top_eq[:7]:
                        sym = p.get("symbol", "?")
                        val = p.get("value", 0)
                        wt = p.get("weight_pct", 0)
                        sec = p.get("sector", "")
                        gl = p.get("gl_pct", None)
                        gl_str = f" GL {gl:+.1f}%" if gl is not None else ""
                        print(f"  {sym}: ${val:,.0f} ({wt:.1f}%, {sec}){gl_str}")
                if _sectors:
                    top_sectors = sorted(_sectors.items(), key=lambda x: x[1], reverse=True)[:5]
                    print(f"  Sectors: {' | '.join(f'{s} {w:.0f}%' for s, w in top_sectors)}")

            # Top/bottom performers from W2 — compact summary is always at base reports dir root
            import os as _os
            _p_base = Path(_os.environ.get("INVESTOR_CLAW_REPORTS_DIR", str(Path.home() / "portfolio_reports"))).expanduser()
            _p_file = _p_base / "performance.json"
            if not _p_file.exists():
                _p_file = _rdir / "performance.json"
            if _p_file.exists():
                _p = json.loads(_p_file.read_text())
                _top_p = _p.get("top_performers", [])
                _bot_p = _p.get("bottom_performers", [])
                _ps = _p.get("portfolio_summary", {})
                if _top_p:
                    print("\nSESSION CONTEXT — performance (from W2):")
                    sharpe_wtd = _ps.get("weighted_sharpe", None)
                    if sharpe_wtd:
                        print(f"  Portfolio Sharpe (wtd): {sharpe_wtd:.2f}")
                    _top_str = ", ".join(f"{x['symbol']} {x['return_pct']:+.0f}%" for x in _top_p[:3])
                    _bot_str = ", ".join(f"{x['symbol']} {x['return_pct']:+.0f}%" for x in _bot_p[:3])
                    print(f"  Top performers: {_top_str}")
                    print(f"  Bottom performers: {_bot_str}")

            # Top analyst ratings from W4 (analyst_data.json — full 215-symbol dataset)
            _a_file = _rdir / "analyst_data.json"
            if _a_file.exists():
                _a = json.loads(_a_file.read_text())
                _recs = _a.get("recommendations", {})
                _buys = [
                    (sym, r) for sym, r in _recs.items()
                    if isinstance(r, dict)
                    and r.get("consensus", "").lower() in ("strong buy", "buy")
                    and r.get("target_price_mean") and r.get("current_price")
                ]
                _buys.sort(
                    key=lambda x: (x[1].get("target_price_mean", 0) - x[1].get("current_price", 0))
                                  / max(x[1].get("current_price", 1), 1),
                    reverse=True
                )
                if _buys:
                    print("\nSESSION CONTEXT — analyst consensus, top upside (from W4):")
                    print("  TICKER_FIDELITY: reproduce each symbol EXACTLY as shown — do not alter spelling.")
                    for sym, r in _buys[:5]:
                        rating = r.get("consensus", "?")
                        pt = r.get("target_price_mean", 0)
                        cp = r.get("current_price", 0)
                        upside = ((pt - cp) / cp * 100) if cp else 0
                        n = r.get("analyst_count", "?")
                        print(f'  {{"symbol":"{sym}","consensus":"{rating}","analysts":{n},"pt":{pt:.0f},"upside_pct":{upside:.0f}}}')
        except Exception:
            pass  # Cross-step context is best-effort; never block the main output

        print("\nSYNTHESIS GUIDANCE (for the presenting agent)")
        print("  Cite specific holdings, sector percentages, and dollar amounts in your response.")
        print("  Reference top performers and analyst consensus for named positions where relevant.")
        print("  Reproduce ALL ticker symbols EXACTLY as provided in SESSION CONTEXT — never alter spelling.")
        print("  Present all findings in educational framing. Target 150-250 words.")
