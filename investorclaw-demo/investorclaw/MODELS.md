# InvestorClaw — Tested Models and Benchmark Results

Harness: V6.1.2 | Runs: IC-RUN-20260413-002 through IC-RUN-20260414-004 | Last updated: 2026-04-14

---

## Mode Definitions

Understanding the distinction between these two modes is essential for reading the tables below.

### Hybrid mode (operational + consultation)

The operational LLM routes the session, runs tools, and frames the synthesis output. A separate **local consultation model** (`gemma4-consult` via a local Ollama endpoint) runs before synthesis and enriches each portfolio symbol with a structured analyst summary. The operational model receives compact enriched records, not raw data.

- Requires a local GPU host running Ollama with `gemma4-consult` (or a compatible model)
- Produces HMAC-fingerprinted synthesis records with `verbatim_required=true` and `is_heuristic=false`
- Enables the anti-fabrication controls: fingerprint chain, verbatim attribution, quote artifact
- **The local enrichment layer, not the operational model, is the primary driver of information density**

### Single-model mode (operational only, no consultation)

The operational LLM handles all routing, tool calls, and synthesis directly from heuristic analyst summaries. No local enrichment step. No fingerprint controls.

- Works with any capable cloud operational LLM
- No GPU or local inference required
- Lower information density on portfolios with many individual equities
- Still enforces guardrails and educational-only output

---

## Recommended Configurations

Four canonical configurations for regression testing. New harness runs should target these before expanding to the full model matrix.

> **RC vs. deployment Profiles are different things.** RC-1–RC-4 define the test matrix for regression — they are chosen to maximise harness coverage, not necessarily to match the README deployment recommendations. In particular: RC-2 uses GLM-5 hybrid (best consultation-delta model for testing), while README Profile 2 uses MiniMax-M2.7 hybrid (highest absolute hybrid QC4 for deployment). Both are valid hybrid configurations; they serve different purposes.

| # | Config | Mode | Model | Notes |
|---|--------|------|-------|-------|
| **RC-1** | Cloud-only default | Single | `together/MiniMaxAI/MiniMax-M2.7` | QC4=108; $0.30/$1.20/M; best price/QC4 ratio. Recommended for most users — no GPU required. |
| **RC-2** | Hybrid with audit controls | Hybrid | `together/zai-org/GLM-5` + `gemma4-consult` | QC4=86 (+16% over cloud-only). Best model where consultation adds net value — used as hybrid regression target. HMAC fingerprints, `is_heuristic=false`. |
| **RC-3** | Large portfolio / context | Hybrid | `xai/grok-4-1-fast` + `gemma4-consult` | Only 2M-context model. Hybrid QC4=52 (WF88). Use when context capacity or audit trail is the test focus. |
| **RC-4** | Budget / speed | Single | `groq/openai/gpt-oss-120b` | QC4=17; $0.15/$0.60/M; ~500 tok/s. ⚠️ `gpt-oss-20b` is FAIL (WF79) — do not use. |

> RC-1 is the primary regression target for all new feature work. RC-2 is the hybrid regression target. RC-3 only when context capacity or audit trail is the test focus. RC-4 for Groq-specific regression.

---

## Benchmark Scores — Harness V6.1.2

The harness runs 39 workflow checkpoints across 5 phases (W0–W8): holdings, analysis, performance, bonds, synthesis, lookup, export, guardrail validation. Scores below are measured on W6 synthesis output — the highest-value single response in a typical InvestorClaw session.

### Key findings

**Cross-step context injection (IC-RUN-20260414-003) closes most of the hybrid/single-model gap.** Before injection, the best single-model QC4 was ~40. After injection, `together/MiniMaxAI/MiniMax-M2.7` reaches QC4=108 — within 5% of the hybrid canonical best (QC4=113, WF39). For users without a local GPU, MiniMax-M2.7 is now a genuine alternative to the hybrid config.

**The hybrid config still leads on audit controls**, not synthesis density. `is_heuristic=false`, HMAC fingerprint chain, and verbatim attribution are exclusive to hybrid mode regardless of operational model. If those matter, hybrid is the right choice.

**`together/MiniMaxAI/MiniMax-M2.7` is the best price/QC4 ratio of any cloud-only model** at $0.011 per QC4-point (output). The next best is GLM-5 at $0.043/point — 4× worse value. MiniMax-M2.7 is the recommended default for users without local GPU infrastructure.

**Key finding (IC-RUN-20260414-003 hybrid addendum)**: Consultation does not uniformly improve synthesis density. MiniMax-M2.7 QC4 drops from 108 (cloud-only) to 97 (hybrid) — yet **MiniMax-M2.7 + gemma4-consult is the Profile 2 default** because it delivers the highest absolute hybrid QC4 under the current stack and is required for HMAC fingerprint chain and `is_heuristic=false` audit controls. Gemini-3.1-pro and GPT-OSS-120B regress under consultation; do not use them in hybrid mode. Models that gain from hybrid: Kimi-K2.5 (+49%), kimi-k2/groq (+40%), grok-4-1-fast (+33%), GLM-5 (+16%). The operational model's synthesis style, not just data richness, determines whether the consultation layer adds measurable value.

### Model all-stars

Rankings across synthesis quality, speed, guardrail adherence, and zero hallucinations (QC8=0). All PASS-verdict models scored zero fabricated portfolio facts.

#### Hybrid mode (consultation + operational LLM)

Full hybrid benchmark completed IC-RUN-20260414-003 addendum (WF87–WF94). **Current injection stack rankings** — grok WF39 is a pre-injection historical result and is listed separately.

