#!/usr/bin/env python3
"""
Fetch current portfolio holdings and values from CSV/XLS input using Polars.
Supports equity, bond, cash, and margin positions.
Polars provides significant speed improvements over pandas for data filtering and aggregation.

Pure Polars environment: all data loading and manipulation uses Polars natively.
Legacy .xls files are read via xlrd directly (no pandas) and converted to Polars
column-by-column. No pandas DataFrames are created or used anywhere in this module.
"""
import polars as pl
import re
import sys
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Dict, List, Tuple, Optional, Union
from pathlib import Path

from rendering.disclaimer_wrapper import DisclaimerWrapper

# Canonical internal holdings model (used throughout processing)
from models.holdings import Holding

# FINOS CDM-compliant portfolio model, current output format
from models.cdm_portfolio import (
    Portfolio,
    PortfolioState,
    Position,
    Product,
    Asset,
    ProductIdentifier,
    PriceQuantity,
    Quantity,
    Price,
    PortfolioSummary,
    AggregationParameters,
    AnalysisMetadata,
    CDMPortfolioResult,
)

logging.basicConfig(level=logging.WARNING, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

_SECTOR_CACHE_FILE = Path(__file__).parent.parent / "portfolios" / ".sector_cache.json"


def _detect_espp_accounts(equity_df: pl.DataFrame) -> Dict[str, List[str]]:
    """
    Interactive ESPP symbol+account detection during portfolio discovery.

    Analyzes symbols and accounts in portfolio, then prompts user to identify which
    symbol+account combinations contain ESPP holdings.

    Returns: Dict mapping symbol -> [ESPP accounts for that symbol]
    """
    try:
        # Extract symbols and accounts from portfolio
        symbols_by_account = {}  # account -> [symbols]

        if 'account' in equity_df.columns and 'symbol' in equity_df.columns:
            for row in equity_df.select(['account', 'symbol']).to_dicts():
                account = row.get('account')
                symbol = row.get('symbol')
                if account and symbol:
                    account_clean = str(account).strip()
                    symbol_clean = str(symbol).strip()
                    if account_clean not in symbols_by_account:
                        symbols_by_account[account_clean] = set()
                    symbols_by_account[account_clean].add(symbol_clean)

        if not symbols_by_account:
            logger.debug("No accounts/symbols found in portfolio - skipping ESPP detection")
            return {}

        # Display unique symbols across all accounts
        logger.info(f"\n{'=' * 70}")
        logger.info("ESPP SYMBOL DETECTION")
        logger.info("=" * 70)
        logger.info("Symbols detected in your portfolio:\n")

        symbol_accounts = {}  # symbol -> [accounts]
        for account, symbols in symbols_by_account.items():
            for symbol in symbols:
                if symbol not in symbol_accounts:
                    symbol_accounts[symbol] = []
                symbol_accounts[symbol].append(account)

        for i, (symbol, accounts) in enumerate(sorted(symbol_accounts.items()), 1):
            accounts_str = ', '.join(sorted(accounts))
            logger.info(f"  {i}. {symbol:8} in {accounts_str}")

        logger.info(f"\n⚠️  Some symbols may have ESPP holdings in specific accounts")
        logger.info("Example: MSFT regular in IRA + MSFT ESPP in Demo ESPP Account")
        logger.info("\nYou can configure ESPP symbol+accounts via environment variable.")
        logger.info("Set ESPP_HOLDINGS=SYMBOL:ACCOUNT,SYMBOL:ACCOUNT")
        logger.info("Example: export ESPP_HOLDINGS='MSFT:Demo ESPP Account,NVDA:Demo ESPP Account'")

        # Return empty dict - will be populated during setup if user specifies
        return {}

    except Exception as e:
        logger.debug(f"ESPP detection failed: {e} - continuing without ESPP marking")
        return {}


def _load_espp_holdings_from_env() -> Dict[str, List[str]]:
    """
    Load ESPP symbol+account configuration from environment variables.

    Format: ESPP_HOLDINGS=symbol:account,symbol:account,...
    Examples:
      ESPP_HOLDINGS=MSFT:Demo ESPP Account,NVDA:Demo ESPP Account
      ESPP_HOLDINGS=MSFT:Demo ESPP Account;Demo ESPP Account,NVDA:Demo ESPP Account
      (semicolon = multiple ESPP accounts for one symbol)

    Returns: Dict mapping symbol -> [list of ESPP accounts for that symbol]
    """
    import os
    espp_str = os.environ.get('ESPP_HOLDINGS', '').strip()

    if not espp_str:
        return {}

    espp_holdings = {}
    # Parse "SYMBOL:account1;account2,SYMBOL2:account3" format
    for pair in espp_str.split(','):
        if ':' not in pair:
            continue
        symbol, accounts_str = pair.split(':', 1)
        symbol = symbol.strip()
        # Handle multiple accounts for same symbol: account1;account2
        accounts = [acc.strip() for acc in accounts_str.split(';') if acc.strip()]
        if symbol and accounts:
            espp_holdings[symbol] = accounts

    if espp_holdings:
        logger.info(f"Loaded ESPP holdings from environment: {espp_holdings}")
    return espp_holdings


def _is_espp_holding(symbol: str, account_name: Optional[str], espp_holdings: Dict[str, List[str]]) -> bool:
    """
    Check if a symbol+account combination is marked as ESPP.

    Args:
        symbol: Stock symbol (MSFT, NVDA, etc.)
        account_name: Account name from portfolio
        espp_holdings: Dict mapping symbol -> [ESPP accounts]

    Returns: True if this symbol in this account is ESPP, False otherwise
    """
    if not symbol or not account_name or symbol not in espp_holdings:
        return False

    account_clean = str(account_name).strip()
    espp_accounts = espp_holdings[symbol]

    # Check for exact match or substring match
    return any(
        account_clean == acc or acc in account_clean
        for acc in espp_accounts
    )


def _load_managed_accounts_from_env() -> set:
    """
    Load the set of account names that are discretionary-managed (e.g. UBS managed strategies).

    Format: MANAGED_ACCOUNTS=account_id1,account_id2,...
    Partial substring match is supported (e.g. "JT Value Stock" matches "(BX 49690) JT Value Stock")

    Returns: set of raw account IDs/substrings to match against
    """
    import os
    raw = os.environ.get('MANAGED_ACCOUNTS', '').strip()
    if not raw:
        return set()
    managed = {a.strip() for a in raw.split(',') if a.strip()}
    if managed:
        logger.info(f"Loaded managed accounts from environment: {managed}")
    return managed


def _is_managed_account(account_name: Optional[str], managed_accounts: set) -> bool:
    """Return True if account_name matches any entry in managed_accounts (substring match)."""
    if not account_name or not managed_accounts:
        return False
    n = account_name.strip()
    return any(ma in n or n in ma for ma in managed_accounts)


def _load_account_labels_from_env() -> Dict[str, str]:
    """
    Load account display-name overrides from environment variables.

    Format: ACCOUNT_LABELS=account_id:display_name,account_id2:display_name2
    Example:
      ACCOUNT_LABELS=(BX 75135):Fidelity 401K,(BX 48162) JT Brokerage:Joint Brokerage

    Returns: Dict mapping raw account ID (as it appears in CSV) -> friendly display name
    """
    import os
    raw = os.environ.get('ACCOUNT_LABELS', '').strip()
    if not raw:
        return {}
    labels: Dict[str, str] = {}
    for pair in raw.split(','):
        if ':' not in pair:
            continue
        acct_id, _, display = pair.partition(':')
        acct_id = acct_id.strip()
        display = display.strip()
        if acct_id and display:
            labels[acct_id] = display
    if labels:
        logger.info(f"Loaded account labels from environment: {labels}")
    return labels


def _infer_financial_type(account_name: str, explicit_type: Optional[str] = None) -> str:
    """Infer account financial type from name or explicit override."""
    if explicit_type:
        return explicit_type.lower().replace(' ', '_')
    n = (account_name or '').upper()
    if 'ROTH' in n:
        return 'roth_ira'
    if 'SEP' in n:
        return 'sep_ira'
    if 'IRA' in n:
        return 'ira'
    if '401K' in n or '401(K)' in n or '401 K' in n or 'RETIREMENT' in n:
        return '401k'
    if 'FIDELITY' in n:
        return '401k'   # Fidelity accounts are commonly 401K in this portfolio
    if 'BROKERAGE' in n:
        return 'brokerage'
    if 'MUNI' in n or 'BOND' in n:
        return 'taxable'
    return 'taxable'


def _is_ubs_managed_strategy(account_name: Optional[str]) -> bool:
    """Return True if the account name looks like a UBS discretionary managed strategy."""
    if not account_name:
        return False
    n = account_name.upper()
    # UBS managed strategy naming patterns
    return any(kw in n for kw in (
        'VALUE STOCK', 'GROWTH STOCK', 'GLOBAL STK', 'GLOBAL STOCK',
        'MANAGED', 'DISCRETIONARY', 'ADVISORY', 'STRATEGY',
    ))


def _load_sector_cache() -> Dict[str, dict]:
    """Load security info cache. Migrates old string-only sector format to {sector, security_type} dicts."""
    try:
        if _SECTOR_CACHE_FILE.exists():
            with open(_SECTOR_CACHE_FILE) as f:
                data = json.load(f)
            migrated = {}
            needs_save = False
            for k, v in data.items():
                if isinstance(v, str):
                    migrated[k] = {'sector': v, 'security_type': 'equity'}
                    needs_save = True
                else:
                    migrated[k] = v
            if needs_save:
                with open(_SECTOR_CACHE_FILE, 'w') as f:
                    json.dump(migrated, f)
            return migrated
    except Exception:
        pass
    return {}


def _save_sector_cache(cache: Dict[str, dict]) -> None:
    try:
        _SECTOR_CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(_SECTOR_CACHE_FILE, 'w') as f:
            json.dump(cache, f)
    except Exception:
        pass


def _fetch_security_info(sym: str) -> Tuple[str, str, str]:
    """Return (symbol, sector, security_type) from yfinance; defaults on any error.

    security_type is one of: 'etf', 'mutual_fund', 'equity'.
    ETF and mutual fund positions cannot have their underlying holdings adjusted
    independently — the whole fund must be bought or sold.
    """
    try:
        import yfinance as yf
        info = yf.Ticker(sym).info
        sector = info.get('sector') or 'Unknown'
        qt = (info.get('quoteType') or 'EQUITY').upper()
        if qt == 'ETF':
            security_type = 'etf'
        elif qt in ('MUTUALFUND', 'FUND'):
            security_type = 'mutual_fund'
        else:
            security_type = 'equity'
        return sym, sector, security_type
    except Exception:
        return sym, 'Unknown', 'equity'


def _fetch_security_info_batch(symbols: List[str], max_workers: int = 8, timeout: int = 30) -> Dict[str, Tuple[str, str]]:
    """Parallel security info lookup. Returns {sym: (sector, security_type)}."""
    result: Dict[str, Tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_fetch_security_info, sym): sym for sym in symbols}
        for fut in as_completed(futures, timeout=timeout):
            try:
                sym, sector, security_type = fut.result()
                result[sym] = (sector, security_type)
            except Exception:
                result[futures[fut]] = ('Unknown', 'equity')
    return result


