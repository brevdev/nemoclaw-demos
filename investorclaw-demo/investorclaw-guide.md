# InvestorClaw — Portfolio Analysis and Market Intelligence for OpenClaw

InvestorClaw is a production-grade portfolio analysis skill for OpenClaw agents. It reads broker CSV exports, fetches live market data, and runs multi-step analysis pipelines covering holdings, performance, bond analytics, analyst consensus, news correlation, and end-of-day reporting — all with built-in financial guardrails that enforce educational-only output.

This guide walks through installing InvestorClaw on a NemoClaw system and running your first analysis session.

---

## Prerequisites

| Requirement | Details |
|-------------|---------|
| NemoClaw | Installed and validated (`openclaw gateway status` returns healthy) |
| Python 3.9+ | Available in the sandbox (`python3 --version`) |
| Portfolio CSV | Exported from your broker (Fidelity, Schwab, Vanguard, IBKR, and others auto-detected) |
| API keys | Optional — falls back to `yfinance` automatically if none are set |
| Ollama (optional) | Required only for local LLM consultation (see [Local Consultation](#local-consultation-optional)) |

---

## Installation

### 1. Clone the skill

```bash
git clone https://github.com/perlowja/InvestorClaw.git ~/Projects/InvestorClaw
```

### 2. Install Python dependencies

```bash
pip install -r ~/Projects/InvestorClaw/requirements.txt
```

### 3. Register with OpenClaw

```bash
openclaw plugins install --link ~/Projects/InvestorClaw
openclaw gateway restart
```

The `--link` flag creates a symlink so `git pull` updates are reflected immediately without reinstalling.

### 4. Configure API keys (optional)

Copy the example env file and add any keys you have:

```bash
cp ~/Projects/InvestorClaw/.env.example ~/Projects/InvestorClaw/.env
```

Without any keys, InvestorClaw uses `yfinance` as the price provider — no registration required. With keys, it uses a fallback chain (Finnhub → Massive → Alpha Vantage → yfinance) for better reliability and richer data.

### 5. Verify installation

```bash
python3 ~/Projects/InvestorClaw/tests_smoke.py
```

All 18 checks should pass. If any fail, check that dependencies installed correctly and the gateway restarted.

---

## First-Run Setup

Before running analysis commands, point InvestorClaw at your portfolio files:

```bash
/portfolio setup
```

This scans common broker export locations, auto-detects the format (CSV, PDF, multi-account), and writes a configuration file. If your CSV is in a non-standard location, you can specify it:

```bash
INVESTOR_CLAW_PORTFOLIO_DIR=~/my-exports /portfolio setup
```

---

## Running an Analysis

Commands are invoked via the `/portfolio` prefix through the OpenClaw agent. The recommended first session:

```
/portfolio holdings
/portfolio performance
/portfolio analyst
/portfolio synthesize
```

Each step builds context for the next. Holdings loads live prices and calculates position values. Performance computes returns and drawdown. Analyst fetches consensus ratings. Synthesize runs multi-factor analysis across all prior outputs and produces a narrative synthesis.

To generate an end-of-day HTML summary report:

```
/portfolio eod --no-email
```

The report is written to `~/portfolio_reports/eod_report.html`. To schedule daily email delivery:

```bash
python3 ~/Projects/InvestorClaw/setup/eod_scheduler.py --install
```

---

## Model Configuration

Set your operational model in `~/.openclaw/openclaw.json`. Recommended configurations:

**Profile 1 — Cloud-only (recommended default, no GPU required)**
```json
{ "agents": { "defaults": { "model": { "primary": "together/MiniMaxAI/MiniMax-M2.7" } } } }
```

**Profile 2 — Hybrid with local GPU (audit controls + HMAC provenance)**
```json
{ "agents": { "defaults": { "model": { "primary": "together/MiniMaxAI/MiniMax-M2.7" } } } }
```
Plus in `.env`:
```bash
INVESTORCLAW_CONSULTATION_ENABLED=true
INVESTORCLAW_CONSULTATION_MODEL=gemma4-consult
INVESTORCLAW_CONSULTATION_ENDPOINT=http://localhost:11434
```

**Profile 3 — Budget / fast (Groq)**
```json
{ "agents": { "defaults": { "model": { "primary": "groq/openai/gpt-oss-120b" } } } }
```

> InvestorClaw requires a model with adequate context and tool-routing capability. Without an explicit model set, OpenClaw uses its installation default, which may be insufficient for reliable plugin routing.

---

## Commands Reference

| Command | What it does |
|---------|-------------|
| `/portfolio setup` | Auto-detect and configure portfolio files |
| `/portfolio holdings` | Live holdings snapshot with current prices |
| `/portfolio performance` | Returns, drawdown, and performance metrics |
| `/portfolio bonds` | Bond analytics: YTM, duration, FRED benchmarks |
| `/portfolio analyst` | Analyst consensus ratings and coverage |
| `/portfolio news` | News correlation across holdings |
| `/portfolio synthesize` | Multi-factor synthesis across all data |
| `/portfolio eod` | End-of-day HTML summary report |
| `/portfolio session` | Initialize risk profile for the session |
| `/portfolio lookup <TICKER>` | Single-symbol detail lookup |
| `/portfolio guardrails` | Check guardrail status |
| `/portfolio run` | Full pipeline: holdings → performance → analyst → synthesize → export |

Output files go to `~/portfolio_reports/`. Add `--verbose` to any command for full detail.

---

## Local Consultation (Optional)

The consultation layer enriches per-symbol analyst data locally using a tuned Ollama model before the cloud operational model sees the result. This is the primary driver of synthesis quality.

**Hardware requirement**: ~10 GB VRAM (RTX 3080 class or better, or Apple Silicon with 16 GB+ unified memory). Ollama >= 0.20.x.

Create the tuned model:

```bash
ollama create gemma4-consult -f ~/Projects/InvestorClaw/docs/gemma4-consult.Modelfile
```

Enable in `.env`:

```bash
INVESTORCLAW_CONSULTATION_ENABLED=true
INVESTORCLAW_CONSULTATION_ENDPOINT=http://localhost:11434
INVESTORCLAW_CONSULTATION_MODEL=gemma4-consult
```

Run `/portfolio ollama-setup` to auto-detect available models on your endpoint and verify connectivity.

---

## Edge Deployment (Raspberry Pi)

InvestorClaw runs on a Raspberry Pi 4 with 8 GB RAM using standard OpenClaw. For 2 GB Pi deployment using the Zeroclaw lightweight runtime, see the embedded test harness at `investorclaw/investorclaw_harness_v620_embedded.txt`.

---

## Privacy and Security

- Broker CSV data is **never sent to external APIs** — only computed summaries reach the cloud model
- PII (account numbers, SSNs) is scrubbed from CSV columns on load
- Raw portfolio artifacts are stored locally at `~/portfolio_reports/.raw/`
- The skill will not give investment advice — guardrails enforce educational-only output at all times

---

## Further Reading

- [Full documentation and Config Profiles](investorclaw/README.md)
- [Model testing results and benchmark scores](investorclaw/MODELS.md)
- [Architecture overview](investorclaw/ARCHITECTURE.md)
- [FINOS CDM 5.x compliance](investorclaw/README.md#compliance)