| Rank | Configuration | QC3 | QC4 | QC5 | Notes |
|------|--------------|:---:|:---:|:---:|-------|
| 🥇 | `together/MiniMaxAI/MiniMax-M2.7` + `gemma4-consult` | **29** | **97** | **836** | WF87. **Profile 2 default.** Highest absolute hybrid QC4 under current stack. Preferred combo for audit-compliant deployments (HMAC fingerprint, `is_heuristic=false`). Cloud-only preferred when audit controls not required (QC4=108 vs hybrid QC4=97). |
| 🥈 | `together/zai-org/GLM-5` + `gemma4-consult` | 21 | 86 | 587 | WF90. Best model where consultation adds net value: +16% vs cloud-only (QC4=74→86). Structured table output, consistent account breakdown. |
| 🥉 | `together/moonshotai/Kimi-K2.5` + `gemma4-consult` | 24 | 82 | 579 | WF84. +49% vs cloud-only (QC4=55→82). Rich narrative, full bond analytics, news. |
| | `xai/grok-4-1-fast` + `gemma4-consult` | 20 | 52 | 564 | WF88. +33% vs cloud-only (WF85 QC4=39). Current injection stack re-baseline of historical WF39. |
| | `together/deepseek-ai/DeepSeek-V3.1` + `gemma4-consult` | 10 | 43 | 408 | WF89. Flat vs cloud-only (QC4=44→43). Consultation neutral. |
| | `google/gemini-3.1-pro-preview` + `gemma4-consult` | 15 | 38 | 259 | WF91. −17% vs cloud-only (QC4=46→38). Use cloud-only. |
| | `groq/moonshotai/kimi-k2-instruct-0905` + `gemma4-consult` | 11 | 35 | 201 | WF94. +40% vs cloud-only (QC4=25→35). Best Groq-served hybrid. ⚠️ preview endpoint. |
| | `openai/gpt-5.4` + `gemma4-consult` | 14 | 27 | 235 | WF92. Flat vs cloud-only (QC4=28→27). Consultation neutral. |
| | `xai/grok-4.20-0309-non-reasoning` + `gemma4-consult` | 14 | 17 | ~200 | WF74. Hybrid-only model — cloud-only FAIL (WF64, WF86). |
| ⚠️ do not hybrid | `groq/openai/gpt-oss-120b` + `gemma4-consult` | 11 | 8 | 237 | WF93. −53% vs cloud-only (QC4=17→8). Consultation severely interferes. |

**Historical record (pre-injection, not reproducible under current stack):** `xai/grok-4-1-fast` + `gemma4-consult` — QC4=113, QC5=1,184 (WF39). Re-baseline with current injection stack: QC4=52 (WF88). WF39 predates cross-step injection and cannot be compared directly against injection-era results.

> **Consultation benefit varies by model.** Gains: Kimi-K2.5 (+49%), kimi-k2/groq (+40%), grok-4-1-fast (+33%), GLM-5 (+16%). Neutral: DeepSeek, GPT-5.4. Harmful: MiniMax-M2.7 (−10%), Gemini (−17%), GPT-OSS-120b (−53%). The operational model's synthesis style, not just data richness, determines whether consultation data is expressed as citations.

#### Single-model (cloud-only, no consultation)

Rankings from IC-RUN-20260414-003 re-benchmark with cross-step context injection enabled.

| Rank | Model | QC3 | QC4 | QC5 | Speed | Run |
|------|-------|:---:|:---:|:---:|:-----:|-----|
| 🥇 | `together/MiniMaxAI/MiniMax-M2.7` | **27** | **108** | **541** | Together AI | WF82 — **top single-model overall** |
| 🥈 | `together/zai-org/GLM-5` | 20 | 74 | 481 | Together AI | WF83 |
| 🥉 | `together/moonshotai/Kimi-K2.5` | 16 | 55 | 256 | Together AI | WF76 |
| | `google/gemini-3.1-pro-preview` | 15 | 46 | 340 | Google | WF80 |
| | `together/deepseek-ai/DeepSeek-V3.1` | 13 | 44 | 160 | Together AI | WF75 |
| | `openai/gpt-5.4` | 14 | 28 | 178 | OpenAI | WF81 |
| | `groq/moonshotai/kimi-k2-instruct-0905` | 9 | 25 | 151 | ~800 tok/s | WF77 ⚠️ preview |
| | `groq/openai/gpt-oss-120b` | 19 | 17 | 376 | ~500 tok/s | WF78 — verbose but low metric density |
| 🚫 | `groq/openai/gpt-oss-20b` | — | — | — | — | WF79 — FAIL: malformed tool calls |
| | `xai/grok-4-1-fast` (cloud-only + injection) | 17 | 39 | 171 | xAI | WF85 — 6.5× vs WF72 (QC4=6→39); still below top-tier |
| 🚫 | `xai/grok-4.20-0309-non-reasoning` (cloud-only) | — | — | — | xAI | WF86 — FAIL: tool payload rejection. **Hybrid-only** (WF74 PASS in hybrid mode). |
| ⚠️ last | `xai/grok-4-1-fast` (cloud-only, pre-injection) | 0 | **6** | ~50 | xAI | WF72 — pre-injection baseline; **not recommended cloud-only** |

**Speed category winner**: `groq/openai/gpt-oss-120b` (~500 tok/s, production-stable; gpt-oss-20b excluded: FAIL WF79)  
**Value category winner**: `together/MiniMaxAI/MiniMax-M2.7` ($0.30/$1.20/M, 197K ctx — QC4=108 cloud-only, $0.011/QC4-point; use cloud-only, consultation hurts)  
**Synthesis quality winner (single-model)**: `together/MiniMaxAI/MiniMax-M2.7` (QC4=108, QC5=541 — full account tables, analyst, bond breakdown)  
**Profile 2 default (hybrid)**: `together/MiniMaxAI/MiniMax-M2.7` + `gemma4-consult` (QC4=97, WF87) — highest absolute hybrid QC4, preferred for audit-compliant deployments. Cloud-only QC4=108 is higher; use Profile 2 when HMAC fingerprint chain or `is_heuristic=false` controls are required.  
**Enterprise/high-context LLM (Profile 4)**: `xai/grok-4-1-fast` — 2M context, only model in this tier. Hybrid QC4=52 (WF88). Use for portfolios >500 holdings, non-compact mode >200 holdings, or extended multi-turn sessions. **Not recommended for standard portfolios** (cloud-only QC4=39 is mid-tier; MiniMax-M2.7 hybrid/cloud-only is higher synthesis density at smaller scale).  
**Not recommended hybrid**: `groq/openai/gpt-oss-120b` — hybrid QC4=8 (WF93) is 53% below cloud-only QC4=17 (WF78). Use cloud-only.  
**Hybrid-only models**: `xai/grok-4.20-0309-non-reasoning` — consistently fails cloud-only (WF64, WF86); passes only when consultation is enabled (WF74).

#### Guardrail compliance

All PASS models: **QC8=0** across W1–W8. Notable failure: `groq/qwen/qwen3-32b` (WF67, DEGRADED) — W7 generated explicit put option and trailing-stop recommendations without educational framing. Avoid for production use.

---

### Information density scores (W6 synthesis output)

Scores from runs where local consultation state was confirmed for the recorded mode.

