---
name: portfolio
version: 1.0.0
description: FINOS CDM 5.x-compliant portfolio analysis skill for OpenClaw agents. Provides holdings snapshots, performance metrics, bond analytics (YTM, duration, FRED-backed benchmarks), analyst consensus ratings, news correlation, and CSV/Excel reports. Built-in financial advice guardrails enforce educational-only output. Requires Python 3.9+.
homepage: https://github.com/perlowja/InvestorClaw
user-invocable: true
metadata: {"openclaw":{"emoji":"📊","requires":{"bins":["python3"]},"install":[{"id":"pip","kind":"shell","label":"Install Python dependencies","run":"pip3 install -r requirements.txt"}]}}
---

# InvestorClaw

> **Installation scope**: This SKILL.md describes the **linked plugin installation** of InvestorClaw.
> Install via `openclaw plugins install --link ~/Projects/InvestorClaw` after cloning from GitHub.
> See README.md Quick Install section for the full one-shot install procedure.
> It is not required to publish this skill to ClawHub for personal use.

Portfolio analysis for OpenClaw agents. **v1.0.0** | FINOS CDM 5.x | Educational guardrails.

> **Model requirement**: 128K+ token context window. Recommended: 200K+.
> **Preferred model**: `xai/grok-4-1-fast` (2M context). GPT-4.1-nano Tier 1 is 30K TPM shared across all session activity — other concurrent agentic tasks may exhaust the budget.
> **Grok compliance**: `xai/grok-4-1-fast` requires `/portfolio update-identity` before each session (0% disclaimer compliance without active guardrails — April 2026 testing).
> **Naming**: package id is `investorclaw` (ClawHub / `openclaw.plugin.json`); agent command is `/portfolio`. Both are intentional.

## Commands

| Command | Aliases | Agent-readable output |
|---------|---------|----------------------|
| `/portfolio holdings` | `snapshot`, `prices` | `holdings.json` |
| `/portfolio performance` | `analyze`, `returns` | `performance.json` |
| `/portfolio bonds` | `bond-analysis`, `analyze-bonds` | `bond_analysis.json` |
| `/portfolio analyst` | `analysts`, `ratings` | `analyst_data.json` |
| `/portfolio news` | `sentiment` | `portfolio_news.json` |
| `/portfolio analysis` | `portfolio-analysis` | `portfolio_analysis.json` |
| `/portfolio synthesize` | `multi-factor`, `recommend`, `recommendations` | `portfolio_analysis.json` |
| `/portfolio fixed-income` | `fixed-income-analysis`, `bond-strategy` | `fixed_income_analysis.json` |
| `/portfolio report` | `export`, `csv`, `excel` | `portfolio_report.{csv,xlsx}` |
| `/portfolio session` | `session-init`, `risk-profile`, `calibrate` | `session_profile.json` |
| `/portfolio lookup` | `query`, `detail` | *(compact stdout — targeted .raw read)* |
| `/portfolio guardrails` | `guardrail`, `guardrails-prime`, `guardrails-status` | — |
| `/portfolio setup` | `auto-setup`, `init`, `initialize` | — |
| `/portfolio update-identity` | `update_identity`, `identity` | — |
| `/portfolio run` | `pipeline` | *(compact stdout)* |
| `/portfolio ollama-setup` | `model-setup`, `consult-setup` | *(stdout: model status)* |
| `/portfolio help` | — | — |

All output files written to `$INVESTOR_CLAW_REPORTS_DIR` (default: `~/portfolio_reports/`).

**Invocation**: Always run commands via the entry point using the absolute path — never use `cd && python3` (blocked by OpenClaw exec preflight):
```bash
# Linked plugin install (recommended)
python3 ~/Projects/InvestorClaw/investorclaw.py <command>
```
The entry point loads `.env`, sets PYTHONPATH, injects `--tier3` when consultation is enabled, and routes to the correct script.
Add `--verbose` to any command for full detail (default is compact/summary).

### ic_result Verification Protocol

Every script invocation emits a terminal verification envelope as the last stdout line:

```json
{"ic_result":{"script":"fetch_holdings.py","exit_code":0,"duration_ms":1420}}
```

