#!/usr/bin/env python3
"""
Fetch master symbol database from NASDAQ Trader (HTTPS).

Writes:
  data/master_symbols.parquet  — fast lookup (polars, snappy)
  data/master_symbols.json     — human-readable reference

Entry point: fetch_and_write(data_dir, *, quiet=False) -> int
"""

import json
import re
import urllib.request
from pathlib import Path
from typing import Optional

NASDAQ_URL = "https://www.nasdaqtrader.com/dynamic/symdir/nasdaqlisted.txt"
OTHER_URL  = "https://www.nasdaqtrader.com/dynamic/symdir/otherlisted.txt"

_HEADER_RE = re.compile(r'^Symbol\|', re.IGNORECASE)


def _fetch_text(url: str, timeout: int = 30) -> str:
    req = urllib.request.Request(url, headers={"User-Agent": "InvestorClaw/1.0"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read().decode("utf-8", errors="replace")


def _parse_nasdaq(text: str) -> list[dict]:
    """Parse nasdaqlisted.txt — pipe-delimited, header on line 0."""
    rows = []
    lines = text.splitlines()
    for line in lines[1:]:
        parts = line.split("|")
        if len(parts) < 2:
            continue
        symbol = parts[0].strip()
        # Skip File Creation Time trailer and blank symbols
        if not symbol or symbol.startswith("File Creation"):
            continue
        # Skip test issues and warrant/unit/note suffixes typical of NASDAQ file
        rows.append({"symbol": symbol, "exchange": "NASDAQ", "category": "NASDAQ Listed"})
    return rows


def _parse_other(text: str) -> list[dict]:
    """Parse otherlisted.txt — pipe-delimited, header on line 0."""
    rows = []
    lines = text.splitlines()
    for line in lines[1:]:
        parts = line.split("|")
        if len(parts) < 4:
            continue
        symbol = parts[0].strip()
        exchange_code = parts[2].strip() if len(parts) > 2 else ""
        if not symbol or symbol.startswith("File Creation"):
            continue
        exchange_map = {
            "A": "NYSE MKT",
            "N": "NYSE",
            "P": "NYSE ARCA",
            "Z": "BATS",
            "V": "IEXG",
        }
        exchange = exchange_map.get(exchange_code, exchange_code or "Other")
        rows.append({"symbol": symbol, "exchange": exchange, "category": "Other Listed"})
    return rows


def fetch_and_write(
    data_dir: Optional[Path] = None,
    *,
    quiet: bool = False,
) -> int:
    """
    Fetch symbol data from NASDAQ Trader and write parquet + JSON files.

    Args:
        data_dir: Directory to write output files (default: ./data)
        quiet:    Suppress progress output

    Returns:
        Total number of symbols written (0 on failure)
    """
    if data_dir is None:
        data_dir = Path(__file__).parent.parent / "data"
    data_dir = Path(data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)

    def log(msg: str) -> None:
        if not quiet:
            print(msg)

    rows: list[dict] = []

    log("  Fetching NASDAQ listed symbols...")
    try:
        nasdaq_text = _fetch_text(NASDAQ_URL)
        nasdaq_rows = _parse_nasdaq(nasdaq_text)
        rows.extend(nasdaq_rows)
        log(f"  NASDAQ: {len(nasdaq_rows):,} symbols")
    except Exception as exc:
        log(f"  Warning: NASDAQ fetch failed — {exc}")

    log("  Fetching other-listed symbols...")
    try:
        other_text = _fetch_text(OTHER_URL)
        other_rows = _parse_other(other_text)
        rows.extend(other_rows)
        log(f"  Other exchanges: {len(other_rows):,} symbols")
    except Exception as exc:
        log(f"  Warning: Other-listed fetch failed — {exc}")

    if not rows:
        log("  Error: no symbols retrieved from either source")
        return 0

    # Deduplicate by symbol (keep first occurrence)
    seen: set[str] = set()
    deduped: list[dict] = []
    for row in rows:
        sym = row["symbol"]
        if sym not in seen:
            seen.add(sym)
            deduped.append(row)

    total = len(deduped)
    log(f"  Total unique symbols: {total:,}")

    # Write parquet
    try:
        import polars as pl
        df = pl.DataFrame(deduped)
        parquet_path = data_dir / "master_symbols.parquet"
        df.write_parquet(str(parquet_path), compression="snappy")
        log(f"  Wrote {parquet_path.name} ({parquet_path.stat().st_size // 1024} KB)")
    except ImportError:
        log("  Warning: polars not installed — skipping parquet output")
    except Exception as exc:
        log(f"  Warning: parquet write failed — {exc}")

    # Write JSON reference
    try:
        json_path = data_dir / "master_symbols.json"
        payload = {
            "metadata": {
                "total": total,
                "sources": [NASDAQ_URL, OTHER_URL],
            },
            "symbols": [r["symbol"] for r in deduped],
            "records": deduped,
        }
        with open(json_path, "w") as fh:
            json.dump(payload, fh, separators=(",", ":"))
        log(f"  Wrote {json_path.name} ({json_path.stat().st_size // 1024} KB)")
    except Exception as exc:
        log(f"  Warning: JSON write failed — {exc}")

    return total


if __name__ == "__main__":
    import sys

    quiet = "--quiet" in sys.argv or "-q" in sys.argv
    n = fetch_and_write(quiet=quiet)
    if n:
        print(f"Done: {n:,} symbols written")
    else:
        print("Failed: no symbols written")
        sys.exit(1)
