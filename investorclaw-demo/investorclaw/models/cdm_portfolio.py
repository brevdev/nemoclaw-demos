"""
InvestorClaw CDM-Compliant Portfolio Model

Simplified, industry-standard FINOS Common Domain Model (CDM) structures
for portfolio representation. Focused on holdings snapshot without enterprise
complexity (events, derivatives, settlement, collateral).

References:
- FINOS CDM: https://github.com/finos/common-domain-model
- event-position-type.rosetta: Portfolio, PortfolioState, Position, PriceQuantity
"""

from dataclasses import dataclass, field, asdict
from datetime import datetime
from typing import Optional, List, Any


@dataclass
class ProductIdentifier:
    """Identifies a security/product (ISIN, ticker, CUSIP, etc.)"""
    identifier_type: str  # "ISIN", "TICKER", "CUSIP", etc.
    identifier: str


@dataclass
class Quantity:
    """Represents a quantity of something (shares, units)"""
    amount: float
    unit: str = "shares"


@dataclass
class Price:
    """Represents a price (with currency)"""
    amount: float
    currency: str = "USD"


@dataclass
class PriceQuantity:
    """CDM core: combines quantity with price(s)

    In CDM, this represents the intersection of quantity and pricing.
    For a simple portfolio holding, we capture:
    - Quantity held
    - Current market price
    - Cost basis price (purchase price)
    """
    quantity: Quantity
    current_price: Price
    cost_basis_price: Price


@dataclass
class Asset:
    """Simplified asset representation (security details)"""
    product_identifier: ProductIdentifier
    security_type: str  # "Equity", "Bond", "Cash", etc.
    asset_class: str = ""  # "Stocks", "Bonds", "Cash"
    security_name: str = ""
    sector: Optional[str] = None
    cusip: Optional[str] = None
    isin: Optional[str] = None


@dataclass
class Product:
    """CDM Product - reference to what's being held

    For a simple portfolio, this is typically just an identifier
    pointing to the underlying security/asset.
    """
    product_identifier: ProductIdentifier


@dataclass
class Position:
    """CDM Position: atomic element of a portfolio

    "A Position describes how much of a given Product is being held"
    (from CDM spec)

    For InvestorClaw: one Position per security holding.
    """
    product: Product  # What's being held
    asset: Asset  # Details about the security
    price_quantity: PriceQuantity  # Quantity and prices
    market_value: float  # Current total value (quantity * current_price)
    cost_basis: float  # Total cost (quantity * cost_basis_price)
    unrealized_gain_loss: float  # market_value - cost_basis
    unrealized_gain_loss_pct: float  # (gain_loss / cost_basis) * 100

    def to_dict(self) -> dict:
        """Convert to CDM-compliant JSON structure"""
        return {
            "product": {
                "productIdentifier": {
                    "identifierType": self.product.product_identifier.identifier_type,
                    "identifier": self.product.product_identifier.identifier,
                }
            },
            "asset": {
                "productIdentifier": {
                    "identifierType": self.asset.product_identifier.identifier_type,
                    "identifier": self.asset.product_identifier.identifier,
                },
                "securityType": self.asset.security_type,
                "assetClass": self.asset.asset_class,
                "securityName": self.asset.security_name,
                "sector": self.asset.sector,
                "cusip": self.asset.cusip,
                "isin": self.asset.isin,
            },
            "priceQuantity": {
                "quantity": {
                    "amount": self.price_quantity.quantity.amount,
                    "unit": self.price_quantity.quantity.unit,
                },
                "currentPrice": {
                    "amount": self.price_quantity.current_price.amount,
                    "currency": self.price_quantity.current_price.currency,
                },
                "costBasisPrice": {
                    "amount": self.price_quantity.cost_basis_price.amount,
                    "currency": self.price_quantity.cost_basis_price.currency,
                },
            },
            "marketValue": self.market_value,
            "costBasis": self.cost_basis,
            "unrealizedGainLoss": self.unrealized_gain_loss,
            "unrealizedGainLossPct": self.unrealized_gain_loss_pct,
        }


@dataclass
class PortfolioSummary:
    """Summary statistics for the portfolio"""
    total_portfolio_value: float
    total_cost_basis: float
    total_unrealized_gain_loss: float
    total_unrealized_gain_loss_pct: float
    equity_value: float
    bond_value: float
    cash_value: float
    equity_pct: float
    bond_pct: float
    cash_pct: float

    def to_dict(self) -> dict:
        return {
            "totalPortfolioValue": self.total_portfolio_value,
            "totalCostBasis": self.total_cost_basis,
            "totalUnrealizedGainLoss": self.total_unrealized_gain_loss,
            "totalUnrealizedGainLossPct": self.total_unrealized_gain_loss_pct,
            "equityValue": self.equity_value,
            "bondValue": self.bond_value,
            "cashValue": self.cash_value,
            "equityPct": self.equity_pct,
            "bondPct": self.bond_pct,
            "cashPct": self.cash_pct,
        }


@dataclass
class AggregationParameters:
    """CDM AggregationParameters - how to aggregate positions into portfolio"""
    as_of_date: datetime  # Snapshot date/time


@dataclass
class PortfolioState:
    """CDM PortfolioState: all positions at a given time

    "State-full representation of a Portfolio that describes all the
    positions held at a given time"
    """
    positions: List[Position]  # List of holdings
    timestamp: datetime


@dataclass
class Portfolio:
    """CDM Portfolio: top-level aggregation

    "A Portfolio represents an aggregation of multiple Positions, by
    describing the parameters that this Portfolio should be aggregated
    based on. The resulting PortfolioState is calculated using these
    aggregation parameters as inputs."
    """
    aggregation_parameters: AggregationParameters
    portfolio_state: PortfolioState
    summary: PortfolioSummary

    def to_dict(self) -> dict:
        """Convert to CDM-compliant JSON"""
        return {
            "aggregationParameters": {
                "asOfDate": self.aggregation_parameters.as_of_date.isoformat(),
            },
            "portfolioState": {
                "timestamp": self.portfolio_state.timestamp.isoformat(),
                "positions": [pos.to_dict() for pos in self.portfolio_state.positions],
            },
            "summary": self.summary.to_dict(),
        }


@dataclass
class AnalysisMetadata:
    """Metadata wrapper for compliance and sourcing"""
    analysis_type: str  # "Portfolio Holdings Snapshot"
    is_investment_advice: bool = False
    disclaimer: str = "⚠️ EDUCATIONAL ANALYSIS - NOT INVESTMENT ADVICE"
    consult_professional: str = (
        "This analysis is educational only. Consult a qualified financial "
        "professional before making investment decisions."
    )


@dataclass
class CDMPortfolioResult:
    """Complete CDM-compliant portfolio response

    Wraps the CDM Portfolio with InvestorClaw metadata and compliance notices.
    """
    portfolio: Portfolio
    metadata: AnalysisMetadata
    source: str = "investorclaw"
    version: str = "1.0.0-cdm"

    def to_dict(self) -> dict:
        """Convert entire result to JSON"""
        return {
            "cdmVersion": "5.x",  # FINOS CDM version reference
            "portfolio": self.portfolio.to_dict(),
            "metadata": {
                "analysisType": self.metadata.analysis_type,
                "isInvestmentAdvice": self.metadata.is_investment_advice,
                "disclaimer": self.metadata.disclaimer,
                "consultProfessional": self.metadata.consult_professional,
                "source": self.source,
                "version": self.version,
            },
        }
