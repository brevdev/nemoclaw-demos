#!/usr/bin/env python3
"""
Consultation Policy — single source of truth for consultative LLM behavior.

This module centralises every decision about whether and how to invoke a
local Ollama consultation model.  All other modules (router, command builders,
enrichment client) import from here rather than reading env vars directly.

Environment variables consumed:
  INVESTORCLAW_CONSULTATION_ENABLED   "true" to activate (default: false)
  INVESTORCLAW_CONSULTATION_ENDPOINT  Ollama base URL (default: http://localhost:11434)
  INVESTORCLAW_CONSULTATION_MODEL     Model tag      (default: gemma4-consult)

gemma4-consult is a tuned Ollama derivative of gemma4:e4b (num_ctx=2048,
num_predict=600, ~65 tok/s on RTX 4500 Ada 24 GB).

Tested models (others will likely work):
  gemma4-consult   — recommended; tuned gemma4:e4b, fast low-latency Q&A
  gemma4:e4b       — base model; 128K ctx, good quality/speed tradeoff
  nemotron-3-nano  — suitable for lower-VRAM setups
  qwen2.5:14b      — solid alternative
"""
from __future__ import annotations

import hashlib
import hmac as _hmac
import json
import os
import secrets
from pathlib import Path

# Per-process session key used when INVESTORCLAW_CONSULTATION_HMAC_KEY is not
# set.  Non-forgeable (random per invocation) but consistent within a session.
_SESSION_HMAC_KEY: bytes = secrets.token_bytes(32)

# ---------------------------------------------------------------------------
# Commands that support --tier3 consultation injection
# ---------------------------------------------------------------------------
_TIER3_COMMANDS: frozenset[str] = frozenset({"analyst", "analysts", "ratings"})

# Maximum symbols passed to the consultation model per command invocation.
# Capped to avoid excessive inference latency on large portfolios.
CONSULTATION_SYMBOL_LIMIT: int = 20


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_consultation_enabled() -> bool:
    """Return True when the user has opted in to local LLM consultation."""
    return os.environ.get("INVESTORCLAW_CONSULTATION_ENABLED", "").lower() == "true"


def get_consultation_endpoint() -> str:
    """Return the Ollama endpoint URL (trailing slash stripped)."""
    return os.environ.get(
        "INVESTORCLAW_CONSULTATION_ENDPOINT", "http://localhost:11434"
    ).rstrip("/")


def get_consultation_model() -> str:
    """Return the Ollama model tag to use for consultation."""
    return os.environ.get("INVESTORCLAW_CONSULTATION_MODEL", "gemma4-consult")


def should_inject_tier3(command: str) -> bool:
    """Return True when --tier3 should be appended to the command's script args."""
    return is_consultation_enabled() and command in _TIER3_COMMANDS


def get_consultation_limit(command: str) -> int:
    """Return the symbol cap for consultation on this command (0 = not applicable)."""
    return CONSULTATION_SYMBOL_LIMIT if command in _TIER3_COMMANDS else 0


def get_dynamic_consultation_limit(position_count: int) -> int:
    """Return enrichment symbol cap scaled to portfolio size."""
    if position_count <= 20:
        return position_count
    if position_count <= 50:
        return 30
    if position_count <= 150:
        return 40
    return CONSULTATION_SYMBOL_LIMIT  # 200+: cap at 20


def update_session_fingerprint(prev_fp: str, symbol: str, synthesis: str) -> str:
    """Chain HMAC: HMAC-SHA256(key, prev_fp + symbol + synthesis)[:16]."""
    raw = os.environ.get("INVESTORCLAW_CONSULTATION_HMAC_KEY", "").encode()
    key = raw if raw else _SESSION_HMAC_KEY
    msg = f"{prev_fp}{symbol}{synthesis}".encode()
    return _hmac.new(key, msg, hashlib.sha256).hexdigest()[:16]


def get_enrichment_status(reports_dir: Path) -> dict:
    """Read enrichment_progress.json and return a status dict with liveness check."""
    progress_file = reports_dir / ".raw" / "enrichment_progress.json"
    defaults = {
        "enriched_count": 0,
        "total_symbols": 0,
        "enriched_pct": 0.0,
        "in_progress": False,
        "background_pid": None,
        "session_fingerprint": "0000000000000000",
        "bonds_covered": False,
        "stalled": False,
        "display": "⚠️ Enrichment status unknown",
    }
    if not progress_file.exists():
        return defaults

    try:
        with open(progress_file) as f:
            prog = json.load(f)
    except Exception:
        return defaults

    enriched_count = prog.get("enriched_count", 0)
    total_symbols = prog.get("total_symbols", 0)
    in_progress = prog.get("in_progress", False)
    background_pid = prog.get("background_pid")
    session_fp = prog.get("session_fingerprint", "0000000000000000")
    bonds_covered = prog.get("bonds_covered", False)
    stalled = False

    enriched_pct = round(enriched_count / total_symbols * 100, 1) if total_symbols else 0.0

    # Check PID liveness
    if in_progress and background_pid:
        try:
            os.kill(background_pid, 0)
        except (ProcessLookupError, PermissionError):
            stalled = True
            in_progress = False

    fp_short = session_fp[:8] if session_fp else "00000000"
    if in_progress:
        display = f"⏳ Enrichment: {enriched_count}/{total_symbols} · {enriched_pct}% · {fp_short} · updating"
    elif stalled:
        display = f"⚠️ Enrichment: {enriched_count}/{total_symbols} · {enriched_pct}% · {fp_short} · stalled"
    elif enriched_count >= total_symbols and total_symbols > 0:
        display = f"✅ Enrichment: {enriched_count}/{total_symbols} · {enriched_pct}% · {fp_short} · complete"
    else:
        display = f"✅ Enrichment: {enriched_count}/{total_symbols} · {enriched_pct}% · {fp_short}"

    return {
        "enriched_count": enriched_count,
        "total_symbols": total_symbols,
        "enriched_pct": enriched_pct,
        "in_progress": in_progress,
        "background_pid": background_pid,
        "session_fingerprint": session_fp,
        "bonds_covered": bonds_covered,
        "stalled": stalled,
        "display": display,
    }