| Metric | Combined WF39 | MiniMax-M2.7 WF82 | GPT-OSS-120B WF78 | grok-4-1-fast WF72 |
|--------|:-------------:|:-----------------:|:-----------------:|:------------------:|
| **QC3** Ticker mentions | **8** | **27** | 19 | 0 |
| **QC4** Metric citations | **113** | **108** | 17 | **6** |
| **QC5** Word count | **1,184** | **541** | 376 | ~50 |
| **QC8** `is_heuristic=false` | **✅** | ✗ | ✗ | ✗ |
| **QC10** Disclaimer instances | **2** | 2 | 2 | 2 |
| **QC13** Autonomous W6 prose | **✅** | ✅ | ✅ | ✅ |
| **Mode** | Hybrid | Single | Single | Single |
| **All commands pass** | ✅ | ✅ | ✅ | ✅ |

**WF39** = `xai/grok-4-1-fast-reasoning` + `gemma4-consult` (canonical combined configuration, intentional hybrid)  
**WF82** = `together/MiniMaxAI/MiniMax-M2.7` (IC-RUN-20260414-003, context injection enabled) — top single-model performer  
**WF78** = `groq/openai/gpt-oss-120b` (IC-RUN-20260414-003) — verbose but low metric density (QC4=17 vs QC4=108)  
**WF72** = `xai/grok-4-1-fast` cloud-only (CONSULTATION_ENABLED=false, ENDPOINT=localhost:0) — measured 19× lower QC4 vs hybrid WF39

Additional single-model runs (WF58–WF62) confirmed protocol compliance and tool-call stability for their respective models but were not scored against all 14 QC dimensions in the benchmark table above.

Phase 5 clean runs (WF63–WF71, IC-RUN-20260413-010) produced the following W6 synthesis density comparison:

| Model | QC3 | QC4 | QC5 | Mode | Result |
|-------|:---:|:---:|:---:|:----:|:------:|
| DeepSeek-V3.1 (WF68) | 16 | 35+ | 400 | Single | ✅ PASS |
| Kimi-K2.5 (WF66) | 13 | 40+ | 250 | Single | ✅ PASS |
| Kimi-K2.5 (WF71) | 17 | 18 | 350 | Hybrid | ✅ PASS |
| GLM-5 (WF70) | 3 | 26 | 130 | Single | ✅ PASS |
| MiniMax-M2.7 (WF69) | 1 | 14 | 150 | Single | ✅ PASS |
| Gemini-3.1-pro (WF65) | 4 | 17 | 104 | Single | ✅ PASS |
| qwen3-32b (WF67) | 6 | 10 | 60 | Single | ⚠️ DEGRADED |
| grok-4-1-fast (WF72) | 0 | 6 | ~50 | Single | ✅ PASS — lowest density; hybrid only |
| grok-4-1-fast (WF73) | 6 | 23 | ~110 | Hybrid+injection | ✅ PASS — 3.8× vs WF72 |
| grok-4.20 (WF74) | 14 | 17 | ~200 | Hybrid+injection | ✅ PASS — narrative prose, most tickers |

**Note on WF71 hybrid QC4**: Kimi-K2.5 in hybrid mode (WF71) produced narrative synthesis (QC4=18) lower than its single-model run (QC4=40+). Re-benchmarked in WF84 with cross-step context injection: QC4=82, QC5=579 — 4.6× improvement. The injection and model-tuning, not just consultation, drive hybrid density.

**IC-RUN-20260414-003** full re-benchmark (WF75–WF84) with context injection + verbose defaults across all 10 validated models:

| Model | QC3 | QC4 | QC5 | Mode | Result |
|-------|:---:|:---:|:---:|:----:|:------:|
| MiniMax-M2.7 (WF82) | 27 | **108** | 541 | Single | ✅ PASS — **#1 single-model overall** |
| GLM-5 (WF83) | 20 | 74 | 481 | Single | ✅ PASS |
| Kimi-K2.5 (WF84) | 24 | 82 | 579 | Hybrid | ✅ PASS — **4.6× over WF71** |
| Kimi-K2.5 (WF76) | 16 | 55 | 256 | Single | ✅ PASS |
| Gemini-3.1-pro (WF80) | 15 | 46 | 340 | Single | ✅ PASS — significant ↑ from WF65 (QC4=17→46) |
| DeepSeek-V3.1 (WF75) | 13 | 44 | 160 | Single | ✅ PASS |
| GPT-5.4 (WF81) | 14 | 28 | 178 | Single | ✅ PASS |
| Kimi-K2-0905/Groq (WF77) | 9 | 25 | 151 | Single | ✅ PASS ⚠️ preview |
| GPT-OSS-120B/Groq (WF78) | 19 | 17 | 376 | Single | ✅ PASS — verbose, low metric density |
| GPT-OSS-20B/Groq (WF79) | — | — | — | Single | 🚫 FAIL — malformed tool calls |

**Key IC-RUN-20260414-003 findings**:
- MiniMax-M2.7 jumps from WF69 QC4=14 to WF82 QC4=108 — a 7.7× improvement from context injection alone.
- GLM-5 jumps from WF70 QC4=26 to WF83 QC4=74 — 2.8×.
- Gemini 3.1 Pro jumps from WF65 QC4=17 to WF80 QC4=46 — 2.7×.
- grok-4-1-fast cloud-only jumps from WF72 QC4=6 to WF85 QC4=39 — 6.5×; still below top single-model tier.
- grok-4.20 cloud-only (WF86): FAIL — tool payload rejection. Confirms hybrid-only status (WF64+WF86 FAIL, WF74 PASS hybrid).
- GPT-OSS-20B (WF79) fails on tool calls — malformed `read<|channel|>commentary` call. Previously functional (WF59) at 250 words; current endpoint behavior incompatible.
- GPT-OSS-120B (WF78) remains functional but produces low metric density (QC4=17) despite high word count (376) — data-rich context is not being utilized for citations.

**IC-RUN-20260414-003 hybrid addendum** (WF87–WF94) — full hybrid coverage for all PASS single-model runs:

| Model | QC3 | QC4 | QC5 | Single QC4 | Δ | Result |
|-------|:---:|:---:|:---:|:----------:|:---:|:------:|
| MiniMax-M2.7 (WF87) | 29 | 97 | **836** | 108 | **-10%** | ✅ PASS — best hybrid current stack; single-model still higher |
| GLM-5 (WF90) | 21 | 86 | 587 | 74 | **+16%** | ✅ PASS — gains from consultation |
| Kimi-K2.5 (WF84) | 24 | 82 | 579 | 55 | **+49%** | ✅ PASS — strong hybrid gain (prior run) |
| grok-4-1-fast (WF88) | 20 | 52 | 564 | 39 | **+33%** | ✅ PASS — re-baseline WF39 (pre-injection QC4=113) with injection |
| DeepSeek-V3.1 (WF89) | 10 | 43 | 408 | 44 | **flat** | ✅ PASS — consultation neutral |
| Gemini-3.1-pro (WF91) | 15 | 38 | 259 | 46 | **-17%** | ✅ PASS — use cloud-only |
| kimi-k2-0905/Groq (WF94) | 11 | 35 | 201 | 25 | **+40%** | ✅ PASS — best groq-served hybrid |
| GPT-5.4 (WF92) | 14 | 27 | 235 | 28 | **flat** | ✅ PASS — consultation neutral |
| GPT-OSS-120B/Groq (WF93) | 11 | 8 | 237 | 17 | **-53%** | ✅ PASS — **do not use hybrid**; consultation severely interferes |

**Key hybrid addendum findings**:
- Consultation does not uniformly lift synthesis quality. 3 of 8 models regress (MiniMax, Gemini, GPT-OSS-120b). 2 are flat (DeepSeek, GPT-5.4).
- MiniMax-M2.7 single-model (QC4=108) remains the overall QC4 leader — its hybrid score (QC4=97) is lower. Confirmed: **use MiniMax-M2.7 cloud-only**.
- grok-4-1-fast WF39 (QC4=113) pre-dates cross-step injection. Re-baseline WF88 with injection yields QC4=52 — a 54% drop. The injection stack changes grok's output style (less table-dense, more narrative). WF39 is no longer a fair comparison point against injection-era results.
- GLM-5 is now the best hybrid model under the current injection stack (QC4=86, WF90), displacing Kimi-K2.5 (QC4=82, WF84).

---

### IC-RUN-20260414-004 — Phase 6: Deployment Mode × Heat Level Validation

Run date: 2026-04-14 | WF95–WF114 | Model under test: `together/MiniMaxAI/MiniMax-M2.7` (SI and FA, hybrid and single-model)

**Purpose**: Validate heat trajectory (levels 1–5), FA Dangerous Mode behavior, and SI vs FA single-model comparison under identical portfolio conditions.

#### Scorecard (WF95–WF114)

| Config | Mode | Heat range | Result | Notes |
|--------|------|:----------:|:------:|-------|
| SI hybrid (WF95–WF99) | `MiniMax-M2.7` + `gemma4-consult` | 1–5 | **5/5** ✅ | Perfect heat trajectory; alert escalation MEDIUM→OPPORTUNITY→HIGH_TARIFF. HMAC chain present. |
| FA Dangerous Mode hybrid (WF100–WF104) | `MiniMax-M2.7` + `gemma4-consult` | 1–5 | **5/5** ✅ | FA Dangerous Mode disclaimer active (ANSI red); ADVISORY guardrail; fiduciary framing. Alert escalation matches SI. |
| SI single-model (WF105–WF109) | `MiniMax-M2.7` | 1–5 | 1 FAIL / 4 Partial | WF105 (heat=1): no `ic_result` JSON block. Heat synthesis static; no escalation prose across levels. |
| FA single-model (WF110–WF114) | `MiniMax-M2.7` | 1–5 | **3/5** | FA fiduciary framing improves heat coherence vs SI single-model. No `ic_result` JSON block in any single-model run. |

**Key findings:**
- Hybrid mode (SI and FA) is production-ready for heat-level validation — all 10 hybrid runs pass with correct heat trajectories.
- Single-model mode has structural limitations: no `ic_result` JSON block, heat synthesis does not escalate in prose across levels. Known limitation, not a bug.
- FA single-model outperforms SI single-model: fiduciary framing from the FA ADVISORY guardrail produces more coherent heat trajectory language even without consultation.
- FA Dangerous Mode terminal output (ANSI red bordered disclaimer) works correctly across all FA runs.

#### Bug fixes shipped in IC-RUN-20260414-004

| ID | Description | File(s) | Fix |
|----|-------------|---------|-----|
| BUG-1 | `heat=5` max equity cap was 100%, exceeding the 95% guardrail intent | `commands/session_init.py` | `HEAT_LEVELS[5]['max_equity_pct']` changed 100 → 95 |
| BUG-2 | FA disclaimer not plumbed through heuristic path (5 files missing `deployment_mode`) | `commands/portfolio_analyzer.py`, `commands/analyze_performance_polars.py`, `commands/fixed_income_analysis.py`, `commands/bond_analyzer.py`, `providers/fetch_bond_data.py` | `deployment_mode` parameter propagated to all `DisclaimerWrapper.wrap_output()` and `wrap_and_save()` calls |
| BUG-3 | ACHR ticker retyped as ACHN in single-model synthesis prose | `commands/portfolio_analyzer.py` | Analyst output changed from inline text to JSON-per-line format; `TICKER_FIDELITY` instruction added to prevent LLM from re-spelling ticker symbols |

#### FA Dangerous Mode (new in IC-RUN-20260414-004)

`fa_professional` deployment mode now surfaces as **"FA Professional — Dangerous Mode"** throughout the system:

- **Terminal**: ANSI bright-red (`\033[91m`) bordered disclaimer block with 5-point expanded risk disclosure
- **JSON output**: `fa_risk_disclosure` and `deployment_mode: "fa_professional"` fields added to all wrapped outputs
- **Setup wizard**: Mode 2 panel updated with Dangerous Mode warning and fiduciary language
- **`config/deployment_modes.py`**: display name → `"Financial Advisor — Dangerous Mode"`
- **`config/guardrail_enforcer.py`**: inline disclaimer updated with advisory/fiduciary framing

---

## Full Test Run Catalog

### Passing and degraded runs (produced usable W6 synthesis)