**Agent rules**:
- Echo `ic_result.exit_code` in every response that invokes a script.
- Absence of `ic_result` = UNVERIFIED — state this explicitly; do not report success.
- If exec preflight blocks the command, output only: `"BLOCKED: <exact error>"`.
- Do NOT reconstruct or narrate a hypothetical result for blocked or missing output.

### Output Directory Layout

```
~/portfolio_reports/                  ← agent-readable compact files ONLY
    holdings.json
    performance.json
    bond_analysis.json
    analyst_data.json
    portfolio_news.json
    portfolio_analysis.json
    fixed_income_analysis.json
    session_profile.json
    portfolio_report.xlsx / *.csv

~/portfolio_reports/.raw/             ← optional internal/enrichment artifacts
    analyst_recommendations_tier1_immediate.json
    analyst_recommendations_tier2_background.json
    analyst_recommendations_tier3_enriched.json
    performance.json
    bond_analysis.json
    portfolio_news_cache.json
```

**NEVER read files from `.raw/` directly.** If you need specific symbol detail not in the compact output, use the lookup command instead.

## Output Format

All outputs use the mandatory disclaimer wrapper:

```json
{
  "disclaimer": "⚠️  EDUCATIONAL ANALYSIS - NOT INVESTMENT ADVICE",
  "is_investment_advice": false,
  "consult_professional": "Consult a qualified financial adviser",
  "data": { ... },
  "generated_at": "2026-04-07T..."
}
```

### Compact vs Full Output

**Holdings, performance, and analyst commands emit compact JSON to stdout** (~1–5K tokens) and write a compact summary file to `portfolio_reports/`. The full data is written to `portfolio_reports/.raw/` for downstream script use only.

**NEVER read files from `.raw/` directly.** Work exclusively from compact stdout output or the summary files in `portfolio_reports/`. If a user asks for a specific symbol or detail not in the compact output, use the lookup command:

```bash
IC_ENTRY=~/Projects/InvestorClaw/investorclaw.py

# Holdings detail for a symbol
python3 $IC_ENTRY lookup --symbol AAPL
python3 $IC_ENTRY lookup --symbol AAPL --file holdings

# Analyst data for a symbol
python3 $IC_ENTRY lookup --symbol MSFT --file analyst

# Top 10 performers from performance data
python3 $IC_ENTRY lookup --file performance --top 10

# Account summary from holdings
python3 $IC_ENTRY lookup --accounts

# Specific fields only
python3 $IC_ENTRY lookup --symbol AAPL --fields consensus,analyst_count,current_price
```

This returns a compact targeted slice — never the full file.

When a `quote` block is present in any output JSON with `verbatim_required: true`:

- If `quote.card_path` is set, present the card path and cite `quote.attribution`.
- Otherwise present `quote.text` **verbatim** — do not paraphrase or reorder.
- Always include `quote.fingerprint` in your response for audit traceability.
- Do NOT re-analyze or substitute your own synthesis.

```json
{
  "quote": {
    "text": "Analyst consensus is Strong Buy with 54 analysts...",
    "attribution": "gemma4-consult via local-inference (3420ms)",
    "verbatim_required": true,
    "fingerprint": "a1b2c3d4e5f6g7h8",
    "card_path": "/Users/.../portfolio_reports/.raw/consultation_cards/MSFT.svg"
  },
  "consultation": {
    "model": "gemma4-consult",
    "endpoint": "http://localhost:11434",
    "inference_ms": 3420,
    "is_heuristic": false
  }
}
```

The consultation model is **user-configured** via `INVESTORCLAW_CONSULTATION_MODEL`. Default: `gemma4-consult` — a tuned Ollama derivative of `gemma4:e4b` (num_ctx=2048, num_predict=600, ~65 tok/s on RTX Ada). Other tested models: `gemma4:e4b`, `nemotron-3-nano`, `qwen2.5:14b`. Run `/portfolio setup` to auto-detect available models on your endpoint.

### synthesis_basis Confidence Tiers

Each symbol in compact output includes a `synthesis_basis` field:

