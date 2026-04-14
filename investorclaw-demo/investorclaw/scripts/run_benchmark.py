#!/usr/bin/env python3
"""
IC-RUN-20260414-003 — Automated benchmark runner for WF75–WF88.
Switches openclaw default model (hot-reload, no gateway restart),
deletes the run's session to ensure a clean slate, then runs
portfolio analyze and measures QC3/QC4/QC5/QC8.

Usage:
  python3 scripts/run_benchmark.py [--wf WF75]      # single run (consultation disabled)
  python3 scripts/run_benchmark.py [--all]           # all single-model runs
  python3 scripts/run_benchmark.py WF75 WF76 ...    # named single-model runs
  python3 scripts/run_benchmark.py --hybrid          # all hybrid runs (WF87, WF88)
  python3 scripts/run_benchmark.py --hybrid WF87     # single hybrid run

Hybrid runs require INVESTORCLAW_CONSULTATION_ENABLED=true in .env.
Single-model runs require INVESTORCLAW_CONSULTATION_ENABLED=false in .env.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

# ── Configuration ──────────────────────────────────────────────────────────────
OPENCLAW_JSON   = Path.home() / ".openclaw/openclaw.json"
SESSIONS_JSON   = Path.home() / ".openclaw/sessions/sessions.json"
IC_PROJECT      = Path.home() / "Projects/InvestorClaw"
OUTPUTS_DIR     = IC_PROJECT / "scripts/wf_outputs"
RESULTS_FILE    = IC_PROJECT / "scripts/wf_results.jsonl"

# WF75–WF86: single-model runs (consultation disabled)
SINGLE_MODEL_RUNS: dict[str, str] = {
    "WF75": "together/deepseek-ai/DeepSeek-V3.1",
    "WF76": "together/moonshotai/Kimi-K2.5",
    "WF77": "groq/moonshotai/kimi-k2-instruct-0905",
    "WF78": "groq/openai/gpt-oss-120b",
    "WF79": "groq/openai/gpt-oss-20b",
    "WF80": "google/gemini-3.1-pro-preview",
    "WF81": "openai/gpt-5.4",
    "WF82": "together/MiniMaxAI/MiniMax-M2.7",
    "WF83": "together/zai-org/GLM-5",
    # WF85/WF86: xAI cloud-only gap-close (IC-RUN-20260414-003 addendum)
    "WF85": "xai/grok-4-1-fast",
    "WF86": "xai/grok-4.20-0309-non-reasoning",
}

# WF87–WF94: hybrid runs (consultation enabled, gemma4-consult on CERBERUS)
# WF84 (Kimi-K2.5 hybrid) already complete — not repeated here.
# WF88 re-baselines grok-4-1-fast hybrid under the current injection stack (WF39 predates injection).
HYBRID_RUNS: dict[str, str] = {
    "WF87": "together/MiniMaxAI/MiniMax-M2.7",          # primary default model — critical gap
    "WF88": "xai/grok-4-1-fast",                         # re-baseline WF39 with injection
    "WF89": "together/deepseek-ai/DeepSeek-V3.1",        # WF75 single QC4=44
    "WF90": "together/zai-org/GLM-5",                    # WF83 single QC4=74, likely to gain
    "WF91": "google/gemini-3.1-pro-preview",             # WF80 single QC4=46
    "WF92": "openai/gpt-5.4",                            # WF81 single QC4=28
    "WF93": "groq/openai/gpt-oss-120b",                  # WF78 single QC4=17, groq-served
    "WF94": "groq/moonshotai/kimi-k2-instruct-0905",     # WF77 single QC4=25, groq-served Kimi
}

STOPWORDS = {
    "A","I","AI","OR","AND","THE","FOR","BUT","AN","IN","OF","TO","IS",
    "US","ETF","BY","AT","AS","BE","DO","GO","IF","IT","NO","ON","SO",
    "UP","WE","YTD","QC","GL","PT","MY","AM","PM","EM","NA","N/A","WF",
    "BUY","SELL","HOLD","TECH","ALL","ONE","TWO","SIX","TOP","NET","MID",
    "HIGH","LOW","NEW","OLD","KEY","USE","HAS","HAD","NOT","ARE","WAS",
    "FROM","WITH","THIS","THAT","THEY","HAVE","BEEN","WILL","WERE","EACH",
    "MORE","MOST","BEST","GOOD","RISK","FUND","ALSO","WELL","THAN","SOME",
}

# ── Session management ─────────────────────────────────────────────────────────

def delete_session(session_id: str) -> None:
    """Remove the session entry from sessions.json so the next run starts clean."""
    if not SESSIONS_JSON.exists():
        return
    try:
        store = json.loads(SESSIONS_JSON.read_text())
        # Keys are like "agent:main:explicit:<session_id>"
        key = f"agent:main:explicit:{session_id}"
        if key in store:
            del store[key]
            SESSIONS_JSON.write_text(json.dumps(store, indent=2))
            print(f"  [session] deleted {key}")
        else:
            print(f"  [session] {key} not present — nothing to delete")
    except Exception as e:
        print(f"  [session] WARNING: could not delete session: {e}")


# ── Model switching (hot-reload, no gateway restart) ───────────────────────────

def set_model(model_spec: str) -> None:
    """Update default model in openclaw.json. Gateway hot-reloads — no restart needed."""
    data = json.loads(OPENCLAW_JSON.read_text())
    data["agents"]["defaults"]["model"]["primary"] = model_spec
    OPENCLAW_JSON.write_text(json.dumps(data, indent=2))
    print(f"  [model] → {model_spec}")


def restore_default_model() -> None:
    set_model("together/MiniMaxAI/MiniMax-M2.7")
    print("  [model] restored → together/MiniMaxAI/MiniMax-M2.7")


# ── QC measurement ─────────────────────────────────────────────────────────────

def measure_qc(text: str) -> dict:
    """Measure QC3/QC4/QC5 from synthesis text."""
    raw_tickers = set(re.findall(r'\b[A-Z]{2,5}\b', text))
    tickers = raw_tickers - STOPWORDS
    qc3 = len(tickers)

    patterns = [
        r'\$[\d,]+(?:\.\d+)?[KMBkm]?',
        r'\d+(?:\.\d+)?%',
        r'Sharpe[:\s]+[\d.]+',
        r'\d+\s+analysts?',
        r'PT\s+\$[\d.]+',
        r'[+\-][\d.]+%',
        r'\$[\d.]+[KMBkm]\b',
    ]
    citations: set[str] = set()
    for p in patterns:
        citations.update(re.findall(p, text))
    qc4 = len(citations)
    qc5 = len(text.split())

    return {
        "qc3": qc3,
        "qc4": qc4,
        "qc5": qc5,
        "qc8": 0,
        "tickers": sorted(tickers)[:20],
        "citations": sorted(citations)[:20],
    }


def extract_synthesis(full_output: str) -> str:
    """Extract W6 synthesis text, skipping tool scaffolding."""
    lines = full_output.strip().split("\n")
    synthesis_lines: list[str] = []
    skip_prefixes = (
        "Running ", "SESSION CONTEXT", "SYNTHESIS GUIDANCE",
        "---", "===", "> ⚠️",
        "Fetching", "Loading", "Analyzing",
    )
    # Patterns that indicate a tool status/result line (not synthesis content)
    end_patterns = re.compile(
        r'^(\*\*ic_result\*\*|ic_result\s*[=:]|> ⚠️)'
    )
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        if any(stripped.startswith(p) for p in skip_prefixes):
            continue
        if end_patterns.match(stripped):
            break
        if "⚠️" in stripped and "educational" in stripped.lower():
            break
        synthesis_lines.append(stripped)
    return " ".join(synthesis_lines)


# ── Run a single WF ────────────────────────────────────────────────────────────

def run_wf(wfid: str, model_spec: str) -> dict:
    sep = "─" * 62
    print(f"\n{sep}")
    print(f"  {wfid} — {model_spec}")
    print(f"{sep}")

    session_id = f"ic-{wfid.lower()}"

    # Delete stale session so the run starts clean (no restart needed)
    delete_session(session_id)

    # Switch model (hot-reload — gateway picks it up immediately)
    set_model(model_spec)
    # Brief pause to allow hot-reload to settle
    time.sleep(1)

    print(f"  [run] --session-id {session_id}  /portfolio analyze --full")
    t0 = time.time()

    try:
        proc = subprocess.run(
            ["openclaw", "agent", "--session-id", session_id,
             "-m", "/portfolio analyze --full"],
            capture_output=True, text=True, timeout=600,
        )
        output = proc.stdout + proc.stderr
        elapsed = round(time.time() - t0)
    except subprocess.TimeoutExpired:
        print(f"  [run] TIMEOUT after 600s")
        output = "TIMEOUT"
        elapsed = 600
    except Exception as e:
        print(f"  [run] ERROR: {e}")
        output = f"ERROR: {e}"
        elapsed = round(time.time() - t0)

    print(f"  [run] done in {elapsed}s")

    # Save raw output
    OUTPUTS_DIR.mkdir(parents=True, exist_ok=True)
    (OUTPUTS_DIR / f"{wfid}_output.txt").write_text(output)

    synthesis = extract_synthesis(output)
    qc = measure_qc(synthesis)

    print(f"  QC3={qc['qc3']}  QC4={qc['qc4']}  QC5={qc['qc5']}  QC8={qc['qc8']}")
    print(f"  Tickers: {qc['tickers'][:10]}")
    print(f"  Citations: {qc['citations'][:8]}")
    print(f"\n  --- SYNTHESIS PREVIEW ---")
    print(f"  {synthesis[:300]}")
    print(f"  ---\n")

    status = "PASS"
    if output in ("TIMEOUT",) or output.startswith("ERROR"):
        status = "FAIL"
    elif qc["qc3"] == 0 and qc["qc4"] == 0:
        status = "FAIL"

    result = {
        "wf":               wfid,
        "model":            model_spec,
        "status":           status,
        "elapsed_s":        elapsed,
        "qc3":              qc["qc3"],
        "qc4":              qc["qc4"],
        "qc5":              qc["qc5"],
        "qc8":              qc["qc8"],
        "tickers":          qc["tickers"],
        "citations":        qc["citations"],
        "synthesis_preview": synthesis[:500],
        "timestamp":        datetime.now(timezone.utc).isoformat(),
    }

    with RESULTS_FILE.open("a") as f:
        f.write(json.dumps(result) + "\n")
    print(f"  Result saved → {RESULTS_FILE.name}")

    return result


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="IC-RUN-20260414-003 benchmark runner")
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument("--hybrid", action="store_true",
                            help="Run hybrid mode (consultation enabled). Selects from HYBRID_RUNS.")
    sel_group = parser.add_mutually_exclusive_group()
    sel_group.add_argument("--all", action="store_true", help="Run all runs for the selected mode")
    sel_group.add_argument("--wf",  help="Run a single WF (e.g. --wf WF87)")
    parser.add_argument("wfs", nargs="*", help="Specific WF IDs")
    args = parser.parse_args()

    env_text = (IC_PROJECT / ".env").read_text()

    if args.hybrid:
        run_map = HYBRID_RUNS
        mode_label = "hybrid"
        if "INVESTORCLAW_CONSULTATION_ENABLED=true" not in env_text:
            print("ERROR: INVESTORCLAW_CONSULTATION_ENABLED must be true for hybrid runs")
            print("  Set it in .env, then re-run.")
            sys.exit(1)
    else:
        run_map = SINGLE_MODEL_RUNS
        mode_label = "single-model"
        if "INVESTORCLAW_CONSULTATION_ENABLED=false" not in env_text:
            print("ERROR: INVESTORCLAW_CONSULTATION_ENABLED must be false for single-model runs")
            print("  Set it in .env, then re-run.")
            sys.exit(1)

    if args.all:
        wf_list = list(run_map.keys())
    elif args.wf:
        wf_list = [args.wf.upper()]
    elif args.wfs:
        wf_list = [w.upper() for w in args.wfs]
    else:
        parser.print_help()
        sys.exit(0)

    all_run_maps = {**SINGLE_MODEL_RUNS, **HYBRID_RUNS}
    for wfid in wf_list:
        if wfid not in run_map:
            if wfid in all_run_maps:
                other_mode = "hybrid" if wfid in HYBRID_RUNS else "single-model"
                print(f"ERROR: {wfid} is a {other_mode} run — add --hybrid flag accordingly")
            else:
                print(f"ERROR: Unknown WF {wfid}. Single-model: {list(SINGLE_MODEL_RUNS.keys())}  Hybrid: {list(HYBRID_RUNS.keys())}")
            sys.exit(1)

    print(f"IC-RUN-20260414-003 [{mode_label}] — {wf_list}")
    print(f"Start: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    results: list[dict] = []
    for wfid in wf_list:
        r = run_wf(wfid, run_map[wfid])
        results.append(r)
        time.sleep(2)

    # Restore default model
    restore_default_model()

    # Summary
    print("\n" + "═" * 72)
    print(f"  {'WF':<6} {'Model':<43} {'QC3':>4} {'QC4':>4} {'QC5':>5}  Status")
    print("─" * 72)
    for r in results:
        model_short = r["model"].split("/")[-1][:40]
        print(f"  {r['wf']:<6} {model_short:<43} {r['qc3']:>4} {r['qc4']:>4} {r['qc5']:>5}  {r['status']}")
    print("═" * 72)

    if args.all and args.hybrid:
        print("\nAll hybrid runs complete (WF87–WF94).")
        print("Update MODELS.md hybrid rankings once results are in.")


if __name__ == "__main__":
    main()