| Run | Model | Mode | Consultation | Result |
|-----|-------|------|:------------:|:------:|
| **WF39** | `xai/grok-4-1-fast-reasoning` + `gemma4-consult` | Hybrid | ✅ | ✅ PASS — canonical combined config |
| WF62 | `xai/grok-4-1-fast` (regression verification) | Hybrid | ✅ | ✅ PASS |
| True baseline | `xai/grok-4-1-fast-reasoning` | Single | ✗ | ✅ PASS — reference for cloud-only |
| WF46 | `groq/openai/gpt-oss-120b` | Single | — | ✅ PASS |
| WF58 | `groq/moonshotai/kimi-k2-instruct-0905` | Single | — | ✅ PASS ⚠️ preview model |
| WF59 | `groq/openai/gpt-oss-20b` | Single | — | ✅ PASS |
| WF60 | `together/moonshotai/Kimi-K2.5` | Single | — | ✅ PASS |
| WF61 | `together/Qwen/Qwen3-235B-A22B-Instruct-2507-tput` | Single | ✗ | ✅ PASS |
| WF63 | `openai/gpt-5.4` | Single | — | ✅ PASS (clean confirmed single-model; W7 questionnaire loop) |
| WF65 | `google/gemini-3.1-pro-preview` | Single | — | ✅ PASS (W7 questionnaire loop; QC5~104 words; QC10=1) |
| WF66 | `together/moonshotai/Kimi-K2.5` (clean re-run) | Single | — | ✅ PASS (QC3=13, QC4=40+, QC5=250; strong synthesis) |
| WF68 | `together/deepseek-ai/DeepSeek-V3.1` | Single | — | ✅ PASS (QC3=16, QC4=35+, QC5=400; top single-model performer) |
| WF69 | `together/MiniMaxAI/MiniMax-M2.7` | Single | — | ✅ PASS (QC3=1, QC4=14, QC5=150; economical) |
| WF70 | `together/zai-org/GLM-5` | Single | — | ✅ PASS (QC3=3, QC4=26, QC5=130; clean compliance) |
| WF71 | `together/moonshotai/Kimi-K2.5` + `gemma4-consult` | Hybrid | ✅ | ✅ PASS (215 SVG cards, HMAC fingerprints, is_heuristic=false) |
| WF72 | `xai/grok-4-1-fast` (cloud-only baseline) | Single | — | ✅ PASS (QC3=0, QC4=6, QC5≈50; lowest density; not recommended cloud-only) |
| WF73 | `xai/grok-4-1-fast` (hybrid, context injection) | Hybrid | ✅ | ✅ PASS (QC3=6, QC4=23, QC5≈110; 3.8× improvement vs WF72 cloud-only) |
| WF74 | `xai/grok-4.20-0309-non-reasoning` (hybrid, re-test) | Hybrid | ✅ | ✅ PASS — UPGRADED from WF64 DEGRADED; W4/W5 tool rejection was transient. QC3=14, QC4=17, QC5≈200 |
| WF75 | `together/deepseek-ai/DeepSeek-V3.1` (re-benchmark) | Single | — | ✅ PASS (QC3=13, QC4=44, QC5=160) |
| WF76 | `together/moonshotai/Kimi-K2.5` (re-benchmark) | Single | — | ✅ PASS (QC3=16, QC4=55, QC5=256) |
| WF77 | `groq/moonshotai/kimi-k2-instruct-0905` (re-benchmark) | Single | — | ✅ PASS (QC3=9, QC4=25, QC5=151) ⚠️ preview |
| WF78 | `groq/openai/gpt-oss-120b` (re-benchmark) | Single | — | ✅ PASS (QC3=19, QC4=17, QC5=376) — verbose, low metric density |
| WF79 | `groq/openai/gpt-oss-20b` (re-benchmark) | Single | — | 🚫 FAIL — malformed tool call `read<|channel|>commentary` |
| WF80 | `google/gemini-3.1-pro-preview` (re-benchmark) | Single | — | ✅ PASS (QC3=15, QC4=46, QC5=340) — significant ↑ from WF65 |
| WF81 | `openai/gpt-5.4` (re-benchmark) | Single | — | ✅ PASS (QC3=14, QC4=28, QC5=178) |
| WF82 | `together/MiniMaxAI/MiniMax-M2.7` (re-benchmark) | Single | — | ✅ PASS (QC3=27, QC4=108, QC5=541) — **#1 single-model overall** |
| WF83 | `together/zai-org/GLM-5` (re-benchmark) | Single | — | ✅ PASS (QC3=20, QC4=74, QC5=481) |
| WF84 | `together/moonshotai/Kimi-K2.5` + `gemma4-consult` (re-benchmark) | Hybrid | ✅ | ✅ PASS (QC3=24, QC4=82, QC5=579) — 4.6× over WF71 |
| WF85 | `xai/grok-4-1-fast` cloud-only + injection (gap-close) | Single | — | ✅ PASS (QC3=17, QC4=39, QC5=171) — 6.5× vs WF72 pre-injection |
| WF86 | `xai/grok-4.20-0309-non-reasoning` cloud-only (gap-close) | Single | — | 🚫 FAIL — tool payload rejection. Confirmed hybrid-only (WF74 PASS, WF64+WF86 FAIL). |
| WF87 | `together/MiniMaxAI/MiniMax-M2.7` + `gemma4-consult` | Hybrid | ✅ | ✅ PASS (QC3=29, QC4=97, QC5=836) — best hybrid current stack; single-model QC4=108 is higher |
| WF88 | `xai/grok-4-1-fast` + `gemma4-consult` (injection re-baseline) | Hybrid | ✅ | ✅ PASS (QC3=20, QC4=52, QC5=564) — re-baseline of WF39 with injection; 33% gain vs WF85 cloud-only |
| WF89 | `together/deepseek-ai/DeepSeek-V3.1` + `gemma4-consult` | Hybrid | ✅ | ✅ PASS (QC3=10, QC4=43, QC5=408) — flat vs single-model (QC4=44); consultation neutral |
| WF90 | `together/zai-org/GLM-5` + `gemma4-consult` | Hybrid | ✅ | ✅ PASS (QC3=21, QC4=86, QC5=587) — **best hybrid current stack** (displaces Kimi WF84); +16% vs single |
| WF91 | `google/gemini-3.1-pro-preview` + `gemma4-consult` | Hybrid | ✅ | ✅ PASS (QC3=15, QC4=38, QC5=259) — regresses vs single-model (QC4=46→38); use cloud-only |
| WF92 | `openai/gpt-5.4` + `gemma4-consult` | Hybrid | ✅ | ✅ PASS (QC3=14, QC4=27, QC5=235) — flat vs single-model (QC4=28); consultation neutral |
| WF93 | `groq/openai/gpt-oss-120b` + `gemma4-consult` | Hybrid | ✅ | ✅ PASS (QC3=11, QC4=8, QC5=237) — severe regression (QC4=17→8, -53%); **do not use hybrid** |
| WF94 | `groq/moonshotai/kimi-k2-instruct-0905` + `gemma4-consult` | Hybrid | ✅ | ✅ PASS (QC3=11, QC4=35, QC5=201) — gains +40% vs single-model (QC4=25→35); best groq-served hybrid |

