#!/usr/bin/env python3
"""
Analyze portfolio performance: returns, risk metrics, diversification, alerts, projections.
Supports YTD, 12-month rolling, and custom date ranges.
Uses Polars for data handling and NumPy/SciPy for statistical calculations.
"""
import yfinance as yf
import polars as pl
import pandas as pd
import numpy as np
from scipy import stats
import sys
import os
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, Tuple, Optional
from pathlib import Path

from services.portfolio_utils import fetch_benchmark_returns
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


def _strip_interpretations(obj):
    """Remove verbose interpretation strings to reduce stdout token count.

    Strips keys whose value is a human-readable prose string (len >= 20)
    describing a numeric result. Short codes/tags (len < 20) are preserved.
    Applied to stdout JSON only — file writes keep the full data.
    """
    if isinstance(obj, dict):
        return {k: _strip_interpretations(v) for k, v in obj.items()
                if k not in ('interpretation', 'label', 'description')
                or not isinstance(v, str) or len(v) < 20}
    if isinstance(obj, list):
        return [_strip_interpretations(i) for i in obj]
    return obj


def _build_compact_summary(analysis_data: dict) -> dict:
    """Build a compact summary dict for stdout (2-3KB vs 352KB full data).

    Extracts only the most operationally relevant fields from analysis_data:
    portfolio-level metrics, top/bottom performers, high-risk and high-beta flags.
    """
    ps = analysis_data.get('portfolio_summary', {})
    performance = analysis_data.get('performance', {})

    # Build per-symbol rows with key metrics
    rows = []
    for sym, data in performance.items():
        sharpe_data = data.get('sharpe_ratio', {})
        vol_data = data.get('volatility', {})
        beta_data = data.get('beta', {})
        var_data = data.get('var', {})

        annual_return = sharpe_data.get('annual_return')
        sharpe = sharpe_data.get('sharpe_ratio')
        volatility = vol_data.get('annualized_volatility')
        beta = beta_data.get('beta')
        var_95 = var_data.get('var_95_annualized')  # already multiplied by 100

        rows.append({
            'symbol': sym,
            'return_pct': round(annual_return * 100, 2) if annual_return is not None else None,
            'sharpe': round(sharpe, 3) if sharpe is not None else None,
            'volatility': round(volatility, 4) if volatility is not None else None,
            'beta': round(beta, 3) if beta is not None else None,
            'var_95': round(var_95, 2) if var_95 is not None else None,
        })

    # Sort by return for top/bottom
    valid_rows = [r for r in rows if r['return_pct'] is not None]
    sorted_by_return = sorted(valid_rows, key=lambda x: x['return_pct'], reverse=True)

    top_5 = [{'symbol': r['symbol'], 'return_pct': r['return_pct'], 'sharpe': r['sharpe']}
              for r in sorted_by_return[:5]]
    bottom_5 = [{'symbol': r['symbol'], 'return_pct': r['return_pct']}
                for r in sorted_by_return[-5:]]

    # High-risk: volatility > 0.40 or VaR_95 > 5%
    high_risk = [
        {'symbol': r['symbol'], 'volatility': r['volatility'], 'var_95': r['var_95']}
        for r in rows
        if (r['volatility'] is not None and r['volatility'] > 0.40)
        or (r['var_95'] is not None and abs(r['var_95']) > 5.0)
    ][:10]

    # High-beta: beta > 1.5
    high_beta = [
        {'symbol': r['symbol'], 'beta': r['beta']}
        for r in rows
        if r['beta'] is not None and r['beta'] > 1.5
    ][:10]

    compact = {
        'portfolio_summary': {
            'period': analysis_data.get('period'),
            'holdings_analyzed': analysis_data.get('holdings_analyzed'),
            'success_rate': analysis_data.get('success_rate'),
            'weighted_volatility': round(ps.get('weighted_volatility', 0), 4),
            'weighted_sharpe': round(ps.get('weighted_sharpe', 0), 4),
        },
        'top_performers': top_5,
        'bottom_performers': bottom_5,
        'high_risk': high_risk,
        'high_beta': high_beta,
    }
    return compact


def _consult_performance_summary(compact: dict, client) -> str:
    """Call consultation model to synthesize compact portfolio summary.

    Args:
        compact: Compact summary dict from _build_compact_summary()
        client: ConsultationClient instance

    Returns:
        Synthesis text string (empty string on failure)
    """
    try:
        prompt = (
            "Synthesize this portfolio performance summary in 2-3 sentences "
            "highlighting key risks and opportunities: "
            + json.dumps(compact, separators=(',', ':'))
        )
        result = client.consult(prompt)
        return result.response if hasattr(result, 'response') else str(result)
    except Exception as e:
        logger.warning(f"Consultation synthesis failed: {e}")
        return ""