| Value | Source | Agent behavior |
|-------|--------|---------------|
| `enriched` | LLM synthesis (is_heuristic=false) | Present `quote.text` verbatim or show `quote.card_path` |
| `structured` | Live Finnhub data, no synthesis | Cite structured fields only: `"Analyst consensus: {consensus} ({analyst_count} analysts)"` |
| `failed` | No price or analyst data | State data unavailable — do not synthesize |

**Never apply enriched-symbol quality inferences to `structured` positions.**

### Turn-Level Enrichment Status

Every analyst or portfolio response must begin with the `enrichment_status.display` string:

```
⏳ Enrichment: 20/215 · 9.3% · a1b2c3d4 · updating
✅ Enrichment: 215/215 · 100.0% · a1b2c3d4 · complete
⚠️ Enrichment status unknown
```

The display string is sourced from `enrichment_status.display` in the compact stdout. If absent, output `⚠️ Enrichment status unknown`.

### Setting up gemma4-consult

`gemma4-consult` must be created on your Ollama endpoint before enabling consultation. It is built from `gemma4:e4b` using the Modelfile at `docs/gemma4-consult.Modelfile`.

**Automated setup** (recommended):
```bash
IC_ENTRY=~/Projects/InvestorClaw/investorclaw.py

# Check what models are available
python3 $IC_ENTRY ollama-setup --check --endpoint http://your-ollama-host:11434

# Pull gemma4:e4b base and create gemma4-consult
python3 $IC_ENTRY ollama-setup --endpoint http://your-ollama-host:11434

# Set up all InvestorClaw GPU models (e2b, e4b, gemma4-consult)
python3 $IC_ENTRY ollama-setup --model all --endpoint http://your-ollama-host:11434
```

**Manual setup**:
```bash
ollama pull gemma4:e4b
ollama create gemma4-consult -f docs/gemma4-consult.Modelfile
ollama list | grep gemma4-consult
```

Hardware requirements: 12+ GB VRAM, CUDA compute capability ≥ 8.0 (RTX 30xx / A-series / Ada Lovelace or newer), Ollama ≥ 0.20.x.

## Portfolio File Format

Supported: CSV, Excel (.xls, .xlsx). Place files in `portfolios/` or `$INVESTOR_CLAW_PORTFOLIO_DIR`.

Auto-detected column names:

| Column | Recognized Names |
|--------|-----------------|
| Symbol | `SYMBOL`, `TICKER`, `symbol`, `Description` |
| Quantity | `QUANTITY`, `SHARES`, `QTY`, `shares` |
| Price | `PRICE`, `MARKET PRICE`, `current_price` |
| Value | `VALUE`, `MARKET VALUE`, `value` |
| Asset type | `ASSET TYPE`, `TYPE`, `asset_type` |
| Cost basis | `COST BASIS`, `PURCHASE PRICE`, `purchase_price` |
| Purchase date | `PURCHASE DATE`, `purchase_date` |
| Coupon rate | `COUPON`, `COUPON RATE`, `coupon_rate` (bonds) |
| Maturity date | `MATURITY`, `MATURITY DATE`, `maturity_date` (bonds) |

Bond coupon/maturity embedded in description text (e.g., `"RATE 05.000% MATURES 11/01/28"`) are extracted automatically. Run `/portfolio setup` for guided column-mapping if your broker uses unlisted names.

## Channel Formatting

Many users interact via mobile channels (320–430px display width). Format all output to be readable on small screens:

- **No wide tables** — avoid pipe-separated columns that wrap badly
- **Max ~60 characters per line** — use stacked two-line formats instead of horizontal layouts
- **No raw JSON to user** — always render the compact digest as prose or short lists
- **Bold tickers** — use `**AAPL**` for symbol emphasis
- **Short separators** — use `---` or a brief label, not 60/80-char `===` banners
- **Mobile-first default** — assume mobile unless `--verbose` is passed

## News Presentation

Present `portfolio_news.json` compact digest as follows — do NOT collapse all news into one sentence:

1. **Overall sentiment** — `sentiment_breakdown` counts + net portfolio impact
2. **Top positive movers** — top 5 from `top_positive_movers`, two-line stacked format:
   ```
   📈 **AAPL** +$10,500
      Apple Q1 Earnings Beat Estimates by 12%
   ```
3. **Top negative movers** — top 5 from `top_negative_movers`, same stacked format:
   ```
   📉 **NVDA** -$8,200
      Chip export restrictions widen to additional markets
   ```