### Awaiting full QC benchmark

All runs completed through IC-RUN-20260414-003 hybrid addendum (WF87–WF94). No models remain in pending-benchmark status.

Previously listed models and their final verdicts:

| Model | Final Verdict | Run |
|-------|:-------------:|-----|
| `openai/gpt-5.4` | ✅ PASS | WF63 |
| `xai/grok-4.20-0309-non-reasoning` | ✅ PASS (upgraded WF64→WF74) | WF74 |
| `google/gemini-3.1-pro-preview` | ✅ PASS | WF65 |
| `together/moonshotai/Kimi-K2.5` (single) | ✅ PASS | WF66 |
| `together/moonshotai/Kimi-K2.5` (hybrid) | ✅ PASS | WF71 |
| `groq/qwen/qwen3-32b` | ⚠️ DEGRADED | WF67 |
| `together/deepseek-ai/DeepSeek-V3.1` | ✅ PASS | WF68 |
| `together/MiniMaxAI/MiniMax-M2.7` | ✅ PASS | WF69 |
| `together/zai-org/GLM-5` | ✅ PASS | WF70 |

### Partial / not viable (tool calls work but impractical)

| Run | Model | Reason |
|-----|-------|--------|
| WF47 | `together/Qwen/Qwen3-235B-A22B-Thinking-2507` | PARTIAL/TIMEOUT — tool calls execute correctly; 5–10 min/step; full harness ~2–3 hrs; not viable for interactive sessions |

### Degraded

| Run | Model | Reason |
|-----|-------|--------|
| WF53 | `together/MiniMaxAI/MiniMax-M2.5` | `/portfolio synthesize` not recognized; W5 news non-functional — use M2.7 instead |
| ~~WF64~~ | ~~`xai/grok-4.20-0309-non-reasoning`~~ | **Superseded by WF74 (PASS).** WF64 W4/W5 tool rejection was transient model-version behavior. Re-tested WF74: all W0–W8 pass cleanly, QC3=14, QC4=17, QC5≈200. |
| WF67 | `groq/qwen/qwen3-32b` | `/portfolio update-identity` not recognized; W6 thin synthesis (~60 words) with file pointer; W7 offered specific put option/trailing-stop recommendations without educational framing (guardrail issue); preview model |

### Blocked (cannot execute tool calls at all)

| Run | Model | Reason |
|-----|-------|--------|
| WF49 | `together/deepseek-ai/DeepSeek-R1-0528` | Tool-text incompatibility — outputs tool name as code block, not a function call |
| WF50 | `together/meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8` | Tool payload rejected by Together AI serverless endpoint |
| WF51 | `together/meta-llama/Llama-4-Scout-17B-16E-Instruct` | Tool payload rejected (Groq variant runs but is degraded) |
| WF52 | `together/moonshotai/Kimi-K2-Thinking` | Tool payload rejected — thinking variant not tool-call compatible |
| WF56 | `together/zai-org/GLM-4.7` | Tool payload rejected — GLM-5 works; GLM-4.7 does not |
| WF57 | `together/Qwen/Qwen3-Next-80B-A3B-Instruct` | Tool payload rejected — MoE 80B variant not compatible |

---

## Context Window Comparison

Context window capacity is a separate model selection axis from synthesis quality (QC4). For the current 215-holding portfolio in compact mode, context is not the bottleneck — models are using 17–34K tokens, well within every supported model's limit. Context becomes the decisive dimension as portfolio size, session length, or enrichment depth increases.

### Context tiers

| Tier | Models | Context | When this tier matters |
|------|--------|--------:|------------------------|
| **Tier 1: 2M** | `xai/grok-4-1-fast` | ~2,000K | Only model in this tier. 8–15× capacity advantage over all others. Comfortable for any non-compact, enterprise-scale, or extended-session scenario. |
| **Tier 2: ~1M** | `xai/grok-4.20-0309-non-reasoning`, `google/gemini-3.1-pro-preview` | ~977K–1M | Ample for non-compact mode; handles large portfolios and multi-turn accumulation. |
| **Tier 3: 262–272K** | `openai/gpt-5.4`, `together/moonshotai/Kimi-K2.5`, `groq/moonshotai/kimi-k2-instruct-0905` | 262–272K | Adequate for large compact-mode sessions; tight under non-compact with full enrichment. |
| **Tier 4: 197–203K** | `together/MiniMaxAI/MiniMax-M2.7`, `together/zai-org/GLM-5` | 197–203K | Fine for typical compact sessions; not recommended for non-compact with >150 enriched symbols. |
| **Tier 5: 128–131K** | `together/deepseek-ai/DeepSeek-V3.1`, `groq/openai/gpt-oss-120b`, `groq/openai/gpt-oss-20b` | 128–131K | Smallest working tier. Sufficient for the 215-holding compact benchmark; marginal for enriched or extended sessions. |

### Portfolio token utilization (reference)

| Scenario | Estimated tokens | Fits in tier 3+? | Fits in tier 4+? | Fits in tier 5? |
|----------|----------------:|:----------------:|:----------------:|:---------------:|
| 215 holdings, compact mode (benchmark) | ~17–34K | ✅ | ✅ | ✅ |
| W1 raw output alone, non-compact | ~72K | ✅ | ✅ | ✅ |
| Full enriched session (215 symbols) | ~80–120K | ✅ | ✅ | ⚠️ tight |
| Large portfolio, non-compact (500 holdings) | ~300–400K | ✅ | ❌ | ❌ |
| Enterprise portfolio + long session (1000+ holdings) | ~1M+ | ✅ (Gemini) | ❌ | ❌ |

### Takeaway: where grok-4-1-fast fits on context

`xai/grok-4-1-fast` is the **only model in the 2M tier** — a unique capacity advantage that no current Together AI, Groq, or OpenAI option comes close to. For the standard 215-holding compact-mode benchmark, this advantage is invisible (all models have headroom). It becomes the decisive factor when:

- Running non-compact mode at scale (raw W-step data exhausts smaller-context models)
- Scaling to enterprise-size portfolios (500–1000+ positions)
- Multi-turn sessions where accumulated history approaches model limits
- Maximizing enrichment density without context truncation risk

grok-4-1-fast is the **Profile 4 LLM — use it when context capacity is the binding constraint**, not as a general operational default. For standard portfolios (≤200 holdings non-compact, ≤500 compact), MiniMax-M2.7 (Profile 1/2) delivers higher synthesis density at lower cost. When portfolios scale beyond those thresholds, grok-4-1-fast's 2M context window becomes the decisive factor regardless of synthesis score. Consultation is required: hybrid QC4=52 (WF88, +33% vs cloud-only QC4=39 WF85).

---

## Provider Model Catalog

### xAI (Grok)

| Model | Context | Benchmark | Notes |
|-------|---------|:---------:|-------|
| `xai/grok-4-1-fast` | ~2M | ✅ WF39/WF62/WF72/WF85/WF88 | **Enterprise/high-context LLM (Profile 4).** The only model in the 2M context tier — use when portfolio exceeds ~200 holdings (non-compact) or ~500 holdings (compact), or when accumulated session history risks truncation. **Context capacity is the selection reason, not synthesis quality.** Hybrid (WF88): QC4=52. Cloud-only (WF85): QC4=39 — mid-tier; consultation required. Not recommended as general default for standard portfolios (use MiniMax-M2.7). |
| `xai/grok-4.20-0309-non-reasoning` | ~1M | ⚠️ WF74 PASS (hybrid only) / 🚫 WF86 FAIL (cloud-only) | **Hybrid-only.** Cloud-only consistently fails with tool payload rejection (WF64, WF86). Passes only with consultation enabled (WF74: QC3=14, QC4=17, QC5≈200, narrative prose style). Do not use cloud-only. |

### OpenAI

| Model | Context | Benchmark | Notes |
|-------|---------|:---------:|-------|
| `openai/gpt-5.4` | ~272K | ✅ WF63/WF81 | PASS — re-benchmarked WF81: QC3=14, QC4=28, QC5=178. W7 questionnaire loop (same as Gemini/Kimi-K2.5). 272K context is smallest among frontier models. |

### Google

| Model | Context | Benchmark | Notes |
|-------|---------|:---------:|-------|
| `google/gemini-3.1-pro-preview` | ~1M | ✅ WF65/WF80 | PASS — re-benchmarked WF80: QC3=15, QC4=46, QC5=340. Significant improvement from context injection (WF65: QC4=17→WF80: QC4=46). W7 questionnaire loop; QC10=1. Emoji-decorated output. |

### Together AI

| Model | Context | Benchmark | Notes |
|-------|---------|:---------:|-------|
| `together/moonshotai/Kimi-K2.5` | 262K | ✅ WF60/WF66/WF76 (single) / ✅ WF71/WF84 (hybrid) | Single WF76: QC3=16, QC4=55, QC5=256. Hybrid WF84: QC3=24, QC4=82, QC5=579 — **#3 hybrid overall** (WF87–WF94 stack); 4.6× over WF71. 262K context fits large compact-mode sessions. W7 questionnaire loop in both modes. |
| `together/deepseek-ai/DeepSeek-V3.1` | 131K | ✅ WF68/WF75 | PASS — re-benchmarked WF75: QC3=13, QC4=44, QC5=160. $0.60/$1.70/M. |
| `together/MiniMaxAI/MiniMax-M2.7` | 197K | ✅ WF69/WF82 | PASS — re-benchmarked WF82: QC3=27, QC4=108, QC5=541. **#1 single-model overall** with context injection. $0.30/$1.20/M — best value of all top performers. |
| `together/zai-org/GLM-5` | 203K | ✅ WF70/WF83 | PASS — re-benchmarked WF83: QC3=20, QC4=74, QC5=481. Excellent context utilization; rich account breakdown. $1.00/$3.20/M. |
| `together/Qwen/Qwen3-235B-A22B-Instruct-2507-tput` | 262K | ✅ WF61 (single) | ~300-word synthesis; 60k/262k context use. |
| `together/MiniMaxAI/MiniMax-M2.5` | — | ⚠️ DEGRADED | `/portfolio synthesize` not recognized; W5 news non-functional — use M2.7 instead. |
| `together/Qwen/Qwen3-235B-A22B-Thinking-2507` | — | ⚠️ PARTIAL | Tool calls work; 5–10 min/step — not viable for interactive sessions. |
| `together/deepseek-ai/DeepSeek-R1-0528` | — | 🚫 BLOCKED | Outputs tool name as text code block, not a function call. |
| `together/meta-llama/Llama-4-Maverick-17B-128E-Instruct-FP8` | — | 🚫 BLOCKED | Tool payload rejected by Together AI serverless. |
| `together/meta-llama/Llama-4-Scout-17B-16E-Instruct` | — | 🚫 BLOCKED | Tool payload rejected (Together AI variant). |
| `together/moonshotai/Kimi-K2-Thinking` | — | 🚫 BLOCKED | Thinking variant not tool-call compatible. |
| `together/zai-org/GLM-4.7` | — | 🚫 BLOCKED | GLM-5 works; GLM-4.7 does not. |
| `together/Qwen/Qwen3-Next-80B-A3B-Instruct` | — | 🚫 BLOCKED | MoE 80B variant not tool-call compatible. |

### Groq

Fast inference (500–1000 tok/s) at low cost. 128K context limits to small-to-medium portfolios — not suitable for large multi-account or fully-enriched sessions.

| Model | Context | Benchmark | Notes |
|-------|---------|:---------:|-------|
| `groq/openai/gpt-oss-120b` | 128K | ✅ WF46/WF78 | **Recommended Groq option.** Re-benchmarked WF78: QC3=19, QC4=17, QC5=376 — verbose but low metric density. $0.15/$0.60/M; 500 tok/s. Production-stable. |
| `groq/openai/gpt-oss-20b` | 128K | ✅ WF59 / 🚫 WF79 | WF79 FAIL: malformed tool call `read<|channel|>commentary`. Previously functional (WF59). Current endpoint behavior incompatible — do not use. $0.075/$0.30/M. |
| `groq/moonshotai/kimi-k2-instruct-0905` | 262K | ✅ WF58/WF77 ⚠️ | Re-benchmarked WF77: QC3=9, QC4=25, QC5=151. **Preview tier — not production-stable; may be discontinued without notice.** |
| `groq/qwen/qwen3-32b` | 128K | ⚠️ WF67 DEGRADED | `/portfolio update-identity` not recognized; W6 thin synthesis (~60 words) with file pointer; W7 offered specific investment recommendations without educational framing (guardrail issue). Preview model. |
| `groq/meta-llama/llama-4-scout-17b-16e-instruct` | 128K | ⚠️ DEGRADED | Requires extra prompt step for W6 prose; heat_level type error; preview model. |
| `groq/moonshotai/kimi-k2-instruct` | 128K | ⚠️ DEGRADED | Thin synthesis (~144 words); undocumented endpoint. |
| `groq/llama-3.3-70b-versatile` | 128K | 🚫 DO NOT USE | Config corruption risk — wrote unauthorized keys into `openclaw.json` during testing. |