def _build_compact_holdings(equity_data: dict, bond_data: dict, cash_data: dict,
                             margin_data: dict, total_value: float,
                             cdm_summary: dict, output_file: str) -> dict:
    """Build a compact holdings summary for LLM injection (~8-15KB vs 290KB full CDM).

    Returns a dict with portfolio totals, top equity positions, sector weights,
    and bond/cash summary — sufficient for LLM analysis without the full CDM payload.
    """
    from datetime import date as _date

    equity_value  = sum(h.value for h in equity_data.values())
    bond_value    = sum(h.value for h in bond_data.values())
    cash_value    = sum(h.value for h in cash_data.values())
    margin_value  = sum(h.value for h in margin_data.values())
    net_value     = total_value - abs(margin_value)

    # Equity positions sorted by market value descending
    eq_sorted = sorted(equity_data.values(), key=lambda h: h.value, reverse=True)

    # Top 25 equity positions
    top_equity = []
    for h in eq_sorted[:25]:
        weight_pct = round(h.value / total_value * 100, 2) if total_value else 0
        _display_sector = (
            "ETF / Diversified" if (h.is_etf or h.security_type == 'etf')
            else (h.sector or "Unknown")
        )
        entry = {
            "symbol":     h.symbol,
            "sector":     _display_sector,
            "value":      round(h.value, 2),
            "weight_pct": weight_pct,
            "gl_pct":     round(h.unrealized_gain_loss_pct * 100, 2),
            "type":       h.security_type or "equity",
        }
        if h.espp_status:
            entry["espp_status"] = h.espp_status
        top_equity.append(entry)

    # Sector concentration — total and non-ESPP breakdown
    sector_totals: dict = {}
    sector_totals_non_espp: dict = {}
    espp_value_by_sector: dict = {}
    for h in equity_data.values():
        # ETFs and ETF-like diversified positions get a distinct sector label
        if h.is_etf or h.security_type == 'etf':
            sec = "ETF / Diversified"
        else:
            sec = h.sector or "Unknown"
        sector_totals[sec] = sector_totals.get(sec, 0.0) + h.value
        if h.espp_status:
            espp_value_by_sector[sec] = espp_value_by_sector.get(sec, 0.0) + h.value
        else:
            sector_totals_non_espp[sec] = sector_totals_non_espp.get(sec, 0.0) + h.value

    sector_weights = {
        sec: round(val / equity_value * 100, 1)
        for sec, val in sorted(sector_totals.items(), key=lambda x: x[1], reverse=True)
    } if equity_value else {}

    # Non-ESPP sector weights (organic portfolio concentration)
    non_espp_equity_value = sum(sector_totals_non_espp.values())
    sector_weights_ex_espp = {
        sec: round(val / non_espp_equity_value * 100, 1)
        for sec, val in sorted(sector_totals_non_espp.items(), key=lambda x: x[1], reverse=True)
    } if non_espp_equity_value else {}

    # ESPP value by sector (for concentration context)
    espp_sector_pct = {
        sec: round(val / equity_value * 100, 1)
        for sec, val in sorted(espp_value_by_sector.items(), key=lambda x: x[1], reverse=True)
    } if equity_value and espp_value_by_sector else {}

    # Top 5 bonds by value
    bd_sorted = sorted(bond_data.values(), key=lambda h: h.value, reverse=True)
    top_bonds = []
    for h in bd_sorted[:5]:
        top_bonds.append({
            "name":       h.bond_name or h.symbol or "Unknown",
            "cusip":      h.cusip or "",
            "value":      round(h.value, 2),
            "weight_pct": round(h.value / total_value * 100, 2) if total_value else 0,
            "coupon":     h.coupon_rate,
            "maturity":   str(h.maturity_date) if h.maturity_date else None,
        })

    compact = {
        "disclaimer":          "EDUCATIONAL ANALYSIS - NOT INVESTMENT ADVICE",
        "is_investment_advice": False,
        "_note":               "Compact summary for LLM analysis. Full CDM data is at output_file for downstream scripts only — do NOT read that file for analysis.",
        "as_of":               str(_date.today()),
        "summary": {
            "total_value":      round(total_value, 2),
            "net_value":        round(net_value, 2),
            "equity_value":     round(equity_value, 2),
            "bond_value":       round(bond_value, 2),
            "cash_value":       round(cash_value, 2),
            "margin_value":     round(margin_value, 2),
            "equity_pct":       round(equity_value / total_value * 100, 1) if total_value else 0,
            "bond_pct":         round(bond_value / total_value * 100, 1) if total_value else 0,
            "cash_pct":         round(cash_value / total_value * 100, 1) if total_value else 0,
            "position_count":   {
                "equity": len(equity_data),
                "bond":   len(bond_data),
                "cash":   len(cash_data),
            },
            "unrealized_gl":    round(
                cdm_summary.get("totalUnrealizedGainLoss", 0) or 0, 2
            ),
            "unrealized_gl_pct": round(
                cdm_summary.get("totalUnrealizedGainLossPct", 0) or 0, 2
            ),
        },
        "top_equity":    top_equity,
        "sector_weights": sector_weights,
        "top_bonds":     top_bonds,
        "remaining_equity_count": max(0, len(equity_data) - 25),
        "output_file":   output_file,
    }
    # Include ESPP-adjusted sector breakdown when ESPP positions are present
    if espp_sector_pct:
        compact["sector_weights_ex_espp"] = sector_weights_ex_espp
        compact["espp_sector_pct"] = espp_sector_pct

    # Account-level breakdown: name → {financial_type, managed, value, position_count}
    _acct_totals: dict = {}
    for h in equity_data.values():
        _acct_name = h.account or 'Unknown'
        if _acct_name not in _acct_totals:
            _ft = _infer_financial_type(_acct_name, h.account_type)
            _is_mgd = (h.managed_status == 'discretionary') or _is_ubs_managed_strategy(_acct_name)
            _acct_totals[_acct_name] = {
                'financial_type': _ft,
                'managed': _is_mgd,
                'value': 0.0,
                'position_count': 0,
            }
        _acct_totals[_acct_name]['value']          += h.value
        _acct_totals[_acct_name]['position_count'] += 1
    if _acct_totals:
        compact["accounts"] = {
            name: {
                'financial_type': data['financial_type'],
                'managed': data['managed'],
                'value': round(data['value'], 2),
                'position_count': data['position_count'],
                'weight_pct': round(data['value'] / equity_value * 100, 1) if equity_value else 0,
            }
            for name, data in sorted(_acct_totals.items(), key=lambda x: x[1]['value'], reverse=True)
        }

    return compact