class PerformanceAnalyzer:
    def __init__(self):
        self.performance = {}
        self.risk_metrics = {}
        self.alerts = []

    @staticmethod
    def parse_date(date_str: str) -> str:
        """Convert date string to valid format, handle 'today', 'ytd', etc."""
        if not date_str or date_str.lower() == 'today':
            return datetime.now().strftime('%Y-%m-%d')
        elif date_str.lower() == 'ytd':
            year_start = datetime(datetime.now().year, 1, 1)
            return year_start.strftime('%Y-%m-%d')
        elif date_str.lower() == '12m':
            return (datetime.now() - timedelta(days=365)).strftime('%Y-%m-%d')
        elif date_str.lower() == '3m':
            return (datetime.now() - timedelta(days=90)).strftime('%Y-%m-%d')
        elif date_str.lower() == '1m':
            return (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
        else:
            # Assume YYYY-MM-DD format
            return date_str

    def fetch_equity_data(self, symbols: list, start_date: str, end_date: str) -> Tuple[pl.DataFrame, Dict, list]:
        """Fetch OHLC and dividend data for equities using Polars.

        NOTE: yfinance returns different column structures depending on symbol count:
        - Single symbol: columns are ['Open', 'High', 'Low', 'Close', 'Volume']
        - Multiple symbols: columns are MultiIndex like ('Open', 'AAPL'), ('Open', 'GOOGL'), etc.

        This method normalizes multi-symbol data into flat columns like 'Close_AAPL', 'Close_GOOGL'.
        """
        try:
            logger.info(f"Fetching data for {len(symbols)} symbols from {start_date} to {end_date}")

            # Download price data (yfinance returns pandas, convert to Polars)
            data_pd = yf.download(symbols, start=start_date, end=end_date, progress=False, auto_adjust=True)

            # Normalize column structure for both single and multiple symbols
            if len(symbols) == 1:
                # Single symbol - yfinance returns columns like ['Open', 'High', 'Low', 'Close', 'Volume']
                data_pd.columns = [col if isinstance(col, str) else col[0] for col in data_pd.columns.values]
                data_pl = pl.from_pandas(data_pd.reset_index())
                logger.debug(f"Single symbol mode: columns={list(data_pl.columns)}")
            else:
                # Multiple symbols - yfinance returns MultiIndex columns like ('Open', 'AAPL'), ('Close', 'AAPL')
                # Flatten to 'Close_AAPL', 'Close_GOOGL' format
                if isinstance(data_pd.columns, pd.MultiIndex):
                    # MultiIndex: flatten to 'metric_symbol' format
                    new_columns = []
                    for col in data_pd.columns:
                        metric, symbol = col  # ('Close', 'AAPL') -> 'Close_AAPL'
                        new_columns.append(f"{metric}_{symbol}")
                    data_pd.columns = new_columns
                    logger.debug(f"Multi-symbol mode (MultiIndex): converted {len(data_pd.columns)} columns")
                else:
                    # Single-level columns (shouldn't happen with multiple symbols, but handle it)
                    logger.warning(f"Multi-symbol download returned single-level columns (unusual)")

                data_pl = pl.from_pandas(data_pd.reset_index())
                logger.debug(f"Multi-symbol final columns: {list(data_pl.columns)[:10]}...")  # Log first 10

            if data_pl.is_empty():
                raise ValueError("No data returned from Yahoo Finance. Check symbols and date range.")

            # Fetch dividends for all symbols
            dividends = {}
            for sym in symbols:
                try:
                    ticker = yf.Ticker(sym)
                    div_data = ticker.dividends
                    if not div_data.empty:
                        div_data = div_data[(div_data.index >= start_date) & (div_data.index <= end_date)]
                        dividends[sym] = float(div_data.sum()) if len(div_data) > 0 else 0.0
                    else:
                        dividends[sym] = 0.0
                except Exception as e:
                    logger.warning(f"Could not fetch dividends for {sym}: {e}")
                    dividends[sym] = 0.0

            return data_pl, dividends, symbols

        except Exception as e:
            logger.error(f"Error fetching equity data: {e}")
            raise

    @staticmethod
    def _validate_array(arr: np.ndarray, symbol: str, operation: str) -> Tuple[bool, str]:
        """Validate that array is suitable for financial calculations.

        Returns: (is_valid, debug_message)
        """
        if arr is None:
            return False, f"{symbol} {operation}: array is None"
        if len(arr) == 0:
            return False, f"{symbol} {operation}: array is empty (len=0)"
        if len(arr) < 2:
            return False, f"{symbol} {operation}: array too short (len={len(arr)}, need >= 2)"
        nan_count = np.isnan(arr).sum()
        if nan_count == len(arr):
            return False, f"{symbol} {operation}: all values NaN ({nan_count}/{len(arr)})"
        if nan_count > 0:
            return False, f"{symbol} {operation}: partial NaN values ({nan_count}/{len(arr)})"
        return True, f"{symbol} {operation}: valid (len={len(arr)}, min={np.min(arr):.6f}, max={np.max(arr):.6f}, mean={np.mean(arr):.6f})"

    def calculate_returns(self, price_data: pl.DataFrame, symbol: str,
                         annual_dividend: float = 0.0) -> np.ndarray:
        """Calculate total daily returns from price data including dividend yield.

        FORMULA:
        --------
        Daily Return = (Price_t - Price_t-1) / Price_t-1 + Daily Dividend Yield
        where Daily Dividend Yield = (Annual Dividend / Average Price) / 252

        REFERENCES:
        -----------
        - Price returns: Standard daily return calculation (widely used in finance)
        - Dividend adjustment: Standard practice per MSCI, Bloomberg, FactSet methodologies
        - 252: Standard number of trading days per year (NYSE/NASDAQ)

        Args:
            price_data: DataFrame with price data (Date, Close prices)
            symbol: Stock symbol to extract price column
            annual_dividend: Annual dividend amount. If provided, adds daily dividend yield to returns.

        Returns:
            Array of daily returns including dividend contribution

        Example:
            returns = analyzer.calculate_returns(df, 'AAPL', annual_dividend=0.94)
            # Returns include both price appreciation and dividend income
        """
        try:
            # Extract close prices for the symbol
            # For multi-symbol downloads, columns are named like 'Close_AAPL', 'Close_GOOGL'
            # For single-symbol downloads, column is just 'Close'
            close_col = f'Close_{symbol}'
            if close_col not in price_data.columns:
                # Fallback: look for just 'Close' (single symbol mode)
                if 'Close' in price_data.columns:
                    close_col = 'Close'
                else:
                    # Last resort: find any Close column
                    close_cols = [col for col in price_data.columns if 'Close' in col]
                    if not close_cols:
                        raise ValueError(f"No Close price found for {symbol}. Available columns: {list(price_data.columns)}")
                    close_col = close_cols[0]

            prices = price_data.select(close_col).to_numpy().flatten()

            # Validate price data
            is_valid, msg = self._validate_array(prices, symbol, "prices")
            if not is_valid:
                logger.error(msg)
                raise ValueError(msg)

            # Calculate daily price returns as percentage change
            price_returns = np.diff(prices) / prices[:-1]

            # Validate returns
            is_valid, msg = self._validate_array(price_returns, symbol, "price_returns")
            if not is_valid:
                logger.error(msg)
                raise ValueError(msg)

            # Add dividend contribution if provided
            if annual_dividend > 0 and len(prices) > 0:
                # Daily dividend yield = annual_dividend / average_price / 252
                avg_price = np.mean(prices)
                daily_dividend_yield = (annual_dividend / avg_price) / 252
                total_returns = price_returns + daily_dividend_yield
                logger.debug(f"{symbol}: Added daily dividend yield of {daily_dividend_yield*100:.3f}% ({annual_dividend:.2f}/year at {avg_price:.2f} avg price)")
            else:
                total_returns = price_returns

            is_valid, msg = self._validate_array(total_returns, symbol, "final_returns")
            logger.debug(msg)
            return total_returns

        except Exception as e:
            logger.error(f"Error calculating returns for {symbol}: {e}")
            raise

    def calculate_volatility(self, returns: np.ndarray, symbol: str = 'UNKNOWN', window: int = 30) -> Dict:
        """Calculate volatility metrics using NumPy.

        FORMULA:
        --------
        Daily Volatility = sqrt( sum((R_i - mean(R))^2) / (n-1) )
        Annualized Volatility = Daily Volatility × sqrt(252)

        where:
        - R_i = daily return
        - n = number of observations
        - n-1 = Bessel's correction (sample variance, ddof=1)
        - 252 = trading days per year

        REFERENCES:
        -----------
        - Sample standard deviation (ddof=1): Standard practice per ISO 3534-1, NIST SP 800-22
        - Annualization: 252 trading days per MSCI, Bloomberg methodologies
        - Source: Modern Portfolio Theory (Markowitz, 1952)

        Uses sample standard deviation (ddof=1, Bessel's correction) for statistical consistency
        with population estimation. This is preferred for historical volatility calculations.
        """
        try:
            is_valid, msg = self._validate_array(returns, symbol, "volatility_input")
            if not is_valid:
                logger.warning(msg)
                return {'_valid': False, '_error': msg, 'annualized_volatility': None}

            if len(returns) < window:
                window = max(1, len(returns) - 1)

            # Annualized volatility (using sample std dev with ddof=1)
            daily_vol = np.std(returns, ddof=1)  # Sample std dev
            annual_vol = daily_vol * np.sqrt(252)  # 252 trading days

            # Rolling volatility
            rolling_vols = []
            for i in range(len(returns) - window + 1):
                vol = np.std(returns[i:i+window], ddof=1) * np.sqrt(252)  # Sample std dev
                rolling_vols.append(vol)

            result = {
                '_valid': True,
                'daily_volatility': float(daily_vol),
                'annualized_volatility': float(annual_vol),
                'rolling_volatility_30d': float(np.mean(rolling_vols)) if rolling_vols else 0.0,
                'high_volatility': float(np.max(rolling_vols)) if rolling_vols else 0.0,
                'low_volatility': float(np.min(rolling_vols)) if rolling_vols else 0.0,
                'note': 'Volatility calculated using sample standard deviation (ddof=1)'
            }
            logger.debug(f"{symbol}: volatility={annual_vol:.4f}")
            return result

        except Exception as e:
            logger.error(f"Error calculating volatility for {symbol}: {e}")
            return {'_valid': False, '_error': str(e), 'annualized_volatility': None}

    def calculate_beta(self, returns: np.ndarray, symbol: str = 'UNKNOWN', benchmark: str = 'SPY') -> Dict:
        """Calculate beta (systematic risk) relative to benchmark using NumPy.

        FORMULA:
        --------
        Beta = Cov(Asset_Returns, Benchmark_Returns) / Var(Benchmark_Returns)

        where:
        - Cov = covariance between asset and benchmark (measures co-movement)
        - Var = variance of benchmark returns
        - Both use sample variance (ddof=1, Bessel's correction)

        INTERPRETATION:
        ----------------
        - Beta > 1.0: Asset is more volatile than market (amplifies market moves)
        - Beta = 1.0: Asset moves in line with market (neutral risk)
        - Beta < 1.0: Asset is less volatile than market (dampens market moves)
        - Beta ≤ 0: Asset moves opposite to market (rare, inverse correlation)

        REFERENCES:
        -----------
        - Source: Capital Asset Pricing Model (CAPM) - Sharpe (1964)
        - Standard practice: Bloomberg, FactSet, MSCI
        - Sample variance (ddof=1): Preferred for historical estimation per NIST guidelines
        - Benchmark: SPY = S&P 500 broad market index (default market proxy)

        Note: Beta is backward-looking (historical). Stability depends on time period selected.
        """
        try:
            is_valid, msg = self._validate_array(returns, symbol, "beta_input")
            if not is_valid:
                logger.warning(msg)
                return {'_valid': False, '_error': msg, 'beta': None}

            # Fetch benchmark returns (cached to avoid redundant API calls)
            bench_returns = fetch_benchmark_returns(benchmark, period='1y')

            is_valid_bench, msg_bench = self._validate_array(bench_returns, benchmark, "benchmark_returns")
            if not is_valid_bench:
                logger.warning(f"{symbol}: {msg_bench}")
                return {'_valid': False, '_error': msg_bench, 'beta': None}

            # Align lengths
            min_len = min(len(returns), len(bench_returns))
            returns_aligned = returns[-min_len:]
            bench_returns_aligned = bench_returns[-min_len:]

            # Calculate beta using covariance and variance with consistent ddof=1 (sample)
            covariance = np.cov(returns_aligned, bench_returns_aligned)[0][1]  # np.cov uses ddof=1 by default
            benchmark_variance = np.var(bench_returns_aligned, ddof=1)  # Explicitly use ddof=1 for consistency

            beta = covariance / benchmark_variance if benchmark_variance != 0 else 0.0

            interpretation = 'Higher volatility than market' if beta > 1 else \
                           'Lower volatility than market' if beta < 1 else \
                           'Moves with market'

            result = {
                '_valid': True,
                'beta': float(beta),
                'interpretation': interpretation,
                'note': f'Beta calculated vs {benchmark} using {min_len} periods (ddof=1 sample variance)'
            }
            logger.debug(f"{symbol}: beta={beta:.4f}")
            return result

        except Exception as e:
            logger.warning(f"Could not calculate beta for {symbol}: {e}")
            return {'_valid': False, '_error': str(e), 'beta': None}

    def calculate_var(self, returns: np.ndarray, symbol: str = 'UNKNOWN', confidence: float = 0.95) -> Dict:
        """Calculate Value at Risk (VaR) and Conditional VaR (daily and annualized).

        FORMULA - VALUE AT RISK (VaR):
        --------------------------------
        VaR_95% = Percentile(returns, 5th)  [for 95% confidence level]

        In plain English: "There is a 95% probability that losses will NOT exceed X%"
        Or equivalently: "There is a 5% probability of losing more than X% in one day"

        FORMULA - CONDITIONAL VALUE AT RISK (CVaR, aka Expected Shortfall):
        -----------------------------------------------------------------
        CVaR_95% = Mean(returns where returns ≤ VaR_95%)

        In plain English: "If the worst 5% of days occur, the average loss would be X%"

        ANNUALIZATION:
        ---------------
        Annualized VaR = Daily VaR × √252
        where 252 = trading days per year

        REFERENCES:
        -----------
        - VaR methodology: Bank for International Settlements (BIS), Basel Accords
        - Historical simulation: Standard practice (Dowd, 2007)
        - CVaR (Expected Shortfall): Superior to VaR (tail-risk aware) - Rockafellar & Uryasev (2002)
        - 95% confidence: Standard for portfolio risk reporting (JP Morgan, BlackRock, etc.)

        Note: VaR assumes returns are i.i.d. and may underestimate tail risk in stressed markets.
        """
        try:
            is_valid, msg = self._validate_array(returns, symbol, "var_input")
            if not is_valid:
                logger.warning(msg)
                return {'_valid': False, '_error': msg, 'var_95_daily': None, 'var_95_annualized': None}

            # VaR as percentile of returns
            daily_var = np.percentile(returns, (1 - confidence) * 100)
            annualized_var = daily_var * np.sqrt(252)  # Annualize (252 trading days)

            # Conditional VaR (expected loss beyond VaR)
            daily_cvar = np.mean(returns[returns <= daily_var])
            annualized_cvar = daily_cvar * np.sqrt(252)

            result = {
                '_valid': True,
                'var_95_daily': float(daily_var) * 100,
                'var_95_annualized': float(annualized_var) * 100,
                'cvar_95_daily': float(daily_cvar) * 100,
                'cvar_95_annualized': float(annualized_cvar) * 100,
                'interpretation_daily': f'Daily (95% confidence): worst expected daily loss of {daily_var*100:.2f}%',
                'interpretation_annualized': f'Annual (95% confidence): worst expected annual loss of {annualized_var*100:.2f}%',
                'note': 'Annualized VaR = Daily VaR × √252. Use annualized for planning purposes.'
            }
            logger.debug(f"{symbol}: VaR_95_annualized={annualized_var*100:.2f}%")
            return result

        except Exception as e:
            logger.error(f"Error calculating VaR for {symbol}: {e}")
            return {'_valid': False, '_error': str(e), 'var_95_daily': None, 'var_95_annualized': None}

    def _get_current_risk_free_rate(self) -> float:
        """Fetch current risk-free rate (3-month T-bill yield) from yfinance.

        Returns:
            Annual risk-free rate as decimal (0.045 = 4.5%)
        """
        try:
            # Fetch 3-month T-bill yield
            tbill = yf.Ticker('^IRX')
            # IRX is quoted as annual percentage (e.g., 4.50 for 4.5%)
            current_yield = tbill.info.get('regularMarketPrice', 2.0)
            # Convert from percentage to decimal
            risk_free_rate = max(0.0, current_yield / 100)
            logger.info(f"Fetched current T-bill yield: {current_yield:.2f}%")
            return risk_free_rate
        except Exception as e:
            logger.warning(f"Could not fetch current T-bill yield: {e}. Using 2.0% default.")
            return 0.02

    def calculate_sharpe_ratio(self, returns: np.ndarray, symbol: str = 'UNKNOWN', risk_free_rate: float = None) -> Dict:
        """Calculate Sharpe Ratio: risk-adjusted return relative to risk-free rate.

        FORMULA:
        --------
        Sharpe Ratio = (Annual Return - Risk-Free Rate) / Annual Volatility

        In plain English: "How much excess return are you getting per unit of risk taken?"

        Where:
        - Annual Return = Daily Return Average × 252
        - Annual Volatility = Daily Volatility × √252
        - Risk-Free Rate = Current U.S. Treasury yield (3-month T-Bill by default)

        INTERPRETATION:
        ----------------
        - Sharpe > 1.0: Good risk-adjusted return (1 unit return per 1 unit risk)
        - Sharpe > 2.0: Excellent risk-adjusted return (professional quality)
        - Sharpe > 3.0: Outstanding risk-adjusted return (rare)
        - Negative Sharpe: Portfolio underperformed risk-free rate
        - Higher Sharpe is better (more return per unit of risk)

        REFERENCES:
        -----------
        - Source: William Sharpe, Nobel Prize in Economics (1990)
        - Original paper: "Mutual Fund Performance" (1966)
        - Standard practice: Morningstar, S&P, Bloomberg, institutional investors
        - Risk-free rate: U.S. Treasury 3-month yield (^IRX ticker, updated daily)

        Args:
            returns: Array of daily returns (decimal, e.g., 0.01 = 1%)
            symbol: Stock symbol for logging context
            risk_free_rate: Annual risk-free rate (e.g., 0.045 = 4.5%).
                           If None, fetches current T-bill yield from Yahoo Finance.

        Returns:
            Dict with sharpe_ratio, annual_return, annual_volatility, risk_free_rate_used, note

        Note: Sharpe Ratio assumes returns are normally distributed and independent.
              It may not capture tail risks or non-linear relationships.
        """
        try:
            is_valid, msg = self._validate_array(returns, symbol, "sharpe_input")
            if not is_valid:
                logger.warning(msg)
                return {'_valid': False, '_error': msg, 'sharpe_ratio': None}

            if risk_free_rate is None:
                risk_free_rate = self._get_current_risk_free_rate()

            annual_return = np.mean(returns) * 252
            annual_vol = np.std(returns, ddof=1) * np.sqrt(252)  # Use sample std dev

            sharpe = (annual_return - risk_free_rate) / annual_vol if annual_vol != 0 else 0.0

            result = {
                '_valid': True,
                'sharpe_ratio': float(sharpe),
                'annual_return': float(annual_return),
                'annual_volatility': float(annual_vol),
                'risk_free_rate_used': float(risk_free_rate),
                'note': 'Sharpe ratio = (annual_return - risk_free_rate) / annual_volatility. Risk-free rate fetched from current T-bill yield.'
            }
            logger.debug(f"{symbol}: sharpe={sharpe:.4f}")
            return result

        except Exception as e:
            logger.error(f"Error calculating Sharpe Ratio for {symbol}: {e}")
            return {'_valid': False, '_error': str(e), 'sharpe_ratio': None}

    def calculate_drawdown(self, prices: np.ndarray, symbol: str = 'UNKNOWN') -> Dict:
        """Calculate maximum drawdown (peak-to-bottom loss) using NumPy.

        FORMULA:
        --------
        For each point in time:
            Drawdown_t = (Price_t - Running_Max) / Running_Max

        where:
        - Running_Max = highest price seen from beginning to time t
        - Price_t = current price at time t
        - Drawdown is negative (represents a loss from peak)

        Maximum Drawdown = minimum drawdown value across all time periods

        In plain English: "What is the worst peak-to-trough loss the portfolio experienced?"

        EXAMPLE:
        --------
        Portfolio value: $100 → $150 (peak) → $120 → $110
        From peak ($150) to trough ($110):
        Drawdown = ($110 - $150) / $150 = -26.7%

        REFERENCES:
        -----------
        - Standard practice: Morningstar, Zephyr StyleADVISOR, eSpeed
        - Risk metric: Widely used to assess downside experience
        - Related: Recovery time after drawdown is also important
        """
        try:
            is_valid, msg = self._validate_array(prices, symbol, "drawdown_prices")
            if not is_valid:
                logger.warning(msg)
                return {'_valid': False, '_error': msg, 'max_drawdown': None}

            cumulative = np.cumprod(1 + np.diff(prices) / prices[:-1])
            running_max = np.maximum.accumulate(cumulative)
            drawdown = (cumulative - running_max) / running_max
            max_drawdown = np.min(drawdown)

            result = {
                '_valid': True,
                'max_drawdown': float(max_drawdown) * 100,
                'interpretation': f'Worst peak-to-bottom loss: {max_drawdown*100:.2f}%'
            }
            logger.debug(f"{symbol}: max_drawdown={max_drawdown*100:.2f}%")
            return result

        except Exception as e:
            logger.error(f"Error calculating drawdown for {symbol}: {e}")
            return {'_valid': False, '_error': str(e), 'max_drawdown': None}

    def analyze_portfolio(self, holdings_file: str, output_file: str = None, start_date: str = '12m') -> Dict:
        """Complete portfolio performance analysis."""
        try:
            # Phase 9: Check feature availability
            if _features_available:
                try:
                    mode_str = get_deployment_mode()
                    mode = DeploymentMode(mode_str)
                    fm = FeatureManager(mode)
                    fm.require_feature(Feature.PERFORMANCE_ANALYSIS)  # Core feature, all modes
                    logger.info(f"Performance analysis enabled for {mode_str} mode")
                except FeatureNotAvailableError as e:
                    logger.error(f"Performance analysis not available: {e}")
                    raise

            from services.portfolio_utils import load_holdings_list
            from config.schema import normalize_portfolio, validate_portfolio

            raw = json.load(open(holdings_file))
            raw = normalize_portfolio(raw)
            validate_portfolio(raw)
            holdings = load_holdings_list(raw)

            start_date = self.parse_date(start_date)
            end_date = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')  # Use yesterday to ensure complete yfinance data

            # Fetch data for equities
            equity_symbols = [h['symbol'] for h in holdings if h.get('asset_type') == 'equity']

            if not equity_symbols:
                logger.warning("No equity holdings found")
                return {'holdings': 0, 'performance': {}}

            price_data, dividends, symbols = self.fetch_equity_data(equity_symbols, start_date, end_date)

            performance_summary = {}

            valid_symbols = []
            for symbol in symbols:
                logger.info(f"Analyzing {symbol}")

                try:
                    # Get annual dividend for this symbol
                    dividend = dividends.get(symbol, 0.0)
                    returns = self.calculate_returns(price_data, symbol, annual_dividend=dividend)

                    vol = self.calculate_volatility(returns, symbol=symbol)
                    beta = self.calculate_beta(returns, symbol=symbol)
                    sharpe = self.calculate_sharpe_ratio(returns, symbol=symbol)
                    var = self.calculate_var(returns, symbol=symbol)

                    # Check if all calculations succeeded
                    if all(metric.get('_valid', True) for metric in [vol, beta, sharpe, var]):
                        performance_summary[symbol] = {
                            'volatility': vol,
                            'beta': beta,
                            'sharpe_ratio': sharpe,
                            'var': var,
                            'dividends': dividends.get(symbol, 0.0)
                        }
                        valid_symbols.append(symbol)
                        logger.info(f"✓ {symbol}: analysis complete")
                    else:
                        failed_metrics = [m for m in [vol, beta, sharpe, var] if not m.get('_valid', True)]
                        logger.warning(f"✗ {symbol}: {len(failed_metrics)}/4 metrics failed: {[m.get('_error', 'unknown') for m in failed_metrics]}")
                except Exception as e:
                    logger.error(f"✗ {symbol}: Fatal error - {e}")

            # Calculate value-weighted portfolio metrics (using only valid symbols)
            # Get closing prices for weighting
            position_weights = {}
            total_value = 0.0

            for symbol in valid_symbols:
                try:
                    close_col = f'Close_{symbol}'
                    if close_col not in price_data.columns:
                        # Fallback: look for just 'Close' (single symbol mode)
                        if 'Close' in price_data.columns:
                            close_col = 'Close'
                        else:
                            close_cols = [col for col in price_data.columns if 'Close' in col]
                            if not close_cols:
                                raise ValueError(f"No Close column for {symbol}")
                            close_col = close_cols[0]

                    # Get latest price
                    latest_price_data = price_data.select(close_col).tail(1).to_numpy().flatten()
                    latest_price = float(latest_price_data[0]) if len(latest_price_data) > 0 else 1.0

                    # Ensure we have a valid price
                    if latest_price is None or latest_price != latest_price:  # NaN check
                        latest_price = 1.0

                    # Assume 1 share for weight calculation (we don't have actual share counts)
                    position_weights[symbol] = latest_price
                    total_value += latest_price
                except (ValueError, TypeError, KeyError, IndexError) as e:
                    logger.warning(f"Could not get price for {symbol}: {e}")
                    position_weights[symbol] = 1.0
                    total_value += 1.0

            # Normalize weights
            for symbol in position_weights:
                position_weights[symbol] = position_weights[symbol] / total_value if total_value > 0 else 1.0 / len(valid_symbols)

            # Calculate value-weighted metrics (using valid symbols only)
            weighted_volatility = sum(
                position_weights.get(symbol, 0) * performance_summary[symbol]['volatility'].get('annualized_volatility', 0)
                for symbol in valid_symbols if symbol in performance_summary and performance_summary[symbol]['volatility'].get('_valid', True)
            )
            weighted_sharpe = sum(
                position_weights.get(symbol, 0) * performance_summary[symbol]['sharpe_ratio'].get('sharpe_ratio', 0)
                for symbol in valid_symbols if symbol in performance_summary and performance_summary[symbol]['sharpe_ratio'].get('_valid', True)
            )

            analysis_data = {
                'period': start_date,
                'holdings_analyzed': len(performance_summary),
                'holdings_valid': len(valid_symbols),
                'holdings_failed': len(symbols) - len(valid_symbols),
                'success_rate': f"{len(valid_symbols) / len(symbols) * 100:.1f}%" if len(symbols) > 0 else "0%",
                'performance': performance_summary,
                'portfolio_summary': {
                    'weighted_volatility': float(weighted_volatility),
                    'weighted_sharpe': float(weighted_sharpe),
                    'note': 'Metrics are value-weighted based on closing prices. For accurate portfolio-level analysis, use actual position sizes and calculate from portfolio returns.',
                    'warning': f'Based on {len(valid_symbols)}/{len(symbols)} valid symbols. {len(symbols)-len(valid_symbols)} symbols failed analysis (insufficient data, NaN returns, or calculation errors).',
                    'valid_symbols_only': True
                }
            }

            # Phase 9: Apply guardrails based on deployment mode
            if _features_available:
                try:
                    mode_str = get_deployment_mode()
                    mode = DeploymentMode(mode_str)
                    enforcer = GuardrailEnforcer(mode)

                    # Apply appropriate disclaimer based on mode
                    performance_text = json.dumps(analysis_data, indent=2)
                    enforcer.add_professional_disclaimer(performance_text)
                    logger.info(f"Applied {mode_str} guardrails and disclaimers")
                except Exception as e:
                    logger.warning(f"Could not apply mode-specific guardrails: {e}")

            # Wrap with compliance disclaimers (compact=True omits static metadata ~60 tokens)
            _mode_str = mode_str if 'mode_str' in dir() else (get_deployment_mode() if _features_available else None)
            report = DisclaimerWrapper.wrap_output(analysis_data, 'Portfolio Performance Analysis', compact=True, deployment_mode=_mode_str)

            # Strip verbose interpretation strings for stdout token reduction
            report = _strip_interpretations(report)

            if output_file:
                DisclaimerWrapper.wrap_and_save(analysis_data, output_file, 'Portfolio Performance Analysis', deployment_mode=_mode_str)
                logger.info(f"Performance analysis saved to {output_file}")

            return report

        except Exception as e:
            logger.error(f"Error analyzing portfolio: {e}")
            raise


if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 analyze_performance.py <holdings.json> [output.json] [start_date]")
        print("\nExample:")
        print("  python3 analyze_performance.py ~/portfolio_reports/holdings.json ~/portfolio_reports/performance.json 12m")
        sys.exit(1)

    holdings_file = sys.argv[1]
    start_date = sys.argv[2] if len(sys.argv) > 2 else 'ytd'
    end_date = sys.argv[3] if len(sys.argv) > 3 else 'today'
    output_file = sys.argv[4] if len(sys.argv) > 4 else None

    analyzer = PerformanceAnalyzer()

    # Run analysis — full data saved to output_file, compact summary to stdout
    from services.portfolio_utils import load_holdings_list
    from config.schema import normalize_portfolio, validate_portfolio

    raw = json.load(open(holdings_file))
    raw = normalize_portfolio(raw)
    holdings = load_holdings_list(raw)
    equity_symbols = [h['symbol'] for h in holdings if h.get('asset_type') == 'equity']

    report = analyzer.analyze_portfolio(holdings_file, output_file, start_date)

    # Extract raw analysis_data for compact summary (unwrap DisclaimerWrapper envelope)
    _data = report.get('data', report)

    # Build compact summary (~2-3KB) instead of printing full per-symbol JSON
    compact = _build_compact_summary(_data)

    # Part B: Consultation synthesis for large equity portfolios
    consultation_enabled = os.environ.get("INVESTORCLAW_CONSULTATION_ENABLED", "").lower() == "true"
    if consultation_enabled and len(equity_symbols) > 50:
        try:
            from tier3_enrichment import ConsultationClient
            client = ConsultationClient()
            if client.is_available():
                synthesis = _consult_performance_summary(compact, client)
                if synthesis:
                    compact["consultation_synthesis"] = synthesis
        except Exception as _e:
            logger.warning(f"Consultation import/call failed: {_e}")

    print(json.dumps(compact, separators=(',', ':')))

    if output_file:
        logger.info(f"Full performance data saved to: {output_file}")
