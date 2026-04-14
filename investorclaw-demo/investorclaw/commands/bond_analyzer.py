#!/usr/bin/env python3
"""
Generic bond analysis module supporting municipal bonds, treasuries, and corporate bonds.
Works from CSV or holdings.json format with automatic data source detection.
"""
import json
import os
import sys
import logging
from pathlib import Path
from dataclasses import dataclass, asdict
from typing import Dict, List, Optional, Tuple, Any
from datetime import datetime, timedelta
import re
import polars as pl
import requests
from scipy.optimize import brentq

from models.holdings import Holding
from rendering.disclaimer_wrapper import DisclaimerWrapper

# Phase 9: Mode and feature enforcement
try:
    from config.feature_manager import FeatureManager, FeatureNotAvailableError
    from config.config_loader import get_deployment_mode
    from config.deployment_modes import DeploymentMode, Feature
    from config.guardrail_enforcer import GuardrailEnforcer
    _features_available = True
except ImportError as e:
    _features_available = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


@dataclass
class BondMetrics:
    """Metrics for a single bond."""
    symbol: str
    cusip: Optional[str]
    asset_type: str  # municipal_bond, treasury, corporate_bond

    # Pricing
    par_value: float
    coupon_rate: float  # Annual coupon as %
    market_value: float
    price_percent: float  # Price as % of par

    # Maturity
    maturity_date: str  # YYYY-MM-DD format
    years_to_maturity: float

    # Yields
    ytm: float  # Yield to Maturity %
    ytc: Optional[float] = None  # Yield to Call % (if callable)
    tax_equivalent_yield: Optional[float] = None  # For municipal bonds
    real_yield: Optional[float] = None  # For TIPS

    # Duration & Risk
    macaulay_duration: float = 0.0
    modified_duration: float = 0.0
    convexity: float = 0.0
    dv01: float = 0.0  # Price change per 1bp rate increase

    # Credit & Quality
    credit_quality_estimate: str = "Unknown"
    interest_rate_sensitivity: str = "Moderate"  # High/Moderate/Low
    maturity_bucket: str = "Unknown"  # 0-2y / 2-5y / 5-10y / 10+y

    # Benchmark comparison
    benchmark_yield: Optional[float] = None
    yield_vs_benchmark: Optional[float] = None  # ytm - benchmark_yield


@dataclass
class PortfolioMetrics:
    """Portfolio-level bond metrics."""
    total_value: float
    bond_count: int

    # Breakdown
    asset_type_breakdown: Dict[str, Dict[str, Any]]  # {type: {count, value, pct}}

    # Aggregated metrics
    weighted_avg_ytm: float
    weighted_avg_duration: float
    weighted_avg_coupon: float

    # Maturity ladder
    maturity_ladder: Dict[str, Dict[str, Any]]  # {bucket: {count, value, pct}}

    # Risk assessment
    duration_risk: str  # High/Moderate/Low
    average_credit_quality: str

    # Tax benefits (munis)
    total_annual_muni_tax_savings: float = 0.0  # At 37% bracket
    tax_savings_by_bracket: Optional[Dict[str, float]] = None

    # Recommendations
    recommendations: List[str] = None


