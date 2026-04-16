---
name: investorclaw
description: FINOS CDM 5.x-compliant portfolio analysis for InvestorClaw. Provides holdings snapshots, performance metrics, bond analytics, analyst consensus, news, and CSV reports. Educational output only — not investment advice.
---

# InvestorClaw Portfolio Analysis

Educational portfolio analysis using live market data via Yahoo Finance (free tier).
All output is informational only — not personalized investment advice.

## When to use
- User requests /portfolio commands or asks about portfolio holdings
- Portfolio analysis, holdings summary, bond analytics, performance review, sector breakdown
- Financial news for held positions

## Environment Setup (run before any command)

InvestorClaw uses a local vendor directory so no global packages need to be pre-installed.
This setup is idempotent — safe to run on every invocation.

```bash
IC_HOME=/home/pi/.zeroclaw/workspace/ic_code
IC_VENDOR=${IC_HOME}/vendor

# Create vendor dir and install dependencies if not already present
if ! python3 -c "import polars" 2>/dev/null; then
  pip3 install -q --target "${IC_VENDOR}" \
    "polars>=0.20.0" "pandas>=2.0.0" "pyarrow>=12.0.0" \
    "yfinance>=0.2.35" "requests>=2.31.0" \
    "pyyaml>=6.0" "orjson>=3.9.0" "python-dateutil>=2.8.0" \
    "python-dotenv>=1.0.0" 2>&1 | tail -3
fi

export PYTHONPATH="${IC_HOME}:${IC_VENDOR}"
export IC_PORTFOLIO_CSV="${IC_HOME}/portfolios/UBS_Holdings_07_04_2026.csv"
export IC_HOLDINGS_JSON="${IC_HOME}/data/holdings.json"

# Verify
python3 -c "import polars, yfinance, pandas; print('deps OK')"
```

Detect available portfolio CSV automatically if the default path does not exist:

```bash
IC_HOME=/home/pi/.zeroclaw/workspace/ic_code
CSV_FILE=$(ls ${IC_HOME}/portfolios/*.csv 2>/dev/null | head -1)
[ -z "$CSV_FILE" ] && { echo "ERROR: No portfolio CSV found in ${IC_HOME}/portfolios/"; exit 1; }
echo "Using CSV: $CSV_FILE"
```

## Commands

### /portfolio setup
Validate environment, detect CSVs, confirm data directories exist:

```bash
IC_HOME=/home/pi/.zeroclaw/workspace/ic_code
IC_VENDOR=${IC_HOME}/vendor
python3 -c "import polars" 2>/dev/null || pip3 install -q --target "${IC_VENDOR}" polars pandas pyarrow yfinance requests pyyaml orjson python-dateutil python-dotenv
export PYTHONPATH="${IC_HOME}:${IC_VENDOR}"
python3 ${IC_HOME}/commands/auto_setup.py
```

Expected: setup summary, or "Setup already complete. Skipping."

### /portfolio holdings
Fetch live prices and build holdings snapshot. Output goes to stdout as JSON — parse it directly.

```bash
IC_HOME=/home/pi/.zeroclaw/workspace/ic_code
IC_VENDOR=${IC_HOME}/vendor
python3 -c "import polars" 2>/dev/null || pip3 install -q --target "${IC_VENDOR}" polars pandas pyarrow yfinance requests pyyaml orjson python-dateutil python-dotenv
export PYTHONPATH="${IC_HOME}:${IC_VENDOR}"
CSV_FILE=$(ls ${IC_HOME}/portfolios/*.csv 2>/dev/null | head -1)
python3 ${IC_HOME}/commands/fetch_holdings.py "${CSV_FILE}" "${IC_HOME}/data/holdings.json"
```

Key output fields (parse from stdout JSON):
- `summary.total_value` — total portfolio value in USD
- `summary.equity_pct`, `summary.bond_pct`, `summary.cash_pct` — allocation
- `summary.unrealized_gl_pct` — unrealized gain/loss %
- `top_equity` — top 25 positions with symbol, sector, value, weight_pct, gl_pct
- `top_bonds` — top 5 bonds with cusip, value, coupon, maturity
- `sector_weights` — allocation by sector
- `accounts` — per-account breakdown

Note: `FIDCFPF` (Fidelity 401K fund) will show as Unknown sector with 0% gl — expected.

### /portfolio performance
Analyze performance metrics (run /portfolio holdings first):

```bash
IC_HOME=/home/pi/.zeroclaw/workspace/ic_code
IC_VENDOR=${IC_HOME}/vendor
python3 -c "import polars" 2>/dev/null || pip3 install -q --target "${IC_VENDOR}" polars pandas pyarrow yfinance requests pyyaml orjson python-dateutil python-dotenv
export PYTHONPATH="${IC_HOME}:${IC_VENDOR}"
python3 ${IC_HOME}/commands/analyze_performance_polars.py "${IC_HOME}/data/holdings.json"
```

