#!/usr/bin/env python3
"""
Detached background enricher for InvestorClaw.

Spawned by fetch_analyst_recommendations_parallel.py after the foreground
tier3 enrichment completes. Enriches remaining symbols atomically, updating
enrichment_progress.json after each symbol so agents can report live status.

Usage (internal — not a user-facing command):
    python3 background_enricher.py <raw_dir> <analyst_data_file> <progress_file>

Design:
- Loads .env manually before any other imports (detached process, no inherited env)
- Atomic read-modify-write-rename pattern for all state files
- SIGTERM handler sets shutdown flag; exits cleanly after current symbol
- PID file written on start, removed in finally
- Idempotent: skips already-enriched symbols
"""
from __future__ import annotations

import json
import os
import signal
import sys
import time
from datetime import datetime
from pathlib import Path

# ---------------------------------------------------------------------------
# Step 1: Resolve skill root and load .env BEFORE any investorclaw imports.
# This is critical for detached processes: no inherited env vars.
# ---------------------------------------------------------------------------
_SKILL_ROOT = Path(__file__).resolve().parent.parent


def _load_env(env_file: Path) -> None:
    if not env_file.exists():
        return
    with open(env_file) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())


_load_env(_SKILL_ROOT / ".env")

# ---------------------------------------------------------------------------
# Step 2: Add skill_root to sys.path so internal/ imports work.
# ---------------------------------------------------------------------------
sys.path.insert(0, str(_SKILL_ROOT))
sys.path.insert(0, str(_SKILL_ROOT / "internal"))
sys.path.insert(0, str(_SKILL_ROOT / "scripts"))
sys.path.insert(0, str(_SKILL_ROOT / "rendering"))
sys.path.insert(0, str(_SKILL_ROOT / "services"))
sys.path.insert(0, str(_SKILL_ROOT / "providers"))
sys.path.insert(0, str(_SKILL_ROOT / "models"))
sys.path.insert(0, str(_SKILL_ROOT / "config"))
sys.path.insert(0, str(_SKILL_ROOT / "setup"))

# ---------------------------------------------------------------------------
# Step 3: Now safe to import investorclaw internals.
# ---------------------------------------------------------------------------
from internal.tier3_enrichment import ConsultationClient, _compute_fingerprint  # noqa: E402
from services.consultation_policy import update_session_fingerprint  # noqa: E402

# ---------------------------------------------------------------------------
# Globals
# ---------------------------------------------------------------------------
_shutdown = False


def _sigterm_handler(signum, frame):
    global _shutdown
    _shutdown = True


signal.signal(signal.SIGTERM, _sigterm_handler)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _atomic_write(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2, default=str)
    os.rename(tmp, path)


