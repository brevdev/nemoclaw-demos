#!/usr/bin/env python3
"""
Standalone utility: fetch raw bond data (yields, credit ratings, duration, maturity).

NOTE: This is a standalone data-fetching utility, not the primary bond analysis command.
The main `/portfolio bonds` command routes through `bond_analyzer.py`, which provides
CDM-wrapped output, disclaimer enforcement, and FRED benchmark integration.

Use this script directly only when you need raw bond data without the full analysis pipeline:
    python3 fetch_bond_data.py <holdings.json> [output.json]
"""
import yfinance as yf
import polars as pl
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from pathlib import Path
from services.portfolio_utils import load_holdings_list
from rendering.disclaimer_wrapper import DisclaimerWrapper

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class BondDataFetcher:
    """Fetch and analyze bond-specific data"""

    # Bond ETF/Index mappings for yield curve analysis
    TREASURY_YIELDS = {
        'SHV': '1-3 Year Treasury',      # Short-term
        'IEF': '7-10 Year Treasury',     # Intermediate
        'TLT': '20+ Year Treasury',      # Long-term
    }

    CORPORATE_BONDS = {
        'LQD': 'Investment Grade Corp',
        'HYG': 'High Yield Corp',
    }

    MUNICIPAL_BONDS = {
        'MUB': 'National Muni Bonds',
    }

    INFLATION_PROTECTED = {
        'TIP': 'TIPS (5-Year)',
        'SCHP': 'TIPS (15-Year)',
    }

    # Credit rating scales
    CREDIT_RATINGS = {
        'AAA': 1,
        'AA+': 2,
        'AA': 3,
        'AA-': 4,
        'A+': 5,
        'A': 6,
        'A-': 7,
        'BBB+': 8,
        'BBB': 9,
        'BBB-': 10,
        'BB+': 11,
        'BB': 12,
        'BB-': 13,
        'B+': 14,
        'B': 15,
        'B-': 16,
        'CCC': 17,
        'CC': 18,
        'C': 19,
        'D': 20  # Default
    }

    def __init__(self):
        self.bond_data = {}
        self.yields = {}
        self.errors = []

    def calculate_ytm(self, current_price: float, coupon_rate: float, face_value: float = 100,
                      years_to_maturity: float = None) -> float:
        """
        Estimate Yield-to-Maturity (YTM) using simplified formula.
        For precise calculation, would need iterative solver.
        """
        if years_to_maturity is None or years_to_maturity <= 0:
            return 0.0

        if current_price <= 0:
            return 0.0

        annual_coupon = face_value * (coupon_rate / 100)
        price_gain_loss = (face_value - current_price) / years_to_maturity

        return ((annual_coupon + price_gain_loss) / current_price) * 100

    def calculate_duration(self, coupon_rate: float, ytm: float, years_to_maturity: float,
                          face_value: float = 100) -> Tuple[float, float]:
        """
        Calculate Macaulay Duration and Modified Duration.
        Duration measures interest rate sensitivity.
        """
        if years_to_maturity <= 0 or ytm < 0:
            return 0.0, 0.0

        try:
            # Simplified Macaulay Duration approximation
            # For precise calculation, would need cash flow analysis
            if ytm == coupon_rate:
                macaulay_duration = years_to_maturity / 2
            else:
                macaulay_duration = years_to_maturity * 0.75  # Approximation

            # Modified Duration = Macaulay Duration / (1 + YTM)
            modified_duration = macaulay_duration / (1 + (ytm / 100))

            return macaulay_duration, modified_duration
        except (ValueError, ZeroDivisionError) as e:
            logger.debug(f"Duration calculation error: {e}")
            return 0.0, 0.0

    def estimate_credit_rating(self, ytm: float, coupon_rate: float) -> Tuple[str, str]:
        """
        Estimate credit quality based on yield spread vs Treasury.
        This is a simplified heuristic; real ratings from S&P/Moody's.
        """
        try:
            # Simplified: bonds yielding >2% above Treasury are lower quality
            spread = ytm - coupon_rate

            if spread < 1.0:
                return "AAA/AA", "Excellent - Lowest risk"
            elif spread < 2.0:
                return "A", "Good - Low risk"
            elif spread < 3.5:
                return "BBB", "Fair - Moderate risk"
            elif spread < 5.0:
                return "BB", "Speculative - Higher risk"
            else:
                return "B or Lower", "High risk - Default possible"
        except (ValueError, TypeError, KeyError, IndexError):
            return "Unknown", "Unable to estimate"

    def fetch_bond_etf_data(self, etf_symbol: str) -> Optional[Dict]:
        """Fetch data for bond ETF (Treasury, Corporate, Muni, TIPS, etc)"""
        try:
            logger.info(f"Fetching bond ETF data for {etf_symbol}")
            ticker = yf.Ticker(etf_symbol)

            hist_pandas = ticker.history(period='1y')
            if hist_pandas.empty:
                logger.warning(f"No data found for {etf_symbol}")
                return None

            # Convert to Polars for consistent data handling
            hist = pl.from_pandas(hist_pandas.reset_index())

            # Get first and last Close prices using Polars
            close_prices = hist.select('Close').to_series()
            current_price = float(close_prices[-1]) if len(close_prices) > 0 else 0
            year_start_price = float(close_prices[0]) if len(close_prices) > 0 else current_price
            year_return = ((current_price - year_start_price) / year_start_price) * 100 if year_start_price > 0 else 0

            info = ticker.info
            dividend_yield = info.get('yield', info.get('dividend_yield', 0)) or 0

            return {
                'symbol': etf_symbol,
                'current_price': float(current_price),
                'year_return': float(year_return),
                'dividend_yield': float(dividend_yield) * 100 if dividend_yield else 0,
                'expense_ratio': float(info.get('expense_ratio', 0) or 0) * 100,
                'market_cap': info.get('market_cap', 'N/A'),
                'asset_class': self.TREASURY_YIELDS.get(etf_symbol) or
                             self.CORPORATE_BONDS.get(etf_symbol) or
                             self.MUNICIPAL_BONDS.get(etf_symbol) or
                             self.INFLATION_PROTECTED.get(etf_symbol) or
                             'Bond ETF'
            }
        except Exception as e:
            logger.error(f"Error fetching {etf_symbol}: {e}")
            self.errors.append(f"Failed to fetch {etf_symbol}: {e}")
            return None

    def analyze_portfolio_bonds(self, holdings_file: str, output_file: str = None) -> Dict:
        """Analyze all bonds in a portfolio"""
        try:
            # Use portfolio_utils to load holdings (handles nested JSON format)
            holdings = load_holdings_list(holdings_file)
            df = pl.DataFrame(holdings)

            # Filter for bonds (municipal_bond or bond types)
            bonds = df.filter(
                (pl.col('asset_type') == 'municipal_bond') | (pl.col('asset_type') == 'bond')
            ).to_dicts()

            if not bonds:
                logger.warning("No bonds found in portfolio")
                return {
                    'timestamp': datetime.now().isoformat(),
                    'total_bonds': 0,
                    'bonds_analyzed': [],
                    'portfolio_summary': {
                        'total_value': 0,
                        'average_ytm': 0,
                        'duration_weighted': 0,
                        'credit_quality': 'N/A'
                    }
        }

            logger.info(f"Analyzing {len(bonds)} bonds")

            bond_analysis = []
            total_value = 0
            ytm_weighted = 0
            duration_weighted = 0
            credit_qualities = []

            for bond in bonds:
                # Use CUSIP as primary identifier for municipal bonds
                cusip = bond.get('cusip', bond.get('symbol', 'Unknown'))
                bond_name = bond.get('name', cusip)
                shares = float(bond.get('quantity', bond.get('shares', 1)))  # For bonds, usually quantity
                current_price = float(bond.get('current_price', bond.get('purchase_price', 100)))
                coupon_rate = float(bond.get('coupon_rate', 0))
                maturity_date = bond.get('maturity_date', 'Unknown')
                purchase_price = float(bond.get('purchase_price', 100))

                # Calculate years to maturity
                try:
                    if maturity_date != 'Unknown':
                        mat_date = datetime.strptime(maturity_date, '%Y-%m-%d')
                        years_to_maturity = (mat_date - datetime.now()).days / 365.25
                    else:
                        years_to_maturity = 0
                except (ValueError, TypeError):
                    years_to_maturity = 0

                # Calculate YTM
                ytm = self.calculate_ytm(current_price, coupon_rate, face_value=100,
                                        years_to_maturity=years_to_maturity)

                # Calculate Duration
                macaulay_dur, modified_dur = self.calculate_duration(coupon_rate, ytm,
                                                                     years_to_maturity)

                # Estimate Credit Quality
                credit_rating, credit_description = self.estimate_credit_rating(ytm, coupon_rate)

                bond_value = shares * current_price
                total_value += bond_value

                bond_analysis.append({
                    'cusip': cusip,
                    'name': bond_name,
                    'quantity': shares,
                    'purchase_price': purchase_price,
                    'current_price': float(current_price),
                    'value': float(bond_value),
                    'coupon_rate': float(coupon_rate),
                    'maturity_date': maturity_date,
                    'years_to_maturity': float(years_to_maturity),
                    'ytm': float(ytm),
                    'macaulay_duration': float(macaulay_dur),
                    'modified_duration': float(modified_dur),
                    'credit_rating': credit_rating,
                    'credit_description': credit_description,
                    'interest_rate_sensitivity': f"{modified_dur:.2f}% price change per 1% rate increase"
                })

                if ytm > 0:
                    ytm_weighted += ytm * bond_value
                if modified_dur > 0:
                    duration_weighted += modified_dur * bond_value

                credit_qualities.append(self.CREDIT_RATINGS.get(credit_rating.split('/')[0], 10))

            # Calculate portfolio-level metrics
            if total_value > 0:
                avg_ytm = ytm_weighted / total_value
                avg_duration = duration_weighted / total_value
                avg_credit = sum(credit_qualities) / len(credit_qualities) if credit_qualities else 0

                # Map credit score back to rating
                credit_rating_map = {v: k for k, v in self.CREDIT_RATINGS.items()}
                estimated_rating = credit_rating_map.get(int(avg_credit), 'BBB')
            else:
                avg_ytm = 0
                avg_duration = 0
                estimated_rating = 'N/A'

            # Fetch benchmark bond ETF yields
            benchmarks = {}
            for etf, name in self.TREASURY_YIELDS.items():
                etf_data = self.fetch_bond_etf_data(etf)
                if etf_data:
                    benchmarks[etf] = etf_data

            report = {
                'timestamp': datetime.now().isoformat(),
                'total_bonds': len(bonds),
                'bonds_analyzed': bond_analysis,
                'portfolio_summary': {
                    'total_value': float(total_value),
                    'average_ytm': float(avg_ytm),
                    'average_macaulay_duration': float(duration_weighted / total_value if total_value > 0 else 0),
                    'estimated_credit_rating': estimated_rating,
                    'interest_rate_risk': 'High' if avg_duration > 7 else 'Moderate' if avg_duration > 4 else 'Low'
                },
                'benchmarks': benchmarks,
                'errors': self.errors if self.errors else None
            }

            if output_file:
                # Wrap with disclaimer and save (mode-aware: FA Dangerous Mode gets expanded disclaimer)
                try:
                    from config.config_loader import get_deployment_mode as _get_mode
                    _dep_mode = _get_mode()
                except Exception:
                    _dep_mode = None
                wrapped_report = DisclaimerWrapper.wrap_output(report, "Bond Portfolio Analysis", deployment_mode=_dep_mode)
                with open(output_file, 'w') as f:
                    json.dump(wrapped_report, f, indent=2, default=str)
                logger.info(f"Bond analysis saved to {output_file}")

            return report

        except Exception as e:
            logger.error(f"Error analyzing bonds: {e}")
            raise

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 fetch_bond_data.py <holdings.json> [output.json]")
        print("\nExample:")
        print("  python3 fetch_bond_data.py ~/portfolio_reports/holdings.json ~/portfolio_reports/bond_analysis.json")
        sys.exit(1)

    holdings_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    fetcher = BondDataFetcher()
    report = fetcher.analyze_portfolio_bonds(holdings_file, output_file)

    print("\n" + "="*60)
    print("BOND PORTFOLIO ANALYSIS")
    print("="*60)
    print(f"\nBonds Analyzed: {report['total_bonds']}")

    if report['total_bonds'] > 0:
        summary = report['portfolio_summary']
        print(f"Total Bond Value: ${summary['total_value']:,.2f}")
        print(f"Average YTM: {summary['average_ytm']:.2f}%")
        print(f"Average Duration: {summary['average_macaulay_duration']:.2f} years")
        print(f"Estimated Credit Rating: {summary['estimated_credit_rating']}")
        print(f"Interest Rate Risk: {summary['interest_rate_risk']}")

        print("\n" + "="*60)
        print("INDIVIDUAL BONDS")
        print("="*60)
        for bond in report['bonds_analyzed'][:5]:
            print(f"\n{bond['cusip']} - {bond['name']}")
            print(f"  Maturity: {bond['maturity_date']} ({bond['years_to_maturity']:.2f} years)")
            print(f"  Coupon: {bond['coupon_rate']:.2f}% | YTM: {bond['ytm']:.2f}%")
            print(f"  Duration: {bond['modified_duration']:.2f} years")
            print(f"  Credit: {bond['credit_rating']} - {bond['credit_description']}")
            print(f"  Value: ${bond['value']:,.2f}")

    if output_file:
        print(f"\nFull report saved to: {output_file}")