class BondAnalyzer:
    """Comprehensive bond analysis for multiple bond types."""

    # FRED API endpoints for treasury yields
    TREASURY_ENDPOINTS = {
        '3mo': 'DGS3MO',
        '6mo': 'DGS6MO',
        '1y': 'DGS1',
        '2y': 'DGS2',
        '5y': 'DGS5',
        '7y': 'DGS7',
        '10y': 'DGS10',
        '20y': 'DGS20',
        '30y': 'DGS30',
    }

    TIPS_ENDPOINTS = {
        '5y': 'DFII5',
        '7y': 'DFII7',
        '10y': 'DFII10',
        '20y': 'DFII20',
        '30y': 'DFII30',
    }

    # Credit rating scale (lower number = better quality)
    CREDIT_RATINGS = {
        'AAA': 1, 'AA+': 2, 'AA': 3, 'AA-': 4,
        'A+': 5, 'A': 6, 'A-': 7,
        'BBB+': 8, 'BBB': 9, 'BBB-': 10,
        'BB+': 11, 'BB': 12, 'BB-': 13,
        'B+': 14, 'B': 15, 'B-': 16,
        'CCC': 17, 'CC': 18, 'C': 19, 'D': 20,
    }

    def __init__(self):
        self.bonds: List[BondMetrics] = []
        self.errors: List[str] = []
        self.treasury_yields: Dict[str, float] = {}
        self.tips_yields: Dict[str, float] = {}
        self._load_treasury_yields()
        self._load_tips_yields()

    # Seed values (approximate, used as fallback when FRED unavailable).
    # Updated: April 2026. These go stale — configure FRED_API_KEY for live data.
    _TREASURY_SEED: Dict[str, float] = {
        '3mo': 4.33, '6mo': 4.22, '1y': 4.08,
        '2y': 3.88, '5y': 3.92, '7y': 4.08,
        '10y': 4.21, '20y': 4.55, '30y': 4.62,
    }
    _TIPS_SEED: Dict[str, float] = {
        '5y': 1.85, '7y': 1.89, '10y': 1.92,
        '20y': 2.08, '30y': 2.15,
    }

    def _fred_fetch_series(self, series_id: str, api_key: str) -> Optional[float]:
        """Fetch the most recent non-null daily observation for a FRED series.

        Returns the yield as a float (percent) or None on failure.
        """
        try:
            # Request last 10 observations so we skip weekends/holidays with "."
            url = "https://api.stlouisfed.org/fred/series/observations"
            params = {
                "series_id": series_id,
                "api_key": api_key,
                "file_type": "json",
                "limit": 10,
                "sort_order": "desc",
                "observation_start": (datetime.now() - timedelta(days=30)).strftime("%Y-%m-%d"),
            }
            resp = requests.get(url, params=params, timeout=8)
            resp.raise_for_status()
            observations = resp.json().get("observations", [])
            for obs in observations:
                value = obs.get("value", ".")
                if value != "." and value is not None:
                    return float(value)
        except Exception as e:
            logger.debug(f"FRED fetch failed for {series_id}: {e}")
        return None

    def _load_treasury_yields(self):
        """Load current Treasury yield curve from FRED API with seed-data fallback.

        Reads FRED_API_KEY from environment. Falls back to hardcoded seed values
        (approximate, dated April 2026) when the key is absent or the API is unreachable.
        Series used: DGS3MO, DGS6MO, DGS1, DGS2, DGS5, DGS7, DGS10, DGS20, DGS30.
        """
        api_key = os.environ.get("FRED_API_KEY", "").strip()
        if not api_key:
            logger.info("FRED_API_KEY not set — using seed Treasury yields (configure key for live data)")
            self.treasury_yields = dict(self._TREASURY_SEED)
            return

        fetched: Dict[str, float] = {}
        for tenor, series_id in self.TREASURY_ENDPOINTS.items():
            value = self._fred_fetch_series(series_id, api_key)
            if value is not None:
                fetched[tenor] = value

        if fetched:
            self.treasury_yields = fetched
            logger.info(f"Loaded {len(fetched)}/{len(self.TREASURY_ENDPOINTS)} Treasury yields from FRED")
        else:
            logger.warning("FRED returned no Treasury data — using seed yields")
            self.treasury_yields = dict(self._TREASURY_SEED)

    def _load_tips_yields(self):
        """Load current TIPS real yield curve from FRED API with seed-data fallback.

        Reads FRED_API_KEY from environment. Falls back to hardcoded seed values
        (approximate, dated April 2026) when the key is absent or the API is unreachable.
        Series used: DFII5, DFII7, DFII10, DFII20, DFII30.
        """
        api_key = os.environ.get("FRED_API_KEY", "").strip()
        if not api_key:
            logger.info("FRED_API_KEY not set — using seed TIPS yields")
            self.tips_yields = dict(self._TIPS_SEED)
            return

        fetched: Dict[str, float] = {}
        for tenor, series_id in self.TIPS_ENDPOINTS.items():
            value = self._fred_fetch_series(series_id, api_key)
            if value is not None:
                fetched[tenor] = value

        if fetched:
            self.tips_yields = fetched
            logger.info(f"Loaded {len(fetched)}/{len(self.TIPS_ENDPOINTS)} TIPS yields from FRED")
        else:
            logger.warning("FRED returned no TIPS data — using seed yields")
            self.tips_yields = dict(self._TIPS_SEED)

    def load_bonds_from_csv(self, csv_path: Path) -> List[Dict]:
        """Load bonds from CSV with automatic column detection (CDM-compatible current format)."""
        try:
            df = pl.read_csv(csv_path, truncate_ragged_lines=True)
            holdings = df.to_dicts()

            bonds = []
            for holding in holdings:
                # Auto-detect if this is a bond
                if self._is_bond(holding):
                    # Validate via Holding interface (v2.2.1+ CDM-compatible)
                    try:
                        _ = Holding.from_dict(holding)
                    except Exception as e:
                        logger.warning(f"Bond {holding.get('cusip', 'unknown')} failed Holding validation: {e}")
                    bonds.append(holding)

            logger.info(f"Loaded {len(bonds)} bonds from {csv_path.name}")
            return bonds
        except Exception as e:
            logger.error(f"Error loading CSV {csv_path}: {e}")
            self.errors.append(f"CSV load error: {e}")
            return []

    def load_bonds_from_holdings_json(self, json_path: Path) -> List[Dict]:
        """Load bonds from holdings.json format (backwards compatible, CDM-compatible current format)."""
        try:
            from config.schema import normalize_portfolio

            with open(json_path, 'r') as f:
                data = json.load(f)

            data = normalize_portfolio(data)

            holdings = []

            # Current holdings.json format: data.portfolio.fixed_income dict keyed by CUSIP
            if isinstance(data, dict) and 'portfolio' in data:
                fi = data['portfolio'].get('fixed_income', {})
                for cusip, bond_data in fi.items():
                    entry = {'symbol': cusip, 'cusip': cusip, 'asset_type': 'bond'}
                    entry.update(bond_data)
                    holdings.append(entry)
                # Also check legacy 'bond' key (canonical schema after CDM normalization)
                for cusip, bond_data in data['portfolio'].get('bond', {}).items():
                    entry = {'symbol': cusip, 'cusip': cusip, 'asset_type': 'bond'}
                    entry.update(bond_data)
                    holdings.append(entry)
            # Flat holdings list format
            elif isinstance(data, dict) and 'holdings' in data:
                holdings = data['holdings']
            elif isinstance(data, list):
                holdings = data

            bonds = [h for h in holdings if 'bond' in h.get('asset_type', '').lower()]

            # Enrich bonds missing maturity/coupon from security_name (CDM broker format)
            for bond in bonds:
                sec_name = bond.get("security_name", "")
                if sec_name:
                    parsed = self._parse_security_name(sec_name)
                    if parsed.get("maturity_date") and not bond.get("maturity_date"):
                        bond["maturity_date"] = parsed["maturity_date"]
                    if parsed.get("coupon_rate") is not None and not bond.get("coupon_rate"):
                        bond["coupon_rate"] = parsed["coupon_rate"]
                    if parsed.get("asset_type") and bond.get("asset_type") in ("bond", "fixed_income", None, ""):
                        bond["asset_type"] = parsed["asset_type"]

            # Validate via Holding interface (v2.2.1+ CDM-compatible)
            for bond in bonds:
                try:
                    _ = Holding.from_dict(bond)
                except Exception as e:
                    logger.warning(f"Bond {bond.get('cusip', 'unknown')} failed Holding validation: {e}")

            logger.info(f"Loaded {len(bonds)} bonds from {json_path.name}")
            return bonds
        except Exception as e:
            logger.error(f"Error loading holdings.json {json_path}: {e}")
            self.errors.append(f"Holdings load error: {e}")
            return []

    @staticmethod
    def _parse_security_name(name: str) -> Dict:
        """Extract coupon, maturity, and asset type from broker security-name strings.

        Handles formats such as:
          'U S TREASURY BILL MATURES 04/30/26 (912797SN8)'
          'AIKEN CO SC CONS SCH SOUTH SR A BE/R/ RATE 05.000% MATURES 04/01/33'
          'ATLANTA GA WTR &WASTEWTR RV BE/R/ RATE 05.000% MATURES 11/01/28'

        Returns a dict with keys (present only when parsed):
          maturity_date (str MM/DD/YY or MM/DD/YYYY, caller converts to YYYY-MM-DD)
          coupon_rate   (float, annual percent)
          asset_type    (str: treasury | municipal_bond | corporate_bond)
        """
        extracted: Dict = {}
        if not name:
            return extracted

        name_upper = name.upper()

        # Coupon: "RATE 05.000%" or "RATE 5%"
        coupon_match = re.search(r'\bRATE\s+(\d+\.?\d*)\s*%', name_upper)
        if coupon_match:
            try:
                extracted["coupon_rate"] = float(coupon_match.group(1))
            except ValueError:
                pass

        # Maturity: "MATURES MM/DD/YY" or "MATURES MM/DD/YYYY"
        mat_match = re.search(r'\bMATURES?\s+(\d{1,2}/\d{1,2}/\d{2,4})', name_upper)
        if mat_match:
            extracted["maturity_date"] = mat_match.group(1)

        # Asset type heuristic from name
        if re.search(r'\bTREASURY\b|\bT[\s-]BILL\b|\bT[\s-]BOND\b|\bT[\s-]NOTE\b|\bTREASURIES\b', name_upper):
            extracted["asset_type"] = "treasury"
        elif re.search(r'\bTIPS\b|\bINFLATION[\s-]PROTECTED\b', name_upper):
            extracted["asset_type"] = "treasury"
        else:
            # Default to muni for bonds without a clear corporate/treasury marker
            extracted["asset_type"] = "municipal_bond"

        return extracted

    def _is_bond(self, holding: Dict) -> bool:
        """Check if a holding is a bond based on asset_type or data characteristics."""
        asset_type = holding.get('asset_type', '').lower()
        if 'bond' in asset_type or 'treasury' in asset_type or 'muni' in asset_type:
            return True

        # Heuristic: if has maturity_date and coupon_rate with non-empty values, likely a bond
        maturity = holding.get('maturity_date', '').strip() if isinstance(holding.get('maturity_date'), str) else holding.get('maturity_date')
        coupon = holding.get('coupon_rate', '')
        if maturity and coupon:
            return True

        # Broker-format heuristic: null/empty symbol + valid 9-char alphanumeric CUSIP
        # (UBS, Schwab, and similar broker CSVs omit ticker symbols for fixed-income positions)
        symbol = str(holding.get('symbol', '') or '').strip()
        cusip = str(holding.get('cusip', '') or '').strip()
        if (not symbol or symbol.lower() in ('none', 'n/a', 'nan', '')) and \
                len(cusip) == 9 and re.match(r'^[A-Za-z0-9]{9}$', cusip):
            return True

        return False

    def _detect_asset_type(self, holding: Dict) -> str:
        """Detect bond asset type from data."""
        asset_type = holding.get('asset_type', '').lower()

        if 'municipal' in asset_type or 'muni' in asset_type:
            return 'municipal_bond'
        elif 'treasury' in asset_type or 'govt' in asset_type:
            return 'treasury'
        elif 'tips' in asset_type:
            return 'treasury'  # TIPS are treasuries
        elif 'corporate' in asset_type or 'corp' in asset_type:
            return 'corporate_bond'
        else:
            # Default to municipal if unknown
            return 'municipal_bond'

    def _parse_maturity_date(self, date_str: str) -> Optional[str]:
        """Parse maturity date in any format and return YYYY-MM-DD."""
        if not date_str or date_str.upper() in ['UNKNOWN', 'N/A', 'NONE']:
            return None

        # Try common formats
        formats = [
            '%Y-%m-%d',    # YYYY-MM-DD
            '%m/%d/%Y',    # MM/DD/YYYY
            '%m/%d/%y',    # MM/DD/YY
            '%d/%m/%Y',    # DD/MM/YYYY
            '%d/%m/%y',    # DD/MM/YY
            '%m-%d-%Y',    # MM-DD-YYYY
            '%Y/%m/%d',    # YYYY/MM/DD
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                # Handle YY format (assume 20XX for 00-50, 19XX for 51-99)
                if dt.year < 100:
                    dt = dt.replace(year=2000 + dt.year if dt.year <= 50 else 1900 + dt.year)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue

        logger.warning(f"Could not parse maturity date: {date_str}")
        return None

    def _calculate_ytm(self, current_price: float, coupon_rate: float, face_value: float,
                       years_to_maturity: float, frequency: int = 2) -> float:
        """
        Calculate Yield-to-Maturity (YTM): effective annual return if held to maturity.

        FORMULA:
        --------
        Bond Price = Σ(C / (1+y)^t) + P / (1+y)^n

        where:
        - C = periodic coupon payment
        - y = YTM (solved iteratively, not analytically)
        - t = time period (1 to n)
        - P = face value (par)
        - n = number of periods to maturity

        In plain English: "What is the annualized return if I hold this bond to maturity?"

        SOLVING METHOD:
        ----------------
        Uses scipy.optimize.brentq (Brent's method):
        - Combines bisection, secant method, and parabolic interpolation
        - Guaranteed convergence for continuous functions
        - Search range: -50% to 100% (handles negative yields and extreme cases)

        INTERPRETATION:
        ----------------
        - YTM > Coupon Rate: Bond trading at DISCOUNT (below par)
        - YTM = Coupon Rate: Bond trading AT PAR
        - YTM < Coupon Rate: Bond trading at PREMIUM (above par)
        - YTM can be NEGATIVE: Premium bonds with prices >> face value

        NEGATIVE YIELD EXAMPLE:
        -----------------------
        US Treasury 2-year at price $102, coupon 2%:
        YTM ≈ -0.5% (buyer pays premium, loses money on price if held to maturity)
        This is mathematically correct and common in low-rate environments.

        REFERENCES:
        -----------
        - Source: Bond pricing theory, widely used since 1960s
        - Standard practice: Bloomberg, FactSet, Morningstar, all bond platforms
        - Brent's method: Original paper by Brent (1973)
        - YTM limitations: Assumes reinvestment of coupons at YTM rate (unrealistic)

        IMPORTANT NOTE:
        ----------------
        Negative yields are mathematically valid for premium bonds. They are NOT clipped
        to zero (that would be incorrect). Negative yields indicate the bond is expensive
        relative to its income generation.

        Args:
            current_price: Current market price of the bond (as percentage or dollar amount)
            coupon_rate: Annual coupon rate (as percentage, e.g., 2.5 for 2.5%)
            face_value: Par value / face value of the bond (typically 1000 or 100)
            years_to_maturity: Time until maturity in years (can be fractional)
            frequency: Coupon payment frequency (2 = semi-annual, 1 = annual)

        Returns:
            YTM as annual percentage (can be negative for premium bonds, zero if invalid input)
        """
        if years_to_maturity <= 0 or current_price <= 0:
            return 0.0

        # Zero-coupon fast path: brentq fails when coupon_rate=0 because
        # int(years * frequency) can round to 0 for very short maturities.
        if coupon_rate == 0:
            try:
                ytm_decimal = (face_value / current_price) ** (1.0 / years_to_maturity) - 1.0
                return round(ytm_decimal * 100, 6)
            except (ZeroDivisionError, ValueError, OverflowError):
                logger.warning("Zero-coupon YTM formula failed (degenerate inputs).")
                return None

        try:
            # Bond pricing function: Price = sum(coupon/(1+y)^t) + par/(1+y)^n
            # Solve for y (YTM)

            def bond_price(ytm: float) -> float:
                price = 0.0
                annual_coupon = face_value * (coupon_rate / 100)
                periods = int(years_to_maturity * frequency)
                period_rate = ytm / frequency / 100

                for t in range(1, periods + 1):
                    price += annual_coupon / frequency / ((1 + period_rate) ** t)

                price += face_value / ((1 + period_rate) ** periods)
                return price - current_price

            # Use brentq for guaranteed convergence
            ytm = brentq(bond_price, -50, 100)  # Search between -50% and 100%
            return ytm  # Return exact YTM (can be negative for premium bonds)
        except Exception as e:
            # Log error but don't silently return approximation
            logger.warning(f"YTM calculation failed: {e}. Bond may have unusual structure.")
            # Return None to signal failure instead of approximation
            return None

    def _calculate_duration(self, coupon_rate: float, ytm: float, years_to_maturity: float,
                           face_value: float = 100, frequency: int = 2) -> Tuple[float, float]:
        """Calculate Macaulay and Modified Duration: bond's effective maturity and interest rate sensitivity.

        FORMULA - MACAULAY DURATION:
        ----------------------------
        MacD = Σ(t × PV(CF_t)) / Σ(PV(CF_t))

        where:
        - t = time to each cash flow (in years)
        - CF_t = cash flow at time t (coupon + principal)
        - PV(CF_t) = present value of cash flow (discounted at YTM)

        In plain English: "Weighted average time to receive the bond's cash flows"

        FORMULA - MODIFIED DURATION:
        ----------------------------
        ModD = MacD / (1 + y/m)

        where:
        - y = YTM (annual percentage)
        - m = compounding frequency (2 for semi-annual)

        In plain English: "Price sensitivity to 1% change in yield"

        INTERPRETATION:
        ----------------
        - Duration = 5 years: 1% yield increase → ~5% price decrease (negative relationship)
        - Longer duration = higher interest rate risk
        - Zero coupon bonds: Duration ≈ years to maturity
        - High coupon bonds: Duration < years to maturity (faster cash flow collection)

        PRACTICAL USE:
        ----------------
        Modified Duration = DV01 / Bond Price × 10,000
        Price Change ≈ -Modified Duration × Yield Change (in percent)

        Example: Bond with ModD = 5
        If yields rise from 3% to 4% (+1%):
        Price change ≈ -5 × 1% = -5%

        REFERENCES:
        -----------
        - Macaulay Duration: Frederick Macaulay (1938) - original framework
        - Modified Duration: Developed to measure price elasticity to yield changes
        - Standard practice: Bloomberg, FactSet, all bond analytics platforms
        - Duration assumes: Parallel yield curve shift, no credit event, reinvestment at YTM

        Returns:
            Tuple of (macaulay_duration_years, modified_duration_years)
        """
        if years_to_maturity <= 0 or ytm < -50:
            return 0.0, 0.0

        try:
            annual_coupon = face_value * (coupon_rate / 100)
            period_coupon = annual_coupon / frequency
            periods = int(years_to_maturity * frequency)
            period_rate = ytm / frequency / 100

            # Calculate present value of cash flows
            pv_weighted_time = 0.0
            pv_total = 0.0

            for t in range(1, periods + 1):
                time_years = t / frequency
                cf = period_coupon if t < periods else period_coupon + face_value
                pv = cf / ((1 + period_rate) ** t)
                pv_total += pv
                pv_weighted_time += time_years * pv

            # Macaulay duration in years
            macaulay_duration = pv_weighted_time / pv_total if pv_total > 0 else 0.0

            # Modified duration
            modified_duration = macaulay_duration / (1 + period_rate) if pv_total > 0 else 0.0

            return macaulay_duration, modified_duration
        except Exception as e:
            logger.warning(f"Could not calculate duration: {e}")
            return 0.0, 0.0

    def _calculate_convexity(self, coupon_rate: float, ytm: float, years_to_maturity: float,
                            face_value: float = 100, frequency: int = 2) -> float:
        """Calculate bond convexity: second-order price sensitivity to yield changes.

        FORMULA:
        --------
        Convexity = Σ(t(t+1) × PV(CF_t)) / (Price × (1+y)^2)

        where:
        - t = time periods to cash flow
        - CF_t = cash flow at time t
        - PV(CF_t) = present value of cash flow
        - y = YTM

        In plain English: "How does the bond's price response change when yields move?"

        RELATIONSHIP WITH DURATION:
        ---------------------------
        Duration measures 1st-order (linear) price sensitivity.
        Convexity measures 2nd-order (curved) price sensitivity.

        More accurate price change formula:
        ΔPrice ≈ -Duration × ΔY + 0.5 × Convexity × (ΔY)^2

        where ΔY = change in yield

        EXAMPLE:
        --------
        Bond with Duration=5, Convexity=75
        If yields rise 2% (from 3% to 5%):

        Linear estimate (duration only):
        ΔPrice ≈ -5 × 2% = -10%

        Accurate estimate (duration + convexity):
        ΔPrice ≈ -5 × 2% + 0.5 × 75 × (2%)^2 = -10% + 1.5% = -8.5%

        Convexity benefit: The price doesn't fall as much (due to curvature).

        INTERPRETATION:
        ----------------
        - All straight bonds have positive convexity
        - Higher convexity = more benefit from price appreciation, less damage from price decline
        - Callable bonds may have negative convexity (cap on upside)
        - Zero coupon bonds have high convexity

        REFERENCES:
        -----------
        - Convexity in bond analysis: Introduced in 1980s for improved pricing models
        - Standard practice: Bloomberg, FactSet, Morningstar
        - Source: Fixed Income Mathematics (Fabozzi, 4th ed., 2006)
        - Related: DV01 = Dollar Value of 1 basis point (simpler alternative)

        Note: Convexity assumes option-free bonds and parallel yield curve shifts.
              Callable bonds require specialized models.

        Returns:
            Convexity value in units of years^2 (typically 50-150 for straight bonds)
        """
        if years_to_maturity <= 0:
            return 0.0

        try:
            annual_coupon = face_value * (coupon_rate / 100)
            period_coupon = annual_coupon / frequency
            periods = int(years_to_maturity * frequency)
            period_rate = ytm / frequency / 100

            pv_weighted_convexity = 0.0
            pv_total = 0.0

            for t in range(1, periods + 1):
                cf = period_coupon if t < periods else period_coupon + face_value
                pv = cf / ((1 + period_rate) ** t)
                pv_total += pv
                pv_weighted_convexity += t * (t + 1) * pv

            # Convexity (in years^2)
            convexity = (pv_weighted_convexity / (pv_total * (1 + period_rate) ** 2)) / (frequency ** 2)
            return convexity
        except Exception as e:
            logger.warning(f"Could not calculate convexity: {e}")
            return 0.0

    def _calculate_tax_equivalent_yield(self, ytm: float, tax_bracket: float = 0.37) -> float:
        """Calculate tax-equivalent yield for municipal bonds."""
        if ytm <= 0:
            return 0.0
        return ytm / (1 - tax_bracket)

    def _estimate_credit_quality(self, ytm: float, coupon_rate: float) -> str:
        """Estimate credit quality based on yield spread vs coupon."""
        # Degenerate case: both zero means maturity was unparseable and YTM
        # computation produced 0 — cannot infer quality from a zero spread.
        if ytm == 0.0 and coupon_rate == 0.0:
            return "Unrated"

        spread = ytm - coupon_rate

        if spread < 1.0:
            return "AAA/AA"
        elif spread < 2.0:
            return "A"
        elif spread < 3.5:
            return "BBB"
        elif spread < 5.0:
            return "BB"
        else:
            return "B or Lower"

    def _get_maturity_bucket(self, years: float) -> str:
        """Classify bond by maturity bucket."""
        if years <= 2:
            return "0-2y"
        elif years <= 5:
            return "2-5y"
        elif years <= 10:
            return "5-10y"
        else:
            return "10+y"

    def analyze_bond(self, holding: Dict) -> Optional[BondMetrics]:
        """Analyze a single bond and return BondMetrics."""
        try:
            symbol = holding.get('symbol', 'UNKNOWN')
            cusip = holding.get('cusip')
            asset_type = self._detect_asset_type(holding)

            # Parse maturity date
            maturity_str = holding.get('maturity_date')
            maturity_date = self._parse_maturity_date(maturity_str) if maturity_str else None

            # Calculate years to maturity
            years_to_maturity = 0.0
            if maturity_date:
                try:
                    mat_dt = datetime.strptime(maturity_date, '%Y-%m-%d')
                    years_to_maturity = (mat_dt - datetime.now()).days / 365.25
                    if years_to_maturity < 0:
                        years_to_maturity = 0.0
                except ValueError as e:
                    logger.warning(f"Could not parse maturity date '{maturity_date}': {e}. "
                                   "Duration/YTM will be 0 and credit quality will show Unrated.")
                    years_to_maturity = 0.0
            else:
                logger.warning(f"Bond {symbol or cusip}: maturity date unknown — "
                               "duration/YTM excluded from weighted averages.")

            # Get prices and values (with comprehensive null-safe handling)
            # Helper function for safe float conversion
            def safe_float(val, default=0.0):
                if val is None or val == '' or val == 'nan' or val == 'NaN':
                    return default
                try:
                    return float(val)
                except (TypeError, ValueError):
                    return default

            par_value = safe_float(holding.get('par_value'), 100)
            coupon_rate = safe_float(holding.get('coupon_rate'), 0.0)
            market_value = safe_float(holding.get('market_value'), safe_float(holding.get('value'), 0.0))
            price_percent = safe_float(holding.get('price_percent'), (market_value / par_value * 100) if par_value else 100)
            current_price = price_percent  # As % of par

            # Calculate YTM
            ytm = self._calculate_ytm(current_price, coupon_rate, 100, years_to_maturity)

            # If YTM calculation failed, use placeholder and log warning
            if ytm is None:
                logger.warning(f"YTM calculation failed for {symbol}. Duration/convexity will not be calculated.")
                ytm = coupon_rate  # Use coupon as fallback estimate
                macaulay_dur, modified_dur = 0.0, 0.0
                convexity = 0.0
                dv01 = 0.0
            else:
                # Calculate duration and convexity only if YTM succeeded
                macaulay_dur, modified_dur = self._calculate_duration(coupon_rate, ytm, years_to_maturity)
                convexity = self._calculate_convexity(coupon_rate, ytm, years_to_maturity)
                # Calculate DV01 (dollar value of 1 basis point)
                dv01 = modified_dur * market_value * 0.0001

            # Tax-equivalent yield for munis
            tax_eq_yield = None
            if asset_type == 'municipal_bond' and ytm is not None:
                tax_eq_yield = self._calculate_tax_equivalent_yield(ytm)

            # Estimate credit quality
            credit_quality = self._estimate_credit_quality(ytm if ytm is not None else coupon_rate, coupon_rate)

            # Determine interest rate sensitivity
            if modified_dur > 7:
                sensitivity = "High"
            elif modified_dur > 4:
                sensitivity = "Moderate"
            else:
                sensitivity = "Low"

            # Maturity bucket
            bucket = self._get_maturity_bucket(years_to_maturity)

            return BondMetrics(
                symbol=symbol,
                cusip=cusip,
                asset_type=asset_type,
                par_value=par_value,
                coupon_rate=coupon_rate,
                market_value=market_value,
                price_percent=price_percent,
                maturity_date=maturity_date or "Unknown",
                years_to_maturity=years_to_maturity,
                ytm=ytm,
                tax_equivalent_yield=tax_eq_yield,
                macaulay_duration=macaulay_dur,
                modified_duration=modified_dur,
                convexity=convexity,
                dv01=dv01,
                credit_quality_estimate=credit_quality,
                interest_rate_sensitivity=sensitivity,
                maturity_bucket=bucket,
            )
        except Exception as e:
            logger.error(f"Error analyzing bond {holding.get('symbol', 'UNKNOWN')}: {e}")
            self.errors.append(f"Bond analysis error: {e}")
            return None

    def analyze_portfolio(self, bonds: List[Dict]) -> Optional[PortfolioMetrics]:
        """Analyze portfolio of bonds and return aggregated metrics."""
        if not bonds:
            return None

        self.bonds = []
        total_value = 0.0
        ytm_weighted = 0.0
        duration_weighted = 0.0
        coupon_weighted = 0.0

        asset_breakdown = {}
        maturity_breakdown = {}
        credit_qualities = []
        muni_tax_savings = 0.0
        unknown_maturity_count = 0

        for holding in bonds:
            metrics = self.analyze_bond(holding)
            if metrics:
                self.bonds.append(metrics)
                total_value += metrics.market_value

                # Weighted metrics — exclude bonds with unknown maturity from
                # YTM/duration averages (years_to_maturity==0 makes both degenerate)
                if metrics.years_to_maturity > 0:
                    ytm_weighted += metrics.ytm * metrics.market_value
                    duration_weighted += metrics.modified_duration * metrics.market_value
                else:
                    unknown_maturity_count += 1
                coupon_weighted += metrics.coupon_rate * metrics.market_value

                # Asset type breakdown
                asset_type = metrics.asset_type
                if asset_type not in asset_breakdown:
                    asset_breakdown[asset_type] = {'count': 0, 'value': 0.0}
                asset_breakdown[asset_type]['count'] += 1
                asset_breakdown[asset_type]['value'] += metrics.market_value

                # Maturity ladder
                bucket = metrics.maturity_bucket
                if bucket not in maturity_breakdown:
                    maturity_breakdown[bucket] = {'count': 0, 'value': 0.0}
                maturity_breakdown[bucket]['count'] += 1
                maturity_breakdown[bucket]['value'] += metrics.market_value

                # Credit quality
                quality_score = self.CREDIT_RATINGS.get(metrics.credit_quality_estimate.split('/')[0], 10)
                credit_qualities.append(quality_score)

                # Muni tax savings (at 37% bracket)
                if metrics.asset_type == 'municipal_bond' and metrics.tax_equivalent_yield:
                    annual_income = metrics.market_value * (metrics.ytm / 100)
                    annual_tax_savings = annual_income * 0.37  # 37% bracket
                    muni_tax_savings += annual_tax_savings

        if total_value == 0:
            return None

        # Warn if a significant fraction of bonds have unknown maturity
        unknown_pct = unknown_maturity_count / len(bonds) * 100 if bonds else 0
        if unknown_pct > 20:
            logger.warning(
                f"{unknown_maturity_count}/{len(bonds)} bonds ({unknown_pct:.0f}%) have unknown maturity — "
                "YTM/duration averages exclude these bonds. Run '/portfolio holdings' to refresh data."
            )

        # Calculate percentages
        for asset_type in asset_breakdown:
            asset_breakdown[asset_type]['pct'] = (asset_breakdown[asset_type]['value'] / total_value) * 100

        for bucket in maturity_breakdown:
            maturity_breakdown[bucket]['pct'] = (maturity_breakdown[bucket]['value'] / total_value) * 100

        # Weighted averages
        avg_ytm = ytm_weighted / total_value if total_value > 0 else 0.0
        avg_duration = duration_weighted / total_value if total_value > 0 else 0.0
        avg_coupon = coupon_weighted / total_value if total_value > 0 else 0.0

        # Average credit quality
        avg_quality_score = sum(credit_qualities) / len(credit_qualities) if credit_qualities else 10
        quality_map = {v: k for k, v in self.CREDIT_RATINGS.items()}
        avg_credit = quality_map.get(int(round(avg_quality_score)), 'BBB')

        # Duration risk
        if avg_duration > 7:
            duration_risk = "High"
        elif avg_duration > 4:
            duration_risk = "Moderate"
        else:
            duration_risk = "Low"

        # Generate recommendations
        recommendations = self._generate_recommendations(
            len(self.bonds), total_value, avg_duration, avg_ytm, asset_breakdown
        )

        return PortfolioMetrics(
            total_value=total_value,
            bond_count=len(self.bonds),
            asset_type_breakdown=asset_breakdown,
            weighted_avg_ytm=avg_ytm,
            weighted_avg_duration=avg_duration,
            weighted_avg_coupon=avg_coupon,
            maturity_ladder=maturity_breakdown,
            duration_risk=duration_risk,
            average_credit_quality=avg_credit,
            total_annual_muni_tax_savings=muni_tax_savings,
            recommendations=recommendations,
        )

    def _generate_recommendations(self, bond_count: int, total_value: float, duration: float,
                                 ytm: float, asset_breakdown: Dict) -> List[str]:
        """Generate plain-English recommendations based on portfolio."""
        recs = []

        if duration > 7:
            recs.append("High interest rate sensitivity: Consider shortening duration if rates are expected to rise.")

        if bond_count < 5:
            recs.append(f"Limited diversification: Portfolio contains only {bond_count} bonds. Consider increasing.")

        # Check for concentration
        for asset_type, data in asset_breakdown.items():
            if data['pct'] > 70:
                recs.append(f"High concentration in {asset_type}: {data['pct']:.1f}% of portfolio. Consider diversifying.")

        if ytm < 2:
            recs.append("Low portfolio yield: Consider duration extension or credit quality upgrade for higher income.")
        elif ytm > 6:
            recs.append("High portfolio yield: Verify credit quality is appropriate for your risk tolerance.")

        return recs if recs else ["Portfolio is well-diversified and positioned appropriately."]

    def export_report(self, metrics: PortfolioMetrics, output_path: Path) -> None:
        """Export analysis report to JSON."""
        try:
            analysis_data = {
                'portfolio_summary': asdict(metrics),
                'individual_bonds': [asdict(bond) for bond in self.bonds],
                'errors': self.errors if self.errors else None,
            }

            # Wrap with compliance disclaimers (mode-aware: FA Dangerous Mode gets expanded disclaimer)
            try:
                from config.config_loader import get_deployment_mode as _get_mode
                _dep_mode = _get_mode()
            except Exception:
                _dep_mode = None
            DisclaimerWrapper.wrap_and_save(analysis_data, str(output_path), "Bond Portfolio Analysis", deployment_mode=_dep_mode)

            logger.info(f"Report exported to {output_path}")
        except Exception as e:
            logger.error(f"Error exporting report: {e}")
            self.errors.append(f"Export error: {e}")


def _backfill_holdings_summary(bond_output_file: Path, bonds: list) -> None:
    """Enrich holdings_summary.json top_bonds with ytm and duration.

    holdings_summary.json is written by fetch_holdings.py *before* bond analysis
    runs, so it cannot include YTM or duration at write time.  This function
    finds holdings_summary.json in the same directory as bond_output_file and
    adds ytm/duration to each top_bonds entry that has a matching CUSIP.
    """
    summary_file = bond_output_file.parent / "holdings_summary.json"
    if not summary_file.exists():
        return

    # Build CUSIP → analytics lookup from analyzed bonds
    analytics: dict = {}
    for b in bonds:
        cusip = getattr(b, "cusip", None)
        if not cusip:
            continue
        ytm_val      = getattr(b, "ytm", None)
        dur_val      = getattr(b, "macaulay_duration", None)
        mod_dur_val  = getattr(b, "modified_duration", None)
        analytics[cusip] = {
            "ytm":               round(ytm_val, 4)      if ytm_val      is not None else None,
            "duration":          round(dur_val, 2)       if dur_val      is not None else None,
            "modified_duration": round(mod_dur_val, 2)  if mod_dur_val  is not None else None,
        }

    try:
        with open(summary_file) as fh:
            hs = json.load(fh)

        top_bonds = hs.get("top_bonds", [])
        changed = False
        for entry in top_bonds:
            a = analytics.get(entry.get("cusip", ""))
            if not a:
                continue
            for field in ("ytm", "duration", "modified_duration"):
                if a.get(field) is not None and entry.get(field) is None:
                    entry[field] = a[field]
                    changed = True

        if changed:
            with open(summary_file, "w") as fh:
                json.dump(hs, fh, indent=2, default=str)
            logger.info(f"Backfilled ytm/duration into {summary_file}")
    except Exception as exc:
        logger.warning(f"Could not enrich holdings_summary.json: {exc}")


def main():
    """Main entry point for bond analyzer."""

    # Phase 9: Check feature availability (FA mode only)
    if _features_available:
        try:
            mode_str = get_deployment_mode()
            mode = DeploymentMode(mode_str)
            fm = FeatureManager(mode)
            fm.require_feature(Feature.BOND_ANALYSIS)  # FA-only feature
            logger.info(f"Bond analysis enabled for {mode_str} mode")
        except FeatureNotAvailableError as e:
            logger.error(f"Bond analysis not available: {e}")
            print(f"❌ Bond analysis requires FA Professional mode: {e}")
            sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage: python3 bond_analyzer.py <csv_or_json_file> [output.json]")
        print("\nSupports:")
        print("  - CSV files with bond data")
        print("  - holdings.json format")
        print("\nExample:")
        print("  python3 bond_analyzer.py /path/to/portfolios/Holdings_extracted.csv /path/to/reports/bond_analysis.json")
        sys.exit(1)

    input_file = Path(sys.argv[1])
    if not input_file.exists():
        print(f"Error: {input_file} not found")
        sys.exit(1)

    output_file = Path(sys.argv[2]) if len(sys.argv) > 2 else input_file.parent / f"{input_file.stem}_bond_analysis.json"

    analyzer = BondAnalyzer()

    # Load bonds based on file type
    if input_file.suffix.lower() == '.json':
        bonds = analyzer.load_bonds_from_holdings_json(input_file)
    else:
        bonds = analyzer.load_bonds_from_csv(input_file)

    if not bonds:
        print("No bonds found in input file")
        sys.exit(1)

    # Analyze portfolio
    metrics = analyzer.analyze_portfolio(bonds)
    if not metrics:
        print("Error analyzing portfolio")
        sys.exit(1)

    # Phase 9: Apply guardrails based on deployment mode (FA mode only)
    if _features_available:
        try:
            mode_str = get_deployment_mode()
            mode = DeploymentMode(mode_str)
            enforcer = GuardrailEnforcer(mode)

            # Apply appropriate disclaimer based on mode
            metrics_dict = asdict(metrics)
            metrics_text = json.dumps(metrics_dict, indent=2, default=str)
            enforcer.add_professional_disclaimer(metrics_text)
            logger.info(f"Applied {mode_str} guardrails and disclaimers")
        except Exception as e:
            logger.warning(f"Could not apply mode-specific guardrails: {e}")

    # Export report
    analyzer.export_report(metrics, output_file)

    # Backfill ytm + duration into holdings_summary.json top_bonds so the LLM
    # compact summary includes analytics without needing a separate lookup.
    _backfill_holdings_summary(output_file, analyzer.bonds)

    # Emit compact JSON to stdout for LLM (full report is in output_file — do not read it)
    _compact_bond = {
        "_note": "Compact bond summary for LLM. Full report is at output_file — do NOT read that file.",
        "disclaimer": "EDUCATIONAL ANALYSIS - NOT INVESTMENT ADVICE",
        "bond_count": metrics.bond_count,
        "total_value": round(metrics.total_value, 2),
        "weighted_avg_ytm_pct": round(metrics.weighted_avg_ytm, 3),
        "weighted_avg_duration_yrs": round(metrics.weighted_avg_duration, 2),
        "duration_risk": metrics.duration_risk,
        "average_credit_quality": metrics.average_credit_quality,
        "annual_muni_tax_savings": round(metrics.total_annual_muni_tax_savings, 2),
        "asset_type_breakdown": {
            atype: {"count": d['count'], "value": round(d['value'], 2), "pct": round(d['pct'], 1)}
            for atype, d in metrics.asset_type_breakdown.items()
        },
        "maturity_ladder": {
            bucket: {"count": d['count'], "value": round(d['value'], 2), "pct": round(d['pct'], 1)}
            for bucket, d in metrics.maturity_ladder.items()
            if bucket in ['0-2y', '2-5y', '5-10y', '10+y']
        },
        "recommendations": metrics.recommendations[:5],
        "output_file": output_file,
    }
    print(json.dumps(_compact_bond, separators=(',', ':'), default=str))


if __name__ == '__main__':
    main()