def _build_prompt_from_dict(symbol: str, rec: dict) -> str:
    consensus = rec.get("consensus", "N/A") or "N/A"
    analyst_count = rec.get("analyst_count", 0) or 0
    buy_count = rec.get("buy_count", 0) or 0
    hold_count = rec.get("hold_count", 0) or 0
    sell_count = rec.get("sell_count", 0) or 0
    target_price = rec.get("target_price_mean") or 0
    current_price = rec.get("current_price", 0) or 0
    return (
        f"You are a financial data analyst. Summarize the analyst sentiment for {symbol}. "
        f"Consensus: {consensus}. "
        f"Analysts: {analyst_count}. "
        f"Buy/Hold/Sell: {buy_count}/{hold_count}/{sell_count}. "
        f"Mean target: ${float(target_price):.2f}. "
        f"Current: ${float(current_price):.2f}. "
        "In 2 sentences: (1) key analyst view, (2) main risk. "
        "Educational only — not investment advice."
    )


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    if len(sys.argv) < 4:
        print("Usage: background_enricher.py <raw_dir> <analyst_data_file> <progress_file>",
              file=sys.stderr)
        return 1

    raw_dir = Path(sys.argv[1])
    analyst_data_file = Path(sys.argv[2])
    progress_file = Path(sys.argv[3])

    pid_file = raw_dir / "enrichment.pid"
    pid_file.write_text(str(os.getpid()))

    try:
        # Load analyst_data.json
        if not analyst_data_file.exists():
            print(f"analyst_data_file not found: {analyst_data_file}", file=sys.stderr)
            return 1

        with open(analyst_data_file) as f:
            analyst_data = json.load(f)

        # Unwrap note key if present
        all_recommendations: dict = analyst_data.get("recommendations", {})
        if not all_recommendations:
            return 0

        # Load progress
        if not progress_file.exists():
            return 0

        with open(progress_file) as f:
            progress = json.load(f)

        enriched_set = set(progress.get("enriched_symbols", []))
        session_fp = progress.get("session_fingerprint", "0000000000000000")
        fingerprint_chain: list = progress.get("fingerprint_chain", ["0000000000000000"])
        model = progress.get("model", "gemma4-consult")

        # Determine remaining symbols (not yet enriched)
        all_symbols = list(all_recommendations.keys())
        remaining = [s for s in all_symbols if s not in enriched_set]

        if not remaining:
            progress["in_progress"] = False
            progress["background_pid"] = None
            progress["last_updated"] = datetime.now().isoformat()
            _atomic_write(progress_file, progress)
            return 0

        # Load existing tier3_enriched.json for atomic extension
        tier3_file = raw_dir / "analyst_recommendations_tier3_enriched.json"
        if tier3_file.exists():
            with open(tier3_file) as f:
                tier3_data = json.load(f)
        else:
            tier3_data = {
                "tier": "tier3_enrichment",
                "consultation_model": model,
                "consultation_endpoint": os.environ.get(
                    "INVESTORCLAW_CONSULTATION_ENDPOINT", "http://localhost:11434"
                ),
                "timestamp": datetime.now().isoformat(),
                "total_enriched": 0,
                "enriched_recommendations": {},
            }

        client = ConsultationClient()
        if not client.is_available():
            # Mark as not in progress — local-inference unavailable
            progress["in_progress"] = False
            progress["background_pid"] = None
            progress["last_updated"] = datetime.now().isoformat()
            _atomic_write(progress_file, progress)
            return 0

        elapsed_times: list = []
        failed_symbols: list = list(progress.get("failed_symbols", []))

        # Resolve card format toggle and output paths.
        # INVESTORCLAW_CARD_FORMAT: json | svg | both (default)
        _card_fmt = os.environ.get("INVESTORCLAW_CARD_FORMAT", "both").strip().lower()
        _rdir = os.environ.get("INVESTOR_CLAW_REPORTS_DIR", "")
        _cards_output_dir = Path(_rdir) / ".raw" if _rdir else None
        _quote_dir = Path.home() / ".investorclaw" / "quotes"
        try:
            from rendering.render_consultation_card import render_card as _render_card
            _render_available = True
        except ImportError:
            _render_available = False

        for symbol in remaining:
            if _shutdown:
                break

            rec = all_recommendations.get(symbol, {})
            prompt = _build_prompt_from_dict(symbol, rec)

            t0 = time.time()
            result = client.consult(prompt)
            elapsed_ms = int((time.time() - t0) * 1000)
            elapsed_times.append(elapsed_ms / 1000.0)

            if result.response and not result.is_heuristic:
                synthesis = result.response.strip()
                fp = _compute_fingerprint(symbol, client.model, synthesis)
                attribution = f"{client.model} via local-inference ({result.inference_ms}ms)"
                quote_block: dict = {
                    "text": synthesis,
                    "attribution": attribution,
                    "verbatim_required": True,
                    "fingerprint": fp,
                }

                # JSON quote file — written unless format is svg-only.
                if _card_fmt != "svg":
                    try:
                        _quote_dir.mkdir(parents=True, exist_ok=True)
                        _qf = _quote_dir / f"{symbol}.quote.json"
                        _qf.write_text(json.dumps({
                            "symbol": symbol,
                            "text": synthesis,
                            "attribution": attribution,
                            "fingerprint": fp,
                            "verbatim_required": True,
                            "timestamp": datetime.now().isoformat(),
                        }, indent=2))
                        quote_block["quote_path"] = str(_qf)
                    except Exception:
                        pass

                # SVG card — written only when format is not json-only AND
                # render module is available AND reports dir is configured.
                if _card_fmt != "json" and _render_available and _cards_output_dir:
                    try:
                        card_path = str(_render_card(
                            symbol, synthesis, attribution, fp,
                            datetime.now().isoformat(), _cards_output_dir,
                        ))
                        quote_block["card_path"] = card_path
                    except Exception:
                        pass

                enrichment_rec = {
                    "consensus": rec.get("consensus"),
                    "analyst_count": rec.get("analyst_count", 0),
                    "sentiment": "positive" if "buy" in str(rec.get("consensus", "")).lower() else "neutral",
                    "sentiment_score": 0.7 if "buy" in str(rec.get("consensus", "")).lower() else 0.0,
                    "recommendation_strength": "buy" if rec.get("recommendation_mean", 2.5) < 2.5 else "hold",
                    "synthesis": synthesis,
                    "key_insights": [synthesis] if synthesis else [],
                    "risk_assessment": "",
                    "consultation": result.to_dict(),
                    "fingerprint": fp,
                    "quote": quote_block,
                }

                # Atomic extend tier3_enriched.json
                tier3_data["enriched_recommendations"][symbol] = enrichment_rec
                tier3_data["total_enriched"] = len(tier3_data["enriched_recommendations"])
                tier3_data["timestamp"] = datetime.now().isoformat()
                _atomic_write(tier3_file, tier3_data)

                # Update progress
                enriched_set.add(symbol)
                session_fp = update_session_fingerprint(session_fp, symbol, synthesis)
                fingerprint_chain.append(session_fp)
            else:
                failed_symbols.append(symbol)

            avg_s = sum(elapsed_times) / len(elapsed_times) if elapsed_times else 0
            remaining_count = max(0, len(remaining) - len(elapsed_times))

            progress["enriched_count"] = len(enriched_set)
            progress["enriched_symbols"] = list(enriched_set)
            progress["failed_symbols"] = failed_symbols
            progress["session_fingerprint"] = session_fp
            progress["fingerprint_chain"] = fingerprint_chain
            progress["last_updated"] = datetime.now().isoformat()
            progress["estimated_remaining_s"] = int(remaining_count * avg_s)
            _atomic_write(progress_file, progress)

            time.sleep(0.1)

        # Final: mark complete
        progress["in_progress"] = False
        progress["background_pid"] = None
        progress["last_updated"] = datetime.now().isoformat()
        progress["estimated_remaining_s"] = 0
        _atomic_write(progress_file, progress)
        return 0

    finally:
        if pid_file.exists():
            try:
                pid_file.unlink()
            except Exception:
                pass


if __name__ == "__main__":
    raise SystemExit(main())