### /portfolio bonds
Bond analytics — duration, yield-to-maturity, maturity ladder:

```bash
IC_HOME=/home/pi/.zeroclaw/workspace/ic_code
IC_VENDOR=${IC_HOME}/vendor
python3 -c "import polars" 2>/dev/null || pip3 install -q --target "${IC_VENDOR}" polars pandas pyarrow yfinance requests pyyaml orjson python-dateutil python-dotenv
export PYTHONPATH="${IC_HOME}:${IC_VENDOR}"
python3 ${IC_HOME}/commands/bond_analyzer.py "${IC_HOME}/data/holdings.json"
```

### /portfolio analyst
Analyst consensus ratings for equity positions:

```bash
IC_HOME=/home/pi/.zeroclaw/workspace/ic_code
IC_VENDOR=${IC_HOME}/vendor
python3 -c "import polars" 2>/dev/null || pip3 install -q --target "${IC_VENDOR}" polars pandas pyarrow yfinance requests pyyaml orjson python-dateutil python-dotenv
export PYTHONPATH="${IC_HOME}:${IC_VENDOR}"
python3 ${IC_HOME}/commands/fetch_analyst_recommendations_parallel.py "${IC_HOME}/data/holdings.json"
```

### /portfolio news
Fetch recent news for held positions:

```bash
IC_HOME=/home/pi/.zeroclaw/workspace/ic_code
IC_VENDOR=${IC_HOME}/vendor
python3 -c "import polars" 2>/dev/null || pip3 install -q --target "${IC_VENDOR}" polars pandas pyarrow yfinance requests pyyaml orjson python-dateutil python-dotenv
export PYTHONPATH="${IC_HOME}:${IC_VENDOR}"
python3 ${IC_HOME}/commands/fetch_portfolio_news.py "${IC_HOME}/data/holdings.json"
```

### /portfolio synthesize
Full portfolio synthesis report:

```bash
IC_HOME=/home/pi/.zeroclaw/workspace/ic_code
IC_VENDOR=${IC_HOME}/vendor
python3 -c "import polars" 2>/dev/null || pip3 install -q --target "${IC_VENDOR}" polars pandas pyarrow yfinance requests pyyaml orjson python-dateutil python-dotenv
export PYTHONPATH="${IC_HOME}:${IC_VENDOR}"
python3 ${IC_HOME}/commands/portfolio_analyzer.py \
  "${IC_HOME}/data/holdings.json" \
  "${IC_HOME}/data/synthesis_report.json"
```

### /portfolio guardrails [--prime]
Check or prime anti-fabrication guardrails:

```bash
IC_HOME=/home/pi/.zeroclaw/workspace/ic_code
export PYTHONPATH="${IC_HOME}"
python3 ${IC_HOME}/commands/model_guardrails.py [--prime]
```

### /portfolio session
Initialize CDM session identity context:

```bash
IC_HOME=/home/pi/.zeroclaw/workspace/ic_code
export PYTHONPATH="${IC_HOME}"
python3 ${IC_HOME}/commands/session_init.py
```

### /portfolio report
Generate end-of-day report:

```bash
IC_HOME=/home/pi/.zeroclaw/workspace/ic_code
IC_VENDOR=${IC_HOME}/vendor
export PYTHONPATH="${IC_HOME}:${IC_VENDOR}"
python3 ${IC_HOME}/commands/eod_report.py "${IC_HOME}/data/holdings.json"
```

### /portfolio lookup <TICKER>
Look up a single security:

```bash
IC_HOME=/home/pi/.zeroclaw/workspace/ic_code
IC_VENDOR=${IC_HOME}/vendor
export PYTHONPATH="${IC_HOME}:${IC_VENDOR}"
python3 ${IC_HOME}/commands/lookup.py <TICKER>
```

## Anti-Fabrication Rules

1. **Always execute the command and use its actual output** — never generate portfolio data from memory or prior sessions
2. If a command fails, report the exact error — do not fabricate a success response
3. All output is educational/informational — include the disclaimer: "EDUCATIONAL ANALYSIS - NOT INVESTMENT ADVICE"
4. Do not cache or reuse output from a previous /portfolio holdings run without re-executing
5. If PYTHONPATH or vendor install fails, report it and stop — do not guess at data

## Troubleshooting

| Error | Fix |
|-------|-----|
| `ModuleNotFoundError: No module named 'rendering'` | Set `PYTHONPATH=/home/pi/investorclaw` |
| `Usage: fetch_holdings.py <input_file>` | Pass CSV path as first argument |
| `Quote not found for symbol: FIDCFPF` | Expected — Fidelity fund not in Yahoo Finance |
| `No portfolio CSV found` | Copy CSV to `~/investorclaw/portfolios/` |
| pip install fails | Check network; try `pip3 install --break-system-packages` |