4. **Symbol digest** — from `symbol_digest`, two lines per holding:
   ```
   **MSFT** · 12.4% · Bullish · 4 articles
     → Azure growth accelerates in Q1 earnings call
   ```
5. **Macro themes** — shared themes across multiple holdings (AI capex, rates, energy)
6. **On-demand detail** — tell user they can run `/portfolio news --symbol TICKER` for full articles

Sort movers by `portfolio_impact` (highest dollar-weighted first).

## Holdings Classification

Each holding in `holdings.json` includes:
- `security_type`: `"etf"` | `"mutual_fund"` | `"equity"`
- `is_etf`: `true` | `false`
- `financial_type`: `"ira"` | `"roth_ira"` | `"401k"` | `"brokerage"` | `"taxable"` | `"unknown"`

Accounts are classified as `"etf_bundle"` (80%+ funds), `"mixed"` (30–80%), or `"individual_stocks"` (<30%).

**ETF/fund guidance**: ETF and mutual fund positions cannot be individually adjusted — the user can only buy or sell the fund as a whole. Before suggesting any position change, check `is_etf`. If true, frame at fund level (e.g., "To reduce IVV exposure, sell IVV shares — you cannot adjust S&P 500 components directly"). Analyst ratings and news for ETF tickers reflect the fund, not individual underlying companies. Note: ETF classification (`is_etf`, `security_type`) is provided but ETF constituent expansion (detailed allocation view of underlying holdings) is not currently implemented.

## 401K / Mutual Fund Holdings

Funds without standard tickers use synthetic symbol IDs (e.g., `FID_CONTRA_POOL`). Set `proxy_symbol` to a publicly-traded equivalent for live pricing via yfinance (e.g., `FCNTX`). Without a proxy, `purchase_price` is used as current NAV.

Account type is inferred from the account name if not set in the CSV: `ROTH` → `roth_ira`; `IRA` → `ira`; `401K` or `RETIREMENT` → `401k`; `BROKERAGE` → `brokerage`. The `financial_type` field appears in the `accounts` block of `holdings.json`. To merge multiple portfolio files, run `fetch_holdings.py` on each and use `scripts/consolidate_portfolios.py`.

## Errors

| Error | Solution |
|-------|----------|
| No portfolio file found | Run `/portfolio setup` first |
| API rate limit | Wait 5–10 min and retry |
| Model context warning | Use 128K+ token model |
| Guardrail violations | Output auto-corrected; check logs |

## OpenClaw 2026.4.12 Compatibility Notes

The following behaviours are confirmed against OpenClaw 2026.4.12 and must be followed exactly.

### Skill installation

Primary install path uses the linked plugin mechanism (OpenClaw 2026.4.12+):

```bash
git clone https://github.com/perlowja/InvestorClaw.git ~/Projects/InvestorClaw
pip install -r ~/Projects/InvestorClaw/requirements.txt
openclaw plugins install --link ~/Projects/InvestorClaw
openclaw gateway restart
```

The `--link` flag creates a symlink so updates (`git pull`) are reflected immediately without reinstalling.

### Skill removal

```bash
openclaw plugins uninstall investorclaw
openclaw gateway restart
```

### Exec session isolation (W0.1 – W0.3 and cleanup)

Agent `exec` sessions do **not** share filesystem context between calls. Artifacts written
in one exec call (e.g. a cloned repo) are invisible to a subsequent exec call.

**Consequence**: all installation workflow steps — clone/download (W0.1), dependency install
(W0.2), skill directory copy (W0.3), and cleanup — must be performed as direct Bash
operations by Claude, not delegated to the agent via exec sessions.

### Model string aliases (informational)

The config may store `xai/grok-4-1-fast-reasoning`; runtime/sessions may show
`xai/grok-4-1-fast`. Both resolve to the same model. The alias `grok-reasoning` also
resolves to it. Accept any of the three — do not flag as a mismatch.

## Compliance

⚠️ **NOT INVESTMENT ADVICE**: InvestorClaw provides educational analysis only. Not a substitute for professional financial advice. Does not assess personal risk tolerance, goals, or investment suitability.
