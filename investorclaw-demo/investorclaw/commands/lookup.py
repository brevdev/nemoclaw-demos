#!/usr/bin/env python3
"""
InvestorClaw Lookup Utility — agent-safe targeted reads from .raw/ data files.

This script is the ONLY sanctioned way for an agent to read specific data from
the full (non-compact) portfolio_reports/.raw/ files.  It extracts exactly the
requested slice and returns it as compact JSON to stdout — never the whole file.

Usage (via skill router):
  /portfolio lookup --symbol AAPL
  /portfolio lookup --symbol AAPL --file analyst
  /portfolio lookup --top 10 --file performance
  /portfolio lookup --accounts
  /portfolio lookup --file analyst --top 20

Arguments:
  reports_dir        Path to portfolio_reports/ (injected by command_builders)
  --symbol TICKER    Extract a single symbol from holdings or analyst data
  --file FILE        Which raw file to query: holdings (default) | analyst | performance | bonds
  --top N            Return top N records (performance: by return_pct desc)
  --accounts         List accounts summary from holdings (no symbol required)
  --fields f1,f2     Comma-separated list of fields to return per record

Exit codes: 0 on success, 1 on missing file or symbol not found.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _raw_path(reports_dir: Path, filename: str) -> Path:
    return reports_dir / ".raw" / filename


def _load_raw(reports_dir: Path, filename: str) -> dict | list | None:
    path = _raw_path(reports_dir, filename)
    if not path.exists():
        print(json.dumps({"error": f"{filename} not found. Run the relevant /portfolio command first."}))
        return None
    with open(path) as f:
        return json.load(f)


def _try_load_raw(reports_dir: Path, filename: str) -> dict | list | None:
    """Like _load_raw but returns None silently if the file is missing (no error output)."""
    path = _raw_path(reports_dir, filename)
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def _filter_fields(record: dict, fields: list[str] | None) -> dict:
    if not fields:
        return record
    return {k: v for k, v in record.items() if k in fields}


# ---------------------------------------------------------------------------
# Query handlers
# ---------------------------------------------------------------------------

def query_holdings_symbol(reports_dir: Path, symbol: str, fields: list[str] | None) -> int:
    """Extract a single position from .raw/holdings.json."""
    cdm = _load_raw(reports_dir, "holdings.json")
    if cdm is None:
        return 1

    positions = cdm.get("portfolio", {}).get("portfolioState", {}).get("positions", [])
    matches = []
    sym_upper = symbol.upper()

    for pos in positions:
        ident = pos.get("product", {}).get("productIdentifier", {})
        if ident.get("identifier", "").upper() == sym_upper:
            matches.append(pos)

    if not matches:
        print(json.dumps({"error": f"Symbol '{symbol}' not found in holdings."}))
        return 1

    result = {"symbol": sym_upper, "positions": [_filter_fields(m, fields) for m in matches]}
    print(json.dumps(result, indent=2, default=str))
    return 0


def query_holdings_accounts(reports_dir: Path) -> int:
    """Return account-level summary from .raw/holdings.json."""
    cdm = _load_raw(reports_dir, "holdings.json")
    if cdm is None:
        return 1

    summary = cdm.get("portfolio", {}).get("summary", {})
    accounts = cdm.get("portfolio", {}).get("accounts", {})
    result = {
        "accounts_summary": accounts,
        "portfolio_summary": summary,
    }
    print(json.dumps(result, indent=2, default=str))
    return 0


def query_analyst_symbol(reports_dir: Path, symbol: str, fields: list[str] | None) -> int:
    """
    Extract a single symbol from analyst data.

    Fallback chain (richest → most available):
      1. .raw/analyst_data.json          — full payload written by fetch_analyst script
      2. .raw/analyst_recommendations_tier3_enriched.json — enriched subset (20 symbols)
      3. analyst_recommendations_summary.json  — compact summary in main reports dir
    """
    sym_upper = symbol.upper()

    # 1. Full analyst payload in .raw/ (silent — tier3 fallback may succeed)
    data = _try_load_raw(reports_dir, "analyst_data.json")
    if data:
        recs = data.get("recommendations", {})
        if sym_upper in recs:
            rec = _filter_fields(recs[sym_upper], fields)
            print(json.dumps({"symbol": sym_upper, "source": "analyst_data", **rec}, indent=2, default=str))
            return 0

    # 2. Tier3 enriched (has synthesis + consultation block)
    t3 = _try_load_raw(reports_dir, "analyst_recommendations_tier3_enriched.json")
    if t3:
        enriched = t3.get("enriched_recommendations", {})
        if sym_upper in enriched:
            rec = _filter_fields(enriched[sym_upper], fields)
            print(json.dumps({"symbol": sym_upper, "source": "tier3_enriched", **rec}, indent=2, default=str))
            return 0

    # 3. Compact summary in main dir (always present after /portfolio analyst)
    summary_path = reports_dir / "analyst_recommendations_summary.json"
    if summary_path.exists():
        with open(summary_path) as f:
            summary = json.load(f)
        recs = summary.get("recommendations", {})
        if sym_upper in recs:
            rec = _filter_fields(recs[sym_upper], fields)
            print(json.dumps({"symbol": sym_upper, "source": "analyst_summary", **rec}, indent=2, default=str))
            return 0

    print(json.dumps({"error": f"Symbol '{symbol}' not found. Run '/portfolio analyst' first."}))
    return 1


def query_performance_top(reports_dir: Path, top_n: int, fields: list[str] | None) -> int:
    """Return top N positions by return_pct from .raw/performance.json."""
    data = _load_raw(reports_dir, "performance.json")
    if data is None:
        return 1

    positions = data.get("positions", data.get("holdings", []))
    if isinstance(positions, dict):
        positions = list(positions.values())

    # Sort by return_pct descending
    try:
        positions.sort(key=lambda p: float(p.get("return_pct", 0)), reverse=True)
    except (TypeError, ValueError):
        pass

    top = [_filter_fields(p, fields) for p in positions[:top_n]]
    print(json.dumps({"top_n": top_n, "by": "return_pct", "positions": top}, indent=2, default=str))
    return 0


def query_bonds_symbol(reports_dir: Path, symbol: str, fields: list[str] | None) -> int:
    """Extract a single CUSIP/symbol from .raw/bond_analysis.json."""
    data = _load_raw(reports_dir, "bond_analysis.json")
    if data is None:
        return 1

    bonds = data.get("bonds", data.get("positions", []))
    if isinstance(bonds, dict):
        bonds = list(bonds.values())

    sym_upper = symbol.upper()
    matches = [b for b in bonds if
               b.get("cusip", "").upper() == sym_upper or
               b.get("symbol", "").upper() == sym_upper or
               b.get("ticker", "").upper() == sym_upper]

    if not matches:
        print(json.dumps({"error": f"Bond '{symbol}' not found in bond_analysis."}))
        return 1

    result = {"symbol": sym_upper, "bonds": [_filter_fields(m, fields) for m in matches]}
    print(json.dumps(result, indent=2, default=str))
    return 0


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="Targeted lookup from portfolio_reports/.raw/ data files."
    )
    parser.add_argument("reports_dir", help="Path to portfolio_reports/ directory")
    parser.add_argument("--symbol",  default=None, help="Ticker or CUSIP to look up")
    parser.add_argument("--file",    default="holdings",
                        choices=["holdings", "analyst", "performance", "bonds"],
                        help="Which raw file to query (default: holdings)")
    parser.add_argument("--top",     type=int, default=None,
                        help="Return top N records (performance only)")
    parser.add_argument("--accounts", action="store_true",
                        help="Return account summary from holdings")
    parser.add_argument("--fields",  default=None,
                        help="Comma-separated field names to include in output")
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir).expanduser().resolve()
    fields = [f.strip() for f in args.fields.split(",")] if args.fields else None

    if args.file == "holdings":
        if args.accounts:
            return query_holdings_accounts(reports_dir)
        if args.symbol:
            return query_holdings_symbol(reports_dir, args.symbol, fields)
        print(json.dumps({"error": "Specify --symbol TICKER or --accounts for holdings lookup."}))
        return 1

    if args.file == "analyst":
        if args.symbol:
            return query_analyst_symbol(reports_dir, args.symbol, fields)
        print(json.dumps({"error": "Specify --symbol TICKER for analyst lookup."}))
        return 1

    if args.file == "performance":
        n = args.top or 10
        return query_performance_top(reports_dir, n, fields)

    if args.file == "bonds":
        if args.symbol:
            return query_bonds_symbol(reports_dir, args.symbol, fields)
        print(json.dumps({"error": "Specify --symbol CUSIP or ticker for bond lookup."}))
        return 1

    print(json.dumps({"error": f"Unknown --file: {args.file}"}))
    return 1


if __name__ == "__main__":
    sys.exit(main())