class PortfolioFetcher:
    def __init__(self):
        self.equity_data = {}
        self.bond_data = {}
        self.cash_data = {}
        self.margin_data = {}
        self.errors = []

    def _normalize_broker_columns(self, df: pl.DataFrame) -> pl.DataFrame:
        """
        Normalize broker-format columns (UBS and similar) to InvestorClaw standard schema.
        Handles uppercase column names, monetary strings, N/A values, and infers asset_type.
        Pure Polars — no pandas.
        """
        # 1. Lowercase and sanitize column names
        df = df.rename({
            c: c.lower().strip()
                .replace(' ', '_').replace('/', '_').replace('%', 'pct')
                .replace('$', 'usd').replace('(', '').replace(')', '')
            for c in df.columns
        })

        # 2. Map broker column names → standard schema names
        col_aliases = {
            'quantity':                        'shares',
            'value':                           'market_value',
            'yield':                           'coupon_rate',
            'unrealized_gain_loss_usd':        'unrealized_gain_loss',
            'unrealized_gain_loss_pct':        'unrealized_gain_loss_pct',
            'as_of':                           'price_date',
            'change_in_price':                 'price_change',
            'change_in_value':                 'value_change',
            'percent_change':                  'change_pct',
            'percent_of_portfolio':            'portfolio_pct',
            'account_number':                  'account',
        }
        rename_map = {k: v for k, v in col_aliases.items() if k in df.columns and v not in df.columns}
        if rename_map:
            df = df.rename(rename_map)

        # 3. Clean monetary columns: strip $, commas, whitespace → Float64
        for col in ('market_value', 'price', 'unrealized_gain_loss', 'coupon_rate', 'shares'):
            if col in df.columns:
                df = df.with_columns(
                    pl.col(col).cast(pl.Utf8)
                      .str.replace_all(r'[$,\s]', '')
                      .cast(pl.Float64, strict=False)
                      .alias(col)
                )

        # 4. Normalize symbol: blank / N/A / nan / None → null
        if 'symbol' in df.columns:
            df = df.with_columns(
                pl.when(
                    pl.col('symbol').cast(pl.Utf8).str.strip_chars()
                      .str.to_lowercase().is_in(['n/a', 'nan', 'none', ''])
                )
                .then(pl.lit(None, dtype=pl.Utf8))
                .otherwise(pl.col('symbol').cast(pl.Utf8).str.strip_chars())
                .alias('symbol')
            )

        # 5. Normalize cusip: blank / N/A / nan / None → null
        if 'cusip' in df.columns:
            df = df.with_columns(
                pl.when(
                    pl.col('cusip').cast(pl.Utf8).str.strip_chars()
                      .str.to_lowercase().is_in(['n/a', 'nan', 'none', ''])
                )
                .then(pl.lit(None, dtype=pl.Utf8))
                .otherwise(pl.col('cusip').cast(pl.Utf8).str.strip_chars())
                .alias('cusip')
            )

        # 6. Add 'name' alias from 'description' if missing (bond handler needs it)
        if 'name' not in df.columns and 'description' in df.columns:
            df = df.with_columns(pl.col('description').alias('name'))

        # 7. Infer asset_type for rows where it is absent OR null.
        # When the column exists (e.g. added manually to a broker CSV for non-standard
        # holdings like mutual funds / 401k CITs) but some rows lack a value, fill the
        # nulls using the standard heuristics so existing broker rows still classify
        # correctly.
        _has_asset_type_col = 'asset_type' in df.columns
        _has_nulls = (
            _has_asset_type_col and
            df.select(pl.col('asset_type').is_null().any()).item()
        )
        if not _has_asset_type_col or _has_nulls:
            has_cusip = 'cusip' in df.columns
            has_desc  = 'description' in df.columns

            # Bond heuristic: null symbol + 9-char alphanumeric CUSIP
            bond_by_cusip = (
                pl.col('symbol').is_null() &
                pl.col('cusip').is_not_null() &
                pl.col('cusip').str.len_chars().eq(9) &
                pl.col('cusip').str.contains(r'^[A-Za-z0-9]+$')
            ) if has_cusip else pl.lit(False)

            # Cash heuristic: description matches cash-like keywords, OR null symbol + null CUSIP
            _cash_keywords = (
                r'cash|credit balance|trade date balance|sweep|deposit account|'
                r'insured|money market|bank usa|sweep program|interest|dividend'
            )
            cash_by_desc = (
                pl.col('description').cast(pl.Utf8).str.to_lowercase()
                  .str.contains(_cash_keywords)
            ) if has_desc else pl.lit(False)
            # Any row with no equity symbol AND no bond CUSIP is cash
            cash_by_null = (
                pl.col('symbol').is_null() &
                (pl.col('cusip').is_null() if has_cusip else pl.lit(True))
            )

            # Municipal bond sub-type: government/school/utility keywords in description
            muni_desc = (
                pl.col('description').cast(pl.Utf8).str.to_lowercase()
                  .str.contains(
                    r'muni|municipal|city |cnty|county|st |state |school|univ|transit|'
                    r'airport|water|sewer|revenue|authority|govt|government'
                  )
            ) if has_desc else pl.lit(True)  # default to muni if no description

            _inferred = (
                pl.when(cash_by_desc | cash_by_null)
                  .then(pl.lit('cash'))
                .when(bond_by_cusip & muni_desc)
                  .then(pl.lit('municipal_bond'))
                .when(bond_by_cusip)
                  .then(pl.lit('bond'))
                .otherwise(pl.lit('equity'))
            )

            if _has_asset_type_col:
                # Column exists but has null rows — fill only the nulls
                df = df.with_columns(
                    pl.when(pl.col('asset_type').is_null())
                      .then(_inferred)
                      .otherwise(pl.col('asset_type'))
                      .alias('asset_type')
                )
            else:
                df = df.with_columns(_inferred.alias('asset_type'))

            bond_count = df.filter(
                pl.col('asset_type').is_in(['bond', 'municipal_bond'])
            ).height
            logger.info(f"Inferred asset_type: {bond_count} bond/muni rows detected via CUSIP heuristic")

        # 8. Fill null shares from market_value for bonds (bonds are quoted per position value)
        if 'market_value' in df.columns and 'shares' in df.columns:
            is_bond = pl.col('asset_type').str.to_lowercase().str.contains('bond')
            df = df.with_columns(
                pl.when(is_bond & pl.col('shares').is_null())
                  .then(pl.lit(1.0))
                  .otherwise(pl.col('shares'))
                  .alias('shares')
            )
            # Use market_value as price for bonds when price is null
            if 'price' in df.columns:
                df = df.with_columns(
                    pl.when(is_bond & pl.col('price').is_null())
                      .then(pl.col('market_value'))
                      .otherwise(pl.col('price'))
                      .alias('price')
                )

        return df

    @staticmethod
    def _read_xls_to_polars(input_file: str) -> pl.DataFrame:
        """
        Read a legacy .xls file using xlrd directly — no pandas involved.
        Builds a native Polars DataFrame from xlrd cell values.
        Handles UBS HOLDINGS header row automatically.
        """
        import xlrd

        book  = xlrd.open_workbook(input_file)
        sheet = book.sheet_by_index(0)

        if sheet.nrows == 0:
            return pl.DataFrame()

        # Detect and skip UBS "HOLDINGS" metadata row (row 0 cell 0 == "HOLDINGS")
        first_cell = str(sheet.cell_value(0, 0)).strip().upper()
        data_start = 1 if first_cell == "HOLDINGS" else 0

        if sheet.nrows <= data_start:
            return pl.DataFrame()

        # Row at data_start is the column header
        raw_headers = [
            str(sheet.cell_value(data_start, c)).strip()
            for c in range(sheet.ncols)
        ]
        # Remove empty trailing headers
        while raw_headers and not raw_headers[-1]:
            raw_headers.pop()
        n_cols = len(raw_headers)

        # Build rows as list[list] — xlrd returns mixed Python types; keep as str for safety
        _NULL_STRINGS = {"", "n/a", "nan", "none", "#n/a", "-"}
        rows: List[List] = []
        for r in range(data_start + 1, sheet.nrows):
            row = []
            for c in range(n_cols):
                cell = sheet.cell(r, c)
                val  = cell.value
                if cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    row.append(None)
                elif cell.ctype == xlrd.XL_CELL_NUMBER:
                    row.append(val)   # keep as float
                elif cell.ctype == xlrd.XL_CELL_TEXT:
                    s = val.strip()
                    row.append(None if s.lower() in _NULL_STRINGS else s)
                else:
                    s = str(val).strip()
                    row.append(None if s.lower() in _NULL_STRINGS else s)
            rows.append(row)

        # Build column lists
        col_data: Dict[str, List] = {h: [] for h in raw_headers}
        for row in rows:
            for i, h in enumerate(raw_headers):
                col_data[h].append(row[i] if i < len(row) else None)

        # Build Polars Series per column: numeric columns stay numeric,
        # mixed/text columns are uniformly stringified (handles XLS mixed-type cells)
        series_list: List[pl.Series] = []
        for h, vals in col_data.items():
            non_null = [v for v in vals if v is not None]
            all_numeric = all(isinstance(v, (int, float)) for v in non_null) if non_null else False
            if all_numeric:
                series_list.append(pl.Series(h, vals, dtype=pl.Float64))
            else:
                # Stringify everything — _normalize_broker_columns will cast numeric cols
                str_vals = [
                    None if v is None else
                    str(int(v)) if isinstance(v, float) and v == int(v) else
                    str(v).strip() if not isinstance(v, float) else str(v)
                    for v in vals
                ]
                series_list.append(pl.Series(h, str_vals, dtype=pl.String))

        return pl.DataFrame(series_list)

    def load_portfolio_file(self, input_file: str) -> pl.DataFrame:
        """Load portfolio from CSV or XLS/XLSX file.
        .xls  → xlrd direct read → native Polars (no pandas)
        .xlsx → polars.read_excel with openpyxl
        .csv  → polars.read_csv
        All column normalization is pure Polars."""
        try:
            ext = Path(input_file).suffix.lower()
            if ext == '.xls':
                df = self._read_xls_to_polars(input_file)
            elif ext == '.xlsx':
                # Polars can read .xlsx natively via openpyxl (no pandas)
                try:
                    peek = pl.read_excel(input_file, read_options={"n_rows": 1, "has_header": False})
                    skip = 1 if str(peek[0, 0]).upper().startswith("HOLDINGS") else 0
                except Exception:
                    skip = 0
                df = pl.read_excel(
                    input_file,
                    read_options={"skip_rows": skip},
                )
            else:
                # Pure Polars CSV read with UBS header auto-detection
                with open(input_file, 'rb') as _f:
                    first_line = _f.readline().decode('utf-8', errors='replace').strip().strip('"')
                skip_rows = 1 if first_line.upper().startswith('HOLDINGS') else 0
                df = pl.read_csv(
                    input_file,
                    skip_rows=skip_rows,
                    null_values=['N/A', 'nan', 'None', 'NaN', ''],
                    infer_schema_length=500,
                )

            # Normalize broker columns → standard schema (pure Polars)
            df = self._normalize_broker_columns(df)

            logger.info(f"Loaded {len(df)} holdings from {input_file}")
            return df
        except FileNotFoundError:
            logger.error(f"Portfolio file not found: {input_file}")
            raise
        except Exception as e:
            logger.error(f"Error loading portfolio file: {e}")
            raise

    def validate_holdings_data(self, df: pl.DataFrame) -> pl.DataFrame:
        """Validate required columns exist after normalization and add missing columns."""
        has_symbol   = 'symbol' in df.columns or 'cusip' in df.columns
        has_quantity = 'shares' in df.columns or 'market_value' in df.columns
        has_type     = 'asset_type' in df.columns  # always present after _normalize_broker_columns

        if not (has_symbol and has_quantity and has_type):
            missing = []
            if not has_symbol:   missing.append('symbol or cusip')
            if not has_quantity: missing.append('shares or market_value')
            if not has_type:     missing.append('asset_type')
            raise ValueError(f"Missing required columns after normalization: {', '.join(missing)}")

        # Add purchase_price if missing (use current price as fallback)
        if 'purchase_price' not in df.columns:
            if 'price' in df.columns:
                df = df.with_columns(pl.col('price').alias('purchase_price'))
                logger.warning("Using current 'price' as purchase_price (historical data unavailable)")
            else:
                raise ValueError("Missing both 'purchase_price' and 'price' columns")

        # Add purchase_date if missing (use N/A as sentinel)
        if 'purchase_date' not in df.columns:
            df = df.with_columns(pl.lit('N/A').alias('purchase_date'))
            logger.warning("purchase_date not available in broker export (set to N/A)")

        return df

    def fetch_equity_holdings(self, equity_df: pl.DataFrame) -> Dict:
        """Fetch current prices for equity positions.

        By default (INVESTOR_CLAW_REFRESH_PRICES=true), live prices are always fetched
        from the configured price provider.  Broker-supplied prices from the CSV are kept
        as a fallback for when the provider fails.

        Set INVESTOR_CLAW_REFRESH_PRICES=false to use broker-snapshot prices as-is
        (older behaviour — useful when the CSV is same-day and you want broker fidelity).

        ESPP Detection:
        - On first run: Displays detected symbols and accounts (for user to identify ESPP)
        - On subsequent runs: Loads ESPP symbol+account mapping from ESPP_HOLDINGS env var
        """
        from providers.price_provider import PriceProvider

        # Load ESPP symbol+account configuration from environment (if set during discovery)
        espp_holdings = _load_espp_holdings_from_env()

        # Load account display-name overrides (e.g. (BX 75135) → Fidelity 401K)
        _account_labels = _load_account_labels_from_env()

        # Load discretionary-managed account identifiers
        _managed_accounts = _load_managed_accounts_from_env()

        # On first portfolio load, run account detection to prompt user
        if not espp_holdings:
            _detect_espp_accounts(equity_df)

        # Aggregate rows by symbol (single_investor) or by symbol+account (fa_professional).
        # Multi-account portfolios (e.g. UBS) list the same equity symbol once per account.
        # In single_investor mode: sum across all accounts → one aggregate position per ticker.
        # In fa_professional mode: keep per-account positions so the FA sees each account separately.
        try:
            from config.config_loader import is_single_investor_mode as _is_single_inv
            _collapse_by_symbol = _is_single_inv()
        except Exception:
            _collapse_by_symbol = True  # default: collapse

        from collections import defaultdict
        _agg: dict = defaultdict(
            lambda: {'market_value': 0.0, 'shares': 0.0, 'price': None, '_row': None,
                     '_asset_type': None, '_proxy': None, '_account_type': None, '_real_sym': None,
                     '_espp_account': None, '_espp_shares': 0.0, '_labeled_account': None}
        )
        for _row in equity_df.to_dicts():
            _sym = _row.get('symbol')
            if _sym is None:
                continue
            _sym = _sym.strip()
            _acct = (_row.get('account') or _row.get('source') or 'default')
            if isinstance(_acct, str):
                _acct = _acct.strip()
            # Apply account label override (e.g. "(BX 75135)" → "Fidelity 401K")
            _acct = _account_labels.get(_acct, _acct)
            # Collapse key: by symbol only (single investor) or symbol+account (FA)
            _agg_key = _sym if _collapse_by_symbol else f"{_sym}__{_acct}"
            _mv = _row.get('market_value')
            _sh = _row.get('shares')
            try:
                _mv_f = float(_mv) if _mv is not None else 0.0
            except (ValueError, TypeError):
                _mv_f = 0.0
            try:
                _sh_f = float(_sh) if _sh is not None else 0.0
            except (ValueError, TypeError):
                _sh_f = 0.0
            _agg[_agg_key]['market_value'] += _mv_f
            _agg[_agg_key]['shares']       += _sh_f
            if _agg[_agg_key]['price'] is None:
                _agg[_agg_key]['price'] = _row.get('price')
            if _agg[_agg_key]['_row'] is None:
                _agg[_agg_key]['_row'] = _row
            if _agg[_agg_key]['_real_sym'] is None:
                _agg[_agg_key]['_real_sym'] = _sym
            if _agg[_agg_key]['_asset_type'] is None:
                _agg[_agg_key]['_asset_type'] = _row.get('asset_type', 'equity')
            if _agg[_agg_key]['_proxy'] is None:
                _raw_proxy = _row.get('proxy_symbol') or _row.get('proxy')
                _agg[_agg_key]['_proxy'] = _raw_proxy.strip() if _raw_proxy else None
            if _agg[_agg_key]['_account_type'] is None:
                _agg[_agg_key]['_account_type'] = _row.get('account_type')
            # Store labeled account name (first seen wins for non-ESPP override)
            if _agg[_agg_key]['_labeled_account'] is None:
                _agg[_agg_key]['_labeled_account'] = _acct
            # Track ESPP account: if ANY row for this symbol is from an ESPP account, record it
            if _agg[_agg_key]['_espp_account'] is None and _is_espp_holding(_sym, _acct, espp_holdings):
                _agg[_agg_key]['_espp_account'] = _acct
                _agg[_agg_key]['_espp_shares'] = _sh_f
            elif _agg[_agg_key]['_espp_account'] == _acct:
                _agg[_agg_key]['_espp_shares'] += _sh_f

        # Build row_map with aggregated values (one entry per agg key)
        row_map: dict = {}
        for _agg_key, _data in _agg.items():
            _base = dict(_data['_row'])          # copy first row for non-aggregated fields
            _base['market_value'] = _data['market_value']
            _base['shares']       = _data['shares']
            if _data['price'] is not None:
                _base['price'] = _data['price']
            _base['_asset_type']   = _data['_asset_type'] or 'equity'
            _base['_proxy']        = _data['_proxy']
            _base['_account_type'] = _data['_account_type']
            _base['_real_sym']     = _data['_real_sym']
            # Apply labeled account name (overrides raw CSV account ID)
            if _data['_labeled_account']:
                _base['account'] = _data['_labeled_account']
            # Propagate ESPP account: prefer the ESPP-matching account over first-seen account
            if _data['_espp_account']:
                _base['account'] = _data['_espp_account']
                _base['_espp_shares'] = _data['_espp_shares']
            row_map[_agg_key] = _base

        # Ordered key list (preserves XLS order, deduplicates)
        _seen: set = set()
        symbols: list = []  # list of agg_keys (sym in single mode, sym__acct in FA mode)
        for _row_d in equity_df.to_dicts():
            _s = _row_d.get('symbol')
            if _s is None:
                continue
            _s = _s.strip()
            _a = (_row_d.get('account') or _row_d.get('source') or 'default')
            if isinstance(_a, str):
                _a = _a.strip()
            _a = _account_labels.get(_a, _a)
            _k = _s if _collapse_by_symbol else f"{_s}__{_a}"
            if _k not in _seen:
                _seen.add(_k)
                symbols.append(_k)

        _mode_label = "single_investor" if _collapse_by_symbol else "fa_professional"
        logger.info(
            f"Fetching data for {len(symbols)} equity positions [{_mode_label}] "
            f"(aggregated from {equity_df.height} rows) via PriceProvider"
        )

        equity_data    = {}
        failed_symbols = []

        # Determine which symbols need a live price fetch.
        # INVESTOR_CLAW_REFRESH_PRICES=true (default): always fetch live prices; broker CSV
        # prices are only used as a fallback when the provider fails.
        # INVESTOR_CLAW_REFRESH_PRICES=false: use broker-snapshot prices as-is (old behaviour).
        import os as _os
        _refresh_prices = _os.environ.get(
            'INVESTOR_CLAW_REFRESH_PRICES', 'true'
        ).strip().lower() not in ('0', 'false', 'no')

        needs_live  = []
        broker_only = {}
        for agg_key in symbols:
            row = row_map.get(agg_key)
            if row is None:
                continue
            sym = row.get('_real_sym') or agg_key  # real ticker (never compound in FA mode)
            mv    = row.get('market_value')
            price = row.get('price')
            try:
                mv    = float(mv)    if mv    is not None else None
                price = float(price) if price is not None else None
            except (ValueError, TypeError):
                mv = price = None

            if mv and mv > 0 and price and price > 0 and not _refresh_prices:
                # Refresh disabled: use broker snapshot price as-is
                broker_only[agg_key] = {'price': price, 'market_value': mv, 'sym': sym}
            elif mv and mv > 0 and price and price > 0:
                # Refresh enabled: store broker data for fallback, queue for live fetch
                broker_only[agg_key] = {'price': price, 'market_value': mv, 'sym': sym}
                needs_live.append(sym)
            elif (row.get('_asset_type') or 'equity') == 'mutual_fund':
                # For mutual funds: prefer proxy live price > broker NAV > purchase_price NAV
                proxy = row.get('_proxy')
                if proxy:
                    needs_live.append(proxy)  # proxy quote mapped back in output loop
                else:
                    _pp = row.get('purchase_price')
                    try:
                        _pp = float(_pp) if _pp is not None else None
                    except (ValueError, TypeError):
                        _pp = None
                    if _pp and _pp > 0:
                        _sh_val = row.get('shares', 0.0)
                        try:
                            _sh_val = float(_sh_val) if _sh_val is not None else 0.0
                        except (ValueError, TypeError):
                            _sh_val = 0.0
                        broker_only[agg_key] = {'price': _pp, 'market_value': _pp * _sh_val, 'sym': sym}
                        logger.info(f"{sym}: using purchase_price=${_pp:.4f} as NAV (mutual fund, no proxy)")
                    else:
                        needs_live.append(sym)
            else:
                needs_live.append(sym)

        if needs_live:
            _mode = "refresh" if _refresh_prices else "no broker price"
            logger.info(f"Live price fetch for {len(needs_live)} symbols ({_mode})")
        if broker_only and not _refresh_prices:
            logger.info(f"Using broker-supplied prices for {len(broker_only)} symbols (refresh disabled)")

        # Batch price fetch for symbols without broker prices (use real tickers, not compound keys)
        quotes: Dict[str, Dict] = {}
        if needs_live:
            try:
                provider = PriceProvider()
                quotes   = provider.get_quotes(list(dict.fromkeys(needs_live)))  # dedup tickers
            except Exception as e:
                logger.error(f"PriceProvider.get_quotes failed: {e}")

        # Merge broker prices into quotes map — only fill gaps where live fetch failed.
        # When _refresh_prices is True, live prices take precedence; broker prices are
        # only used as a fallback for symbols the provider couldn't return.
        for agg_key, bp in broker_only.items():
            real_sym = bp.get('sym', agg_key)
            if real_sym not in quotes or not quotes[real_sym].get('price'):
                quotes[real_sym] = {'price': bp['price'], 'provider': 'broker'}

        # Sector lookup — load from cache, fetch missing symbols in parallel.
        # mutual_fund rows (asset_type == 'mutual_fund') skip yfinance; their security_type
        # is forced from the CSV.  proxy_symbol rows use the proxy for the yfinance lookup.
        _sector_cache = _load_sector_cache()

        # Build effective lookup symbols using real tickers (not compound agg_keys in FA mode).
        _proxy_map: dict = {}  # proxy_sym → agg_key
        _effective_syms: list = []
        _seen_real: set = set()
        for agg_key in symbols:
            row = row_map.get(agg_key, {})
            real_sym = row.get('_real_sym') or agg_key
            if (row.get('_asset_type') or 'equity') == 'mutual_fund':
                continue  # skip yfinance for declared mutual funds
            proxy = row.get('_proxy')
            if proxy:
                _proxy_map[proxy] = agg_key
                if proxy not in _seen_real:
                    _seen_real.add(proxy)
                    _effective_syms.append(proxy)
            elif real_sym not in _seen_real:
                _seen_real.add(real_sym)
                _effective_syms.append(real_sym)

        _missing = [s for s in _effective_syms if s not in _sector_cache]
        if _missing:
            logger.info(f"Fetching security info for {len(_missing)} symbols (cached: {len(_effective_syms)-len(_missing)})")
            try:
                _new_info = _fetch_security_info_batch(_missing)
                _sector_cache.update({
                    sym: {'sector': sec, 'security_type': st}
                    for sym, (sec, st) in _new_info.items()
                })
                _save_sector_cache(_sector_cache)
            except Exception as e:
                logger.warning(f"Security info fetch failed: {e} — using defaults")

        # Build final sector lookup: proxy results map back to real sym (not compound key)
        _sector_lookup = dict(_sector_cache)
        for proxy, orig_key in _proxy_map.items():
            if proxy in _sector_cache:
                orig_real = (row_map.get(orig_key) or {}).get('_real_sym') or orig_key
                _sector_lookup[orig_real] = _sector_cache[proxy]

        for agg_key in symbols:
            try:
                row = row_map.get(agg_key)
                if not row:
                    continue

                sym = row.get('_real_sym') or agg_key  # always the real ticker

                # Use proxy symbol's quote if proxy was set
                _proxy = row.get('_proxy')
                quote = quotes.get(sym) or (quotes.get(_proxy) if _proxy else None)
                # Fallback: if live price failed but broker market_value is present, use broker data
                _broker_mv = row.get('market_value')
                _broker_price = row.get('price')
                try:
                    _broker_mv    = float(_broker_mv)    if _broker_mv    is not None else None
                    _broker_price = float(_broker_price) if _broker_price is not None else None
                except (ValueError, TypeError):
                    _broker_mv = _broker_price = None

                if not quote or not quote.get('price'):
                    if _broker_mv and _broker_mv > 0 and _broker_price and _broker_price > 0:
                        # Use broker values as fallback
                        quote = {'price': _broker_price, 'provider': 'broker_fallback'}
                    else:
                        logger.warning(f"{sym}: no price from PriceProvider or broker")
                        failed_symbols.append(sym)
                        continue

                current_price = float(quote['price'])
                raw_shares    = row.get('shares')
                try:
                    shares = float(raw_shares) if raw_shares is not None else 0.0
                except (ValueError, TypeError):
                    shares = 0.0

                # Broker-supplied market value (e.g., UBS VALUE column)
                mv_raw = row.get('market_value')
                try:
                    market_value_stored = float(mv_raw) if mv_raw is not None else None
                except (ValueError, TypeError):
                    market_value_stored = None

                # When refresh is enabled, always compute value from shares × live price.
                # When refresh is disabled (broker snapshot mode), prefer broker market_value.
                if market_value_stored and market_value_stored > 0 and not _refresh_prices:
                    # Broker snapshot mode: use CSV market value as-is
                    value = market_value_stored
                    if shares == 0:
                        shares = value / current_price if current_price > 0 else 1.0
                elif shares > 0 and current_price > 0:
                    value = shares * current_price
                elif market_value_stored and market_value_stored > 0:
                    # Fallback: use broker value when shares unknown
                    value = market_value_stored
                    if shares == 0:
                        shares = value / current_price if current_price > 0 else 1.0
                else:
                    if shares == 0:
                        shares = 1.0
                    value = shares * current_price

                # Cost basis (Yahoo exports total cost, not per-share)
                cost_basis_total = row.get('cost_basis')
                try:
                    cost_basis_total = float(cost_basis_total) if cost_basis_total is not None else None
                except (ValueError, TypeError):
                    cost_basis_total = None

                raw_pp = row.get('purchase_price')
                try:
                    purchase_price = float(raw_pp) if raw_pp is not None else None
                except (ValueError, TypeError):
                    purchase_price = None

                if not purchase_price or purchase_price == 0:
                    if cost_basis_total and cost_basis_total > 0 and shares > 0:
                        purchase_price = cost_basis_total / shares
                    else:
                        purchase_price = current_price

                purchase_date  = str(row.get('purchase_date', 'N/A'))

                unrealized = value - (shares * purchase_price)
                unreal_pct = ((unrealized / (shares * purchase_price)) * 100
                              if purchase_price > 0 else 0.0)

                _row_asset_type = row.get('_asset_type') or 'equity'
                _sec_info = _sector_lookup.get(sym, {})

                # Mutual fund declared in CSV: force security_type; skip yfinance result
                if _row_asset_type == 'mutual_fund':
                    _security_type = 'mutual_fund'
                    _sector = (row.get('sector') or
                               (_sec_info.get('sector', 'Unknown') if isinstance(_sec_info, dict) else 'Unknown'))
                else:
                    _security_type = (
                        _sec_info.get('security_type', 'equity')
                        if isinstance(_sec_info, dict) else 'equity'
                    )
                    _sector = (_sec_info.get('sector', 'Unknown') if isinstance(_sec_info, dict) else 'Unknown')

                # Determine ESPP and managed-account status
                _account = row.get('account') or row.get('source')
                _espp_status    = 'vested' if _is_espp_holding(sym, _account, espp_holdings) else None
                _managed_status = 'discretionary' if _is_managed_account(_account, _managed_accounts) else None

                # Create Holding object (current CDM-compatible interface).
                # Key is agg_key (sym in single_investor, sym__account in fa_professional).
                # Holding.symbol is always the real ticker regardless of mode.
                equity_data[agg_key] = Holding(
                    symbol=sym,
                    shares=shares,
                    purchase_price=purchase_price,
                    purchase_date=purchase_date,
                    current_price=current_price,
                    market_value=value,
                    sector=_sector,
                    security_type=_security_type,
                    is_etf=_security_type == 'etf',
                    account=_account,
                    account_type=row.get('_account_type'),
                    asset_type=_row_asset_type,
                    data_provider=quote.get('provider', 'unknown'),
                    espp_status=_espp_status,
                    managed_status=_managed_status,
                )
                logger.info(f"{sym}: {shares} shares @ ${current_price:.2f} = ${value:,.2f}")

            except Exception as e:
                logger.error(f"Error processing {agg_key}: {e}")
                failed_symbols.append(sym)

        if failed_symbols:
            self.errors.append(f"Failed to fetch: {', '.join(failed_symbols)}")

        return equity_data

    def fetch_bond_holdings(self, bond_df: pl.DataFrame) -> Dict:
        """Process bond holdings using CUSIP as unique identifier."""
        bond_data = {}

        for row in bond_df.to_dicts():
            try:
                # Debug: Log which bond we're processing
                debug_id = row.get('cusip', row.get('symbol', 'UNKNOWN'))

                # Use CUSIP as primary key for municipal bonds
                cusip = row.get('cusip', row.get('symbol', 'UNKNOWN'))
                if cusip:
                    cusip = str(cusip).strip()
                else:
                    cusip = 'UNKNOWN'

                bond_name = row.get('name', row.get('symbol', 'Bond'))
                # Face amount (par value in dollars)
                shares_val = row.get('shares')
                quantity = float(shares_val) if shares_val is not None else 1.0

                # Broker-format bonds: 'market_value' = actual dollar value (e.g. 65435.5)
                # 'price' = % of par (e.g. 100.67).  Never multiply quantity × market_value.
                market_value_raw = row.get('market_value')
                price_pct_raw    = row.get('price')

                try:
                    market_value_raw = float(market_value_raw) if market_value_raw is not None else None
                except (ValueError, TypeError):
                    market_value_raw = None

                try:
                    price_pct = float(price_pct_raw) if price_pct_raw is not None else None
                except (ValueError, TypeError):
                    price_pct = None

                # Prefer the broker-supplied VALUE column as the authoritative dollar value.
                # Fall back to face × (price%/100) if market_value is absent.
                if market_value_raw is not None and market_value_raw > 0:
                    value         = market_value_raw
                    # Express current_price as $/unit (price% × $100 par / 100)
                    current_price = price_pct if price_pct is not None else (value / quantity if quantity else 100.0)
                else:
                    # price is % of par; value = face × (price/100)
                    current_price = price_pct if price_pct is not None else 100.0
                    value         = quantity * (current_price / 100.0)

                # Get purchase price (fallback to current_price)
                purchase_price = row.get('purchase_price')
                if purchase_price is None:
                    purchase_price = current_price
                else:
                    try:
                        purchase_price = float(purchase_price)
                    except (ValueError, TypeError):
                        purchase_price = current_price

                purchase_date = str(row.get('purchase_date', 'N/A'))

                unrealized = value - (quantity * (purchase_price / 100.0) if market_value_raw is not None else quantity * purchase_price)

                # Coupon rate: prefer CSV column; fall back to parsing from bond name
                # e.g. "ATLANTA GA WTR ... RATE 05.000% MATURES 11/01/28"
                coupon_val = row.get('coupon_rate')
                try:
                    coupon_rate = float(coupon_val) if coupon_val is not None else 0.0
                except (ValueError, TypeError):
                    coupon_rate = 0.0
                if coupon_rate == 0.0 and bond_name:
                    m = re.search(r'\bRATE\s+(\d+\.?\d*)\s*%', str(bond_name), re.IGNORECASE)
                    if not m:
                        m = re.search(r'\b(\d+\.\d+)\s*%', str(bond_name))
                    if m:
                        coupon_rate = float(m.group(1))

                # Maturity date: prefer CSV column; fall back to parsing from bond name
                maturity_raw = str(row.get('maturity_date', '') or '')
                if maturity_raw in ('', 'N/A', 'None', 'nan') and bond_name:
                    m = re.search(r'MATURES?\s+(\d{1,2}/\d{1,2}/\d{2,4})', str(bond_name), re.IGNORECASE)
                    maturity_raw = m.group(1) if m else 'N/A'

                # Create Holding object for bond (current CDM-compatible interface)
                bond_data[cusip] = Holding(
                    symbol=cusip,
                    asset_type='municipal_bond',
                    shares=quantity,
                    current_price=float(current_price),
                    purchase_price=purchase_price,
                    purchase_date=purchase_date,
                    sector='Municipal Bonds',
                    cusip=cusip,
                    bond_name=bond_name,
                    coupon_rate=coupon_rate,
                    maturity_date=maturity_raw,
                    market_value=float(value),
                )
                logger.info(f"{cusip} ({bond_name}): {quantity} bonds @ ${current_price:.2f} = ${value:,.2f}")

            except Exception as e:
                logger.error(f"Error processing bond {row.get('cusip', row.get('symbol', 'unknown'))}: {e}")
                self.errors.append(f"Bond error: {e}")

        return bond_data

    def fetch_cash_holdings(self, cash_df: pl.DataFrame) -> Dict:
        """Process cash and cash-equivalent holdings."""
        cash_data = {}

        for idx, row in enumerate(cash_df.to_dicts()):
            try:
                # Symbol may be null for broker cash/sweep rows — fall back to description
                sym = row.get('symbol')
                desc = row.get('description', row.get('name', ''))
                account_name = sym.strip() if sym else (str(desc).strip() or f"cash_{idx}")

                # For broker-format rows, value is in market_value (VALUE column).
                # shares (QUANTITY) is null for cash items in UBS format.
                mv = row.get('market_value')
                shares_val = row.get('shares')
                try:
                    amount = float(mv) if mv is not None else float(shares_val) if shares_val is not None else 0.0
                except (ValueError, TypeError):
                    amount = 0.0

                interest_rate_raw = row.get('coupon_rate', row.get('purchase_price'))
                try:
                    interest_rate = float(interest_rate_raw) / 100 if interest_rate_raw is not None else 0.0
                except (ValueError, TypeError):
                    interest_rate = 0.0

                # Use a unique key (description may repeat for multiple sweep accounts)
                key = f"{account_name}_{idx}" if account_name in cash_data else account_name
                # Create Holding object for cash (current CDM-compatible interface)
                cash_data[key] = Holding(
                    symbol=sym or account_name,
                    asset_type='cash',
                    shares=1.0,
                    current_price=float(amount),
                    purchase_price=float(amount),
                    purchase_date='N/A',
                    sector='Cash',
                    name=str(desc)[:80],
                    interest_rate=float(interest_rate),
                    market_value=float(amount),
                )
                logger.info(f"{key}: ${amount:,.2f} (rate: {interest_rate*100:.2f}%)")

            except Exception as e:
                logger.error(f"Error processing cash account idx={idx}: {e}")
                self.errors.append(f"Cash error: {e}")

        return cash_data

    def fetch_margin_holdings(self, margin_df: pl.DataFrame) -> Dict:
        """Process margin loan holdings."""
        margin_data = {}

        for row in margin_df.to_dicts():
            try:
                loan_id = row['symbol'].strip()
                principal = float(row['shares'])
                interest_rate = float(row['purchase_price']) / 100  # Convert to decimal

                # Calculate interest accrued (assume annual)
                interest_accrued = principal * interest_rate
                total_debt = principal + interest_accrued

                # Create Holding object for margin debt (current CDM-compatible interface)
                margin_data[loan_id] = Holding(
                    symbol=loan_id,
                    asset_type='margin',
                    shares=1.0,
                    current_price=float(-total_debt),
                    purchase_price=float(-principal),
                    purchase_date='N/A',
                    sector='Margin Debt',
                    interest_rate=float(interest_rate),
                    interest_accrued=float(interest_accrued),
                    market_value=float(-total_debt),
                )
                logger.info(f"Margin {loan_id}: Principal ${principal:,.2f} @ {interest_rate*100:.2f}% = Total ${total_debt:,.2f}")

            except Exception as e:
                logger.error(f"Error processing margin {row.get('symbol', 'unknown')}: {e}")
                self.errors.append(f"Margin error: {e}")

        return margin_data

    def _convert_to_cdm_portfolio(self, equity_data, bond_data, cash_data,
                                   equity_value, bond_value, cash_value, total_value) -> CDMPortfolioResult:
        """Convert holdings to FINOS CDM-compliant Portfolio format.

        Creates CDM Position objects for each holding, then wraps in Portfolio/PortfolioState
        with aggregation parameters and summary statistics.
        """
        positions = []

        # Convert equity holdings to CDM Positions.
        # holding.symbol is always the real ticker (never a compound agg_key from FA mode).
        for _key, holding in equity_data.items():
            pos = Position(
                product=Product(
                    product_identifier=ProductIdentifier(
                        identifier_type="TICKER",
                        identifier=holding.symbol,
                    )
                ),
                asset=Asset(
                    product_identifier=ProductIdentifier(
                        identifier_type="TICKER",
                        identifier=holding.symbol,
                    ),
                    security_type="Equity",
                    asset_class="Stocks",
                    security_name=holding.symbol,
                    sector=holding.sector,
                ),
                price_quantity=PriceQuantity(
                    quantity=Quantity(amount=holding.shares, unit="shares"),
                    current_price=Price(amount=holding.current_price, currency="USD"),
                    cost_basis_price=Price(amount=holding.purchase_price, currency="USD"),
                ),
                market_value=holding.value,
                cost_basis=holding.cost_basis,
                unrealized_gain_loss=holding.unrealized_gain_loss,
                unrealized_gain_loss_pct=holding.unrealized_gain_loss_pct,
            )
            positions.append(pos)

        # Convert bond holdings to CDM Positions
        for cusip, holding in bond_data.items():
            pos = Position(
                product=Product(
                    product_identifier=ProductIdentifier(
                        identifier_type="CUSIP",
                        identifier=cusip,
                    )
                ),
                asset=Asset(
                    product_identifier=ProductIdentifier(
                        identifier_type="CUSIP",
                        identifier=cusip,
                    ),
                    security_type="Bond",
                    asset_class="Bonds",
                    security_name=holding.bond_name or cusip,
                    sector=holding.sector,
                    cusip=cusip,
                ),
                price_quantity=PriceQuantity(
                    quantity=Quantity(amount=holding.shares, unit="units"),
                    current_price=Price(amount=holding.current_price, currency="USD"),
                    cost_basis_price=Price(amount=holding.purchase_price, currency="USD"),
                ),
                market_value=holding.value,
                cost_basis=holding.cost_basis,
                unrealized_gain_loss=holding.unrealized_gain_loss,
                unrealized_gain_loss_pct=holding.unrealized_gain_loss_pct,
            )
            positions.append(pos)

        # Convert cash holdings to CDM Positions
        for account, holding in cash_data.items():
            pos = Position(
                product=Product(
                    product_identifier=ProductIdentifier(
                        identifier_type="ACCOUNT",
                        identifier=account,
                    )
                ),
                asset=Asset(
                    product_identifier=ProductIdentifier(
                        identifier_type="ACCOUNT",
                        identifier=account,
                    ),
                    security_type="Cash",
                    asset_class="Cash",
                    security_name=f"Cash: {account}",
                ),
                price_quantity=PriceQuantity(
                    quantity=Quantity(amount=holding.shares, unit="USD"),
                    current_price=Price(amount=1.0, currency="USD"),
                    cost_basis_price=Price(amount=1.0, currency="USD"),
                ),
                market_value=holding.value,
                cost_basis=holding.value,  # Cash has no gain/loss
                unrealized_gain_loss=0.0,
                unrealized_gain_loss_pct=0.0,
            )
            positions.append(pos)

        # Calculate portfolio gain/loss
        total_cost_basis = sum(pos.cost_basis for pos in positions)
        total_gain_loss = total_value - total_cost_basis
        total_gain_loss_pct = (total_gain_loss / total_cost_basis * 100) if total_cost_basis > 0 else 0.0

        # Create PortfolioState (snapshot of holdings at this moment)
        portfolio_state = PortfolioState(
            positions=positions,
            timestamp=datetime.now(),
        )

        # Create AggregationParameters (how this portfolio is defined)
        agg_params = AggregationParameters(
            as_of_date=datetime.now(),
        )

        # Create PortfolioSummary (aggregated statistics)
        summary = PortfolioSummary(
            total_portfolio_value=total_value,
            total_cost_basis=total_cost_basis,
            total_unrealized_gain_loss=total_gain_loss,
            total_unrealized_gain_loss_pct=total_gain_loss_pct,
            equity_value=equity_value,
            bond_value=bond_value,
            cash_value=cash_value,
            equity_pct=(equity_value / total_value * 100) if total_value > 0 else 0.0,
            bond_pct=(bond_value / total_value * 100) if total_value > 0 else 0.0,
            cash_pct=(cash_value / total_value * 100) if total_value > 0 else 0.0,
        )

        # Create CDM Portfolio
        portfolio = Portfolio(
            aggregation_parameters=agg_params,
            portfolio_state=portfolio_state,
            summary=summary,
        )

        # Wrap in result with compliance metadata
        result = CDMPortfolioResult(
            portfolio=portfolio,
            metadata=AnalysisMetadata(
                analysis_type="Portfolio Holdings Snapshot",
                is_investment_advice=False,
                disclaimer="⚠️ EDUCATIONAL ANALYSIS - NOT INVESTMENT ADVICE",
                consult_professional=(
                    "This analysis is educational only. Consult a qualified financial "
                    "professional before making investment decisions."
                ),
            ),
        )

        return result

    def main(self, input_file: str, output_file: str = 'holdings.json') -> None:
        """Main fetcher orchestration using Polars for high-speed data filtering."""
        try:
            # Load portfolio
            df = self.load_portfolio_file(input_file)

            # Add missing/null purchase_price with fallbacks
            if 'purchase_price' not in df.columns:
                if 'price' in df.columns:
                    df = df.with_columns(pl.col('price').alias('purchase_price'))
                    logger.warning("Using current 'price' as purchase_price (historical data unavailable)")
                else:
                    logger.warning("No price data found for purchase_price - using 0")
                    df = df.with_columns(pl.lit(0).alias('purchase_price'))
            else:
                # Fill null purchase_price using current_price if available, else market_value, else 0
                if 'current_price' in df.columns:
                    fallback = pl.col('current_price').fill_null(0)
                elif 'market_value' in df.columns:
                    fallback = pl.col('market_value').fill_null(0)
                else:
                    fallback = pl.lit(0)
                df = df.with_columns(
                    pl.when(pl.col('purchase_price').is_null())
                    .then(fallback)
                    .otherwise(pl.col('purchase_price'))
                    .alias('purchase_price')
                )
                logger.info("Filled null purchase_price values")

            if 'purchase_date' not in df.columns:
                df = df.with_columns(pl.lit('N/A').alias('purchase_date'))
                logger.warning("purchase_date not available in broker export (set to N/A)")

            df = self.validate_holdings_data(df)

            # Process by asset type using Polars filter (much faster than pandas).
            # mutual_fund rows (e.g. 401k collective investment trusts) are processed
            # alongside equities — they use purchase_price as NAV fallback.
            equity_df = df.filter(
                pl.col('asset_type').str.to_lowercase().is_in(['equity', 'mutual_fund'])
            ) if 'asset_type' in df.columns else df

            # Include both 'bond' and 'municipal_bond' types
            if 'asset_type' in df.columns:
                asset_lower = pl.col('asset_type').str.to_lowercase()
                bond_df = df.filter(
                    (asset_lower == 'bond') | (asset_lower == 'municipal_bond')
                )
            else:
                bond_df = pl.DataFrame()

            cash_df = df.filter(pl.col('asset_type').str.to_lowercase() == 'cash') if 'asset_type' in df.columns else pl.DataFrame()
            margin_df = df.filter(pl.col('asset_type').str.to_lowercase() == 'margin') if 'asset_type' in df.columns else pl.DataFrame()

            # Fetch data by type
            if len(equity_df) > 0:
                self.equity_data = self.fetch_equity_holdings(equity_df)
            if len(bond_df) > 0:
                self.bond_data = self.fetch_bond_holdings(bond_df)
            if len(cash_df) > 0:
                self.cash_data = self.fetch_cash_holdings(cash_df)
            if len(margin_df) > 0:
                self.margin_data = self.fetch_margin_holdings(margin_df)

            # Calculate totals by asset class (Holding objects have .value property)
            equity_value = sum(h.value for h in self.equity_data.values())
            bond_value = sum(h.value for h in self.bond_data.values())
            cash_value = sum(h.value for h in self.cash_data.values())
            margin_value = sum(h.value for h in self.margin_data.values())

            total_value = equity_value + bond_value + cash_value + margin_value

            # Build accounts grouping: group equity positions by account/source,
            # classify each account as etf_bundle | mixed | individual_stocks.
            # ETF and mutual fund positions cannot have underlying holdings adjusted
            # independently — the whole fund must be bought or sold.
            def _financial_type_from_name(acct_name, explicit_type=None):
                """Infer account financial type (ira/roth_ira/401k/brokerage/taxable)."""
                if explicit_type:
                    return explicit_type.lower().replace(' ', '_')
                n = acct_name.upper()
                if 'ROTH' in n:
                    return 'roth_ira'
                if 'IRA' in n:
                    return 'ira'
                if '401K' in n or '401(K)' in n or '401 K' in n or 'RETIREMENT' in n:
                    return '401k'
                if 'BROKERAGE' in n:
                    return 'brokerage'
                if 'TAXABLE' in n:
                    return 'taxable'
                return 'unknown'

            _accounts: dict = {}
            for _sym, _h in self.equity_data.items():
                # _h is now a Holding object; use property access
                _acct = _h.account or 'default'
                if _acct not in _accounts:
                    _ft = _financial_type_from_name(_acct, _h.account_type)
                    _accounts[_acct] = {
                        'symbols': [],
                        'etf_count': 0,
                        'fund_count': 0,
                        'equity_count': 0,
                        'total_value': 0.0,
                        'financial_type': _ft,
                    }
                _accounts[_acct]['symbols'].append(_sym)
                _accounts[_acct]['total_value'] += _h.value
                _st = _h.security_type or 'equity'
                if _st == 'etf':
                    _accounts[_acct]['etf_count'] += 1
                elif _st == 'mutual_fund':
                    _accounts[_acct]['fund_count'] += 1
                else:
                    _accounts[_acct]['equity_count'] += 1
            for _acct_data in _accounts.values():
                _total = _acct_data['etf_count'] + _acct_data['fund_count'] + _acct_data['equity_count']
                _bundle = _acct_data['etf_count'] + _acct_data['fund_count']
                _bundle_pct = _bundle / _total if _total > 0 else 0.0
                if _bundle_pct >= 0.8:
                    _acct_data['account_type'] = 'etf_bundle'
                elif _bundle_pct >= 0.3:
                    _acct_data['account_type'] = 'mixed'
                else:
                    _acct_data['account_type'] = 'individual_stocks'
                _acct_data['etf_bundle_percentage'] = round(_bundle_pct * 100, 1)

            # Convert to CDM-compliant Portfolio format
            cdm_portfolio = self._convert_to_cdm_portfolio(
                self.equity_data,
                self.bond_data,
                self.cash_data,
                equity_value,
                bond_value,
                cash_value,
                total_value,
            )

            # Write CDM-compliant output
            output_path = Path(output_file).expanduser()
            output_path.parent.mkdir(parents=True, exist_ok=True)
            with open(output_path, 'w') as f:
                json.dump(cdm_portfolio.to_dict(), f, indent=2, default=str)
            output_file = str(output_path)

            # Calculate total unrealized G/L for logging
            total_unrealized_gl = (
                sum(h.unrealized_gain_loss for h in self.equity_data.values()) +
                sum(h.unrealized_gain_loss for h in self.bond_data.values())
            )

            # Emit compact JSON to stdout for LLM injection (~8-15KB vs 290KB full CDM).
            # Full CDM is on disk at output_file for downstream scripts (analyst, performance, etc.)
            cdm_summary = cdm_portfolio.to_dict().get('portfolio', {}).get('summary', {})
            compact = _build_compact_holdings(
                self.equity_data, self.bond_data, self.cash_data, self.margin_data,
                total_value, cdm_summary, output_file,
            )
            compact_json = json.dumps(compact, separators=(',', ':'))
            print(compact_json)

            # Also persist compact summary to holdings_summary.json for downstream
            # scripts and the harness W1 verify check (<20KB, _note present).
            # The reports dir is the parent of .raw/ (or the output dir itself).
            reports_dir = output_path.parent
            if reports_dir.name == ".raw":
                reports_dir = reports_dir.parent
            summary_path = reports_dir / "holdings_summary.json"
            with open(summary_path, 'w') as _sf:
                _sf.write(compact_json)

        except Exception as e:
            logger.error(f"Fatal error in portfolio fetcher: {e}")
            raise

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: fetch_holdings.py <input_file> [output_file]")
        print("  input_file: CSV/XLS portfolio export from broker")
        print("  output_file: JSON output (default: holdings.json)")
        sys.exit(1)
    input_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else 'holdings.json'
    input_file = str(Path(input_file).expanduser())
    output_file = str(Path(output_file).expanduser())

    fetcher = PortfolioFetcher()
    fetcher.main(input_file, output_file)