> **Groq stability note**: Production-stable models confirmed in official Groq docs: `llama-3.1-8b-instant`, `openai/gpt-oss-120b`, `openai/gpt-oss-20b`. Preview/beta models (`qwen3-32b`, `llama-4-scout`, `kimi-k2-instruct-0905`) can be discontinued without notice.

---

## Together AI Tool-Call Compatibility

Not all Together AI serverless models support OpenAI function-calling schema. InvestorClaw requires tool execution — models that reject tool payloads cannot complete the workflow.

| Works (tool-call compatible) | Blocked (rejects tool payload) | Incompatible (text output only) |
|------------------------------|-------------------------------|----------------------------------|
| DeepSeek-V3.1 | Llama-4-Maverick FP8 | DeepSeek-R1-0528 (tool name as code block) |
| MiniMax-M2.5 / M2.7 | Llama-4-Scout | — |
| GLM-5 | GLM-4.7 | — |
| Kimi-K2.5 | Qwen3-Next-80B | — |
| Qwen3-235B-Instruct-tput | Kimi-K2-Thinking | — |
| Qwen3-235B-Thinking* | — | — |

*Qwen3-235B-Thinking makes tool calls correctly but takes 5–10 min per response step — not viable for interactive harness runs.

---

## Anti-Fabrication Properties (Hybrid Mode Only)

The tier-3 enrichment path adds audit controls that no single-model configuration provides:

- **HMAC fingerprint chain** — each enriched record gets a 16-character hex fingerprint; the session accumulates a chained fingerprint across all enriched symbols for post-hoc verification
- **`verbatim_required=true` + attribution** — enriched analyst quotes carry a verbatim flag and source attribution; the synthesis layer is constrained to cite rather than paraphrase
- **`is_heuristic=false`** — signals that synthesis was produced from enriched model inference, not keyword matching
- **`synthesis_instruction`** — machine-readable citation directive injected into the compact analyst payload; tells the operational LLM to cite synthesis verbatim with fingerprint included

These controls are absent in all single-model configurations regardless of model capability.

---

## Consultation Model Catalog (Local Ollama)

Tested on the inference host (RTX 4500 Ada 24 GB VRAM, Ollama 0.20.3).

| Model | tok/s | VRAM | Notes |
|-------|------:|-----:|-------|
| `gemma4-consult` | ~65 | 9.6 GB | **Recommended** — tuned gemma4:e4b; optimized for consultative Q&A (num_ctx=4096, num_predict=1200, up to 400 words per symbol) |
| `gemma4:e4b` | ~66 | 9.6 GB | Base model; good quality/speed tradeoff; 128K context |
| `gemma4:e2b` | ~99 | 7.2 GB | Fastest; suitable for lighter tasks |
| `nemotron-3-nano:30b-a3b-q4_K_M` | ~25 | 24 GB | High-quality fallback; requires full VRAM |
| `qwen2.5:14b-instruct-q4_K_M` | ~45 | 9.0 GB | Code and structured output |

Create `gemma4-consult`:
```bash
ollama create gemma4-consult -f docs/gemma4-consult.Modelfile
```

Run `/portfolio ollama-setup` to auto-detect available models on your endpoint.

---

## Reproducibility

The full test harness is at `investorclaw_harness_v612.txt` in the repository root.

```bash
# Prerequisites
# - OpenClaw gateway running with investorclaw plugin loaded
# - (Optional) local Ollama host at INVESTORCLAW_CONSULTATION_ENDPOINT
# - Portfolio CSVs in INVESTOR_CLAW_PORTFOLIO_DIR
# - .env copied to workspace: cp ~/Projects/InvestorClaw/.env ~/.openclaw/workspace/skills/investorclaw/.env

# Covers 39 workflow checkpoints across 5 phases (W0–W8)
```

### Critical: consultation is controlled by the project .env, not the workspace .env

InvestorClaw loads from the registered plugin path (`~/Projects/InvestorClaw/dist/index.js`, origin: "config"), not from the OpenClaw workspace skill directory. This means:

- **`~/Projects/InvestorClaw/.env`** is the authoritative consultation config — changes here take effect after gateway restart.
- **`~/.openclaw/workspace/skills/investorclaw/.env`** affects only the background enricher subprocess when it does NOT inherit the parent process environment. Setting `INVESTORCLAW_CONSULTATION_ENABLED=false` in the workspace `.env` has **no effect** on the plugin loaded from the project directory.

To disable consultation for a clean single-model benchmark run:
```bash
# Edit ~/Projects/InvestorClaw/.env
INVESTORCLAW_CONSULTATION_ENABLED=false
INVESTORCLAW_CONSULTATION_ENDPOINT=http://localhost:0   # unreachable — belt-and-suspenders
```

No gateway restart required — the OpenClaw gateway hot-reloads `openclaw.json` model config changes. For clean runs, **delete the session** rather than restarting the gateway:

```python
# Delete the session from ~/.openclaw/sessions/sessions.json before each run
import json
from pathlib import Path
store = Path.home() / ".openclaw/sessions/sessions.json"
data = json.loads(store.read_text())
data.pop("agent:main:explicit:<session-id>", None)
store.write_text(json.dumps(data, indent=2))
```

Then run with a fresh session ID — the hot-reloaded model config takes effect immediately. The IC-RUN-20260414-003 batch (WF75–WF84) used this approach: no gateway restarts across 10 sequential runs.

This finding (DEV-003, discovered IC-RUN-20260413-010) invalidated the 9 earlier Phase 5 benchmark runs (WF36–WF41, WF48, WF53–WF55) that had attempted to disable consultation via workspace `.env` modifications. All 9 were re-run cleanly in WF63–WF71.
