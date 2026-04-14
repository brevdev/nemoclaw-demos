"""
Holding dataclass — Abstract holding interface for CDM compatibility.

This module provides the Holding dataclass that encapsulates all portfolio holding data.
It supports untyped dict interoperability while preserving compatibility with the current CDM-oriented data model
where only the from_dict/from_cdm factory methods change.

Design principle: All portfolio analysis code accesses holdings via property access
(holding.symbol, holding.value) not dict access (holding['symbol']), making the
underlying representation swappable without code changes.
"""

from dataclasses import dataclass, asdict, field, fields as dataclass_fields
from typing import Optional, Dict, Any
from datetime import date


@dataclass
class Holding:
    """
    Abstract financial holding (position) interface.

    Represents a single holding in a portfolio (equity, bond, cash, margin).
    All fields are optional to accommodate various asset types.

    Properties compute derived values (e.g., unrealized_gain from value - cost_basis).
    """

    # Core identification
    symbol: str  # Ticker (AAPL) or CUSIP (for bonds)
    asset_type: str  # 'equity', 'bond', 'municipal_bond', 'cash', 'margin', 'etf', 'mutual_fund'

    # Position sizing
    shares: float  # Quantity held (units for equities, par value for bonds)
    current_price: float  # Current market price per share
    purchase_price: float  # Historical purchase price per share

    # Value metrics
    purchase_date: str = "N/A"  # ISO date (YYYY-MM-DD) or 'N/A' (default for CDM compat)
    sector: str = "Unknown"  # Industry classification ('Technology', 'Healthcare', etc.)

    # Optional fields for equities
    security_type: Optional[str] = None  # 'equity', 'etf', 'mutual_fund'
    is_etf: bool = False
    account: Optional[str] = None
    account_type: Optional[str] = None
    data_provider: Optional[str] = None
    espp_status: Optional[str] = None      # 'vested', 'unvested', 'restricted', or None for non-ESPP
    managed_status: Optional[str] = None   # 'discretionary' for advisor-managed accounts, else None

    # Optional fields for bonds
    cusip: Optional[str] = None
    coupon_rate: Optional[float] = None
    maturity_date: Optional[str] = None  # YYYY-MM-DD
    ytm: Optional[float] = None  # Yield to Maturity
    ytc: Optional[float] = None  # Yield to Call
    duration: Optional[float] = None
    convexity: Optional[float] = None

    # Optional fields for bonds (detailed)
    tax_equivalent_yield: Optional[float] = None
    real_yield: Optional[float] = None  # TIPS
    modified_duration: Optional[float] = None
    macaulay_duration: Optional[float] = None
    dv01: Optional[float] = None  # Price change per 1bp

    # Optional fields for bonds (metadata)
    bond_name: Optional[str] = None
    bond_type: Optional[str] = None  # 'municipal', 'corporate', 'treasury'
    credit_quality: Optional[str] = None
    interest_rate_sensitivity: Optional[str] = None  # 'High', 'Moderate', 'Low'
    maturity_bucket: Optional[str] = None  # '0-2y', '2-5y', '5-10y', '10+y'

    # Optional fields for cash/margin
    interest_rate: Optional[float] = None
    interest_accrued: Optional[float] = None  # For margin debt

    # Legacy/optional fields
    name: Optional[str] = None  # Human-readable name (bond names, fund names)
    quantity: Optional[float] = None  # Alias for shares (bonds may use this)
    market_value: Optional[float] = None  # Explicit market value (computed if not provided)

    # Metadata
    metadata: Dict[str, Any] = field(default_factory=dict)

    # ==================== PROPERTIES ====================

    @property
    def value(self) -> float:
        """Current market value of the holding."""
        if self.market_value is not None:
            return self.market_value
        return self.shares * self.current_price

    # Bond asset types whose prices are quoted as % of par (e.g. 99.769 = $99.769 per $100 face)
    _BOND_ASSET_TYPES = frozenset(
        ('bond', 'municipal_bond', 'treasury', 'corporate_bond', 'government_bond')
    )

    @property
    def cost_basis(self) -> float:
        """Total cost to acquire this holding.

        For bonds, purchase_price is expressed as % of par (e.g. 99.769), so
        the dollar cost is shares × purchase_price / 100.  For all other asset
        types, purchase_price is already in dollars-per-unit.
        """
        if self.asset_type in self._BOND_ASSET_TYPES:
            return self.shares * self.purchase_price / 100.0
        return self.shares * self.purchase_price

    @property
    def unrealized_gain_loss(self) -> float:
        """Absolute unrealized gain or loss in currency."""
        return self.value - self.cost_basis

    @property
    def unrealized_gain_loss_pct(self) -> float:
        """Unrealized gain/loss as percentage (0.15 = 15% gain)."""
        if self.cost_basis == 0:
            return 0.0
        return self.unrealized_gain_loss / self.cost_basis

    @property
    def unrealized_pct(self) -> float:
        """Alias for unrealized_gain_loss_pct for backwards compatibility."""
        return self.unrealized_gain_loss_pct

    @property
    def position_return_pct(self) -> float:
        """Same as unrealized_pct but named more clearly."""
        return self.unrealized_gain_loss_pct

    # ==================== FACTORIES ====================

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Holding":
        """
        Factory: Create Holding from dict (legacy dict format).

        Handles dict-to-dataclass conversion with field name normalization.
        Unknown fields are stored in metadata.
        """
        if data is None:
            raise ValueError("Cannot create Holding from None")

        # Get all field names from dataclass
        known_fields = {f.name for f in dataclass_fields(cls)}

        # Separate known fields from extras
        init_kwargs = {}
        extras = {}

        for key, value in data.items():
            if key in known_fields:
                init_kwargs[key] = value
            else:
                extras[key] = value

        # Store extras in metadata
        if extras:
            init_kwargs['metadata'] = extras

        # Normalize common aliases
        if 'quantity' in init_kwargs and 'shares' not in init_kwargs:
            init_kwargs['shares'] = init_kwargs.pop('quantity')

        return cls(**init_kwargs)

    @classmethod
    def from_cdm(cls, cdm_position: Any) -> "Holding":
        """
        Factory: Create Holding from CDM Position object (CDM format).

        This method is reserved for CDM-backed position conversion when the CDM object is available.
        For now, it raises NotImplementedError.
        """
        raise NotImplementedError(
            "CDM integration available in the current release. "
            "Currently use from_dict() for portfolio data."
        )

    # ==================== SERIALIZATION ====================

    def to_dict(self) -> Dict[str, Any]:
        """
        Serialize Holding back to dict (for JSON output).

        Includes all non-None fields and metadata.
        """
        data = {}
        for f in dataclass_fields(self):
            value = getattr(self, f.name)
            # Skip None values and empty metadata
            if value is not None and value != {}:
                if f.name == 'metadata':
                    data.update(value)  # Flatten metadata back to top level
                else:
                    data[f.name] = value
        return data

    def to_dict_compact(self) -> Dict[str, Any]:
        """Compact dict representation (only essential fields for JSON output)."""
        return {
            'symbol': self.symbol,
            'asset_type': self.asset_type,
            'shares': self.shares,
            'current_price': self.current_price,
            'purchase_price': self.purchase_price,
            'purchase_date': self.purchase_date,
            'value': self.value,
            'cost_basis': self.cost_basis,
            'unrealized_gain_loss': self.unrealized_gain_loss,
            'unrealized_pct': self.unrealized_pct,
            'sector': self.sector,
        }

    # ==================== UTILITIES ====================

    def is_equity(self) -> bool:
        """True if holding is an equity (not bond/cash/margin)."""
        return self.asset_type.lower() in ('equity', 'etf', 'mutual_fund')

    def is_bond(self) -> bool:
        """True if holding is a bond."""
        return self.asset_type.lower() in ('bond', 'municipal_bond')

    def is_cash(self) -> bool:
        """True if holding is cash."""
        return self.asset_type.lower() == 'cash'

    def is_margin(self) -> bool:
        """True if holding is margin debt."""
        return self.asset_type.lower() == 'margin'

    def __repr__(self) -> str:
        """Human-readable representation."""
        return (
            f"Holding({self.symbol} {self.shares:.2f} @ ${self.current_price:.2f} "
            f"= ${self.value:,.2f} [{self.asset_type}])"
        )
