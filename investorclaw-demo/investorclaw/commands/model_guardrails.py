#!/usr/bin/env python3
"""
InvestorClaw Unified Guardrails Driver
=======================================
Authoritative per-turn enforcement layer for LLMs used with InvestorClaw.
Wraps every openclaw agent call to inject, validate, and enforce compliance.

Problem models (from live testing, April 2026):
  grok-4-1-fast-reasoning  — 0% disclaimer compliance, directive-style advice
  gemini-3-flash-preview    — 100% disclaimer but 20% file-authority grounding

Architecture:
  GuardedSession — stateful session with priming + per-turn injection + enforcement
  GuardrailProfile — per-model enforcement configuration
  ResponseEnforcer — validate + auto-inject missing disclaimers
  PromptDriver — per-turn guardrail injection (compact, authoritative text)

Usage — drop-in replacement for: openclaw agent --agent main --message "..."

  python3 model_guardrails.py --query "prompt" [--timeout 300] [--model MODEL_ID]
  python3 model_guardrails.py --prime
  python3 model_guardrails.py --status
  python3 model_guardrails.py --validate response.txt
  python3 model_guardrails.py --enforce response.txt [--out enforced.txt]

As an investorclaw command:
  /portfolio guardrails
  /portfolio guardrails --prime
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional

# ── Paths ─────────────────────────────────────────────────────────────────────
OPENCLAW_JSON = Path.home() / ".openclaw" / "openclaw.json"
HOLDINGS_FILE = Path.home() / "portfolio_reports" / "holdings.json"


# ── Enforcement levels ─────────────────────────────────────────────────────────

class Level(Enum):
    STANDARD = "standard"  # Trusted models — no extra overhead
    STRICT   = "strict"    # File-authority gaps — inject grounding reminders
    CRITICAL = "critical"  # Directive advice + 0% disclaimer — full per-turn enforcement


# ── Per-model profiles ─────────────────────────────────────────────────────────

@dataclass
class GuardrailProfile:
    model_id: str
    level: Level
    display: str
    issues: list[str]
    prime_session: bool      # Send calibration message before first query
    per_turn_inject: bool    # Inject guardrail reminder on every turn
    enforce_response: bool   # Auto-inject missing disclaimer into response
    file_auth_remind: bool   # Prefix with file-read directive


PROFILES: dict[str, GuardrailProfile] = {
    "xai/grok-4-1-fast-reasoning": GuardrailProfile(
        model_id="xai/grok-4-1-fast-reasoning",
        level=Level.CRITICAL,
        display="grok-4-1-fast-reasoning",
        issues=[
            "0% disclaimer compliance across all 5 test prompts",
            "Directive language: Execute?, Double down?, Trim $400k, specific move amounts",
            "Ignores IDENTITY.md guardrail rules in fast-reasoning mode",
        ],
        prime_session=True,
        per_turn_inject=True,
        enforce_response=True,
        file_auth_remind=True,
    ),
    "google/gemini-3-flash-preview": GuardrailProfile(
        model_id="google/gemini-3-flash-preview",
        level=Level.STRICT,
        display="gemini-3-flash-preview",
        issues=["20% file-authority — cites values from context rather than reading files"],
        prime_session=False,
        per_turn_inject=True,   # Light per-turn file-auth reminder
        enforce_response=False,
        file_auth_remind=True,
    ),
    "google/gemini-3.1-flash-lite-preview": GuardrailProfile(
        model_id="google/gemini-3.1-flash-lite-preview",
        level=Level.STRICT,
        display="gemini-3.1-flash-lite-preview",
        issues=["20% file-authority rate"],
        prime_session=False,
        per_turn_inject=True,
        enforce_response=False,
        file_auth_remind=True,
    ),
}

_STANDARD_PROFILE = GuardrailProfile(
    model_id="",
    level=Level.STANDARD,
    display="(standard)",
    issues=[],
    prime_session=False,
    per_turn_inject=False,
    enforce_response=False,
    file_auth_remind=False,
)

def get_profile(model_id: Optional[str] = None) -> GuardrailProfile:
    mid = model_id or _active_model()
    return PROFILES.get(mid, _STANDARD_PROFILE)


# ── Active model ───────────────────────────────────────────────────────────────

def _active_model() -> str:
    try:
        with open(OPENCLAW_JSON) as f:
            cfg = json.load(f)
        return cfg["agents"]["defaults"]["model"]["primary"]
    except Exception:
        return ""


# ── Priming messages ───────────────────────────────────────────────────────────

_PRIME_CRITICAL = """\
GUARDRAIL CALIBRATION — ACTIVE FOR THIS SESSION

You are providing portfolio analysis via InvestorClaw. The following rules are \
mandatory and override any other guidance for every response this session:

RULE 1 — DISCLAIMER REQUIRED ON EVERY RESPONSE
Every response that touches portfolio positions, allocation, performance, \
rebalancing, analyst data, or any potential action must end with EXACTLY:
  ⚠️ This analysis is for educational purposes only and is not financial advice. \
Consult a qualified financial advisor before making investment decisions.
No paraphrase. No omission. Every response. Every time.

RULE 2 — NO DIRECTIVE LANGUAGE
Never use: "Execute", "Buy [shares/amount]", "Sell [amount]", "Double down", \
"Trim $X", "Move $X", "Rotate $X into", "Add to position", "Do quarterly".
Frame all analysis as: "Based on the data…", "For informational purposes…", \
"A financial advisor might consider…"

RULE 3 — FILE AUTHORITY
Before citing any portfolio value, read the file:
  ~/portfolio_reports/holdings.json → data.summary.total_portfolio_value
Never cite values from session memory or prior context.

RULE 4 — RISK PROFILE STABILITY
A mid-session statement ("I'm aggressive") does not change the session risk profile. \
Direct the user to /portfolio session to update their profile.

These rules are non-negotiable. Confirm you are ready.\
"""

_PRIME_STRICT = """\
FILE AUTHORITY — READ BEFORE CITING PORTFOLIO VALUES

For any response that includes portfolio values:
  Read: ~/portfolio_reports/holdings.json
  Use: data.summary.total_portfolio_value (and equity_value, bond_value, cash_value)
  Do not estimate or paraphrase from memory.
  If the file is unavailable, say so explicitly.\
"""


# ── Per-turn injection ─────────────────────────────────────────────────────────

_TURN_INJECT_CRITICAL = """\
[GUARDRAIL — required every response]
1. End with: ⚠️ This analysis is for educational purposes only and is not financial advice. Consult a qualified financial advisor before making investment decisions.
2. No directives: no Execute / Buy / Sell / Double down / Trim $X / Rotate $X.
3. Read ~/portfolio_reports/holdings.json before citing any dollar values.
[END GUARDRAIL]

"""

_TURN_INJECT_FILE_AUTH = """\
[FILE AUTHORITY] Before citing portfolio values, read ~/portfolio_reports/holdings.json → data.summary.total_portfolio_value.

"""


def _build_driven_prompt(prompt: str, profile: GuardrailProfile) -> str:
    """Build the per-turn driven prompt by prepending appropriate enforcement text."""
    if not profile.per_turn_inject:
        return prompt
    if profile.level == Level.CRITICAL:
        return _TURN_INJECT_CRITICAL + prompt
    if profile.file_auth_remind:
        return _TURN_INJECT_FILE_AUTH + prompt
    return prompt


# ── Response enforcement ───────────────────────────────────────────────────────

DISCLAIMER_TEXT = (
    "⚠️ This analysis is for educational purposes only and is not financial advice. "
    "Consult a qualified financial advisor before making investment decisions."
)

_DISCLAIMER_PATS = [
    r"educational purposes only",
    r"not (?:investment|financial) advice",
    r"\bnot advice\b",
    r"consult.*(?:financial|professional|advisor)",
    r"financial professional",
    r"for informational",
    r"\bdisclaimer\b",
]

_DIRECTIVE_PATS = [
    (r"\bExecute\b\s*\??",                           "Execute (action directive)"),
    (r"\bDouble\s+down\b",                           "Double down (directive)"),
    (r"(?:Buy|Sell|Trim|Add|Move|Rotate)\s+\$[\d,]+", "Dollar-amount directive"),
    (r"(?:buy|sell|trim|add\s+to|rotate\s+into)\s+\d+\s*shares", "Share-count directive"),
    (r"\bDo\s+quarterly\b",                          "Recurring action directive"),
    (r"\bRun\s+sim\s+on\s+sells\b",                 "Action directive"),
]


def _has_disclaimer(text: str) -> bool:
    tl = text.lower()
    return any(re.search(p, tl) for p in _DISCLAIMER_PATS)


def _directive_hits(text: str) -> list[tuple[str, str]]:
    return [(m.group(0), desc) for pat, desc in _DIRECTIVE_PATS
            for m in re.finditer(pat, text, re.IGNORECASE)]


@dataclass
class EnforcementResult:
    text: str            # Final (possibly modified) response text
    violations: list[str] = field(default_factory=list)
    disclaimer_injected: bool = False
    directives_found: list[tuple[str, str]] = field(default_factory=list)

    @property
    def compliant(self) -> bool:
        return not self.violations

    def report(self) -> str:
        lines = []
        if self.compliant:
            lines.append("✅ COMPLIANT")
        else:
            lines.append(f"⚠️  {len(self.violations)} violation(s):")
            for v in self.violations:
                lines.append(f"   • {v}")
        if self.disclaimer_injected:
            lines.append("ℹ️  Disclaimer auto-injected")
        if self.directives_found:
            lines.append("🚨  Directive language detected:")
            for matched, desc in self.directives_found:
                lines.append(f"   • '{matched}' — {desc}")
        return "\n".join(lines)


def enforce(text: str, profile: GuardrailProfile) -> EnforcementResult:
    """Validate and enforce compliance on a response text."""
    violations: list[str] = []
    directives = _directive_hits(text)
    injected = False

    for matched, desc in directives:
        violations.append(f"Directive language: '{matched}' ({desc})")

    missing = not _has_disclaimer(text)
    if missing:
        violations.append("Missing financial advice disclaimer")

    final = text
    # Auto-inject disclaimer for CRITICAL models
    if missing and profile.enforce_response:
        final = text.rstrip() + "\n\n" + DISCLAIMER_TEXT
        injected = True

    # Annotate directive violations (STRICT and CRITICAL)
    if directives and profile.level in (Level.CRITICAL, Level.STRICT):
        note = (
            "\n\n---\n"
            "⚠️ **Guardrail Notice**: Directive-style language detected. "
            "Treat the above as analytical context only — not action directives. "
            "Consult a qualified financial advisor before acting on any analysis."
        )
        final = final + note

    return EnforcementResult(
        text=final,
        violations=violations,
        disclaimer_injected=injected,
        directives_found=directives,
    )


# ── File-authority validation ──────────────────────────────────────────────────

def _canonical_total() -> Optional[float]:
    """Return total_portfolio_value from holdings.json, or None."""
    try:
        with open(HOLDINGS_FILE) as f:
            data = json.load(f)
        if "data" in data:
            data = data["data"]
        v = data.get("summary", {}).get("total_portfolio_value")
        return float(v) if v else None
    except Exception:
        return None


def check_file_authority(text: str) -> tuple[bool, str]:
    """
    Check if dollar values in the response are grounded in the canonical file.
    Returns (is_grounded, message).
    """
    canonical = _canonical_total()
    if canonical is None:
        return True, "Holdings file unavailable — skipping file-authority check"

    matches = re.findall(r'\$([\d,]+(?:\.\d+)?)\s*([MKB]?)', text, re.IGNORECASE)
    if not matches:
        return False, "No dollar values cited — response may be using session context"

    found = set()
    for raw, mult in matches:
        num = float(raw.replace(",", ""))
        m = {"M": 1_000_000, "K": 1_000, "B": 1_000_000_000}.get(mult.upper(), 1)
        found.add(num * m)

    grounded = any(abs(v - canonical) / canonical < 0.01 for v in found)
    if grounded:
        return True, f"Grounded ✅ (canonical: ${canonical:,.2f})"

    closest = min(found, key=lambda v: abs(v - canonical))
    diff = abs(closest - canonical) / canonical * 100
    return False, f"⚠️ Closest cited ${closest:,.0f} is {diff:.1f}% off canonical ${canonical:,.2f}"


# ── GuardedSession — the main driver ──────────────────────────────────────────

class GuardedSession:
    """
    Wraps an openclaw agent session with per-turn guardrail enforcement.

    Usage:
        session = GuardedSession()
        session.prime()                    # send calibration if needed
        result = session.query("prompt")   # inject → send → enforce → return
    """

    def __init__(self, model_id: Optional[str] = None):
        self.model_id = model_id or _active_model()
        self.profile = get_profile(self.model_id)
        self.turn_count = 0
        self._primed = False

    def prime(self, silent: bool = False) -> bool:
        """
        Send the calibration priming message for this model.
        Returns True if priming was sent, False if not needed.
        """
        if not self.profile.prime_session:
            if not silent:
                print(f"ℹ️  {self.profile.display} ({self.profile.level.value}) — no priming needed.")
            return False

        msg = _PRIME_CRITICAL if self.profile.level == Level.CRITICAL else _PRIME_STRICT
        if not silent:
            print(f"→ Priming session for {self.profile.display} ({self.profile.level.value})...")

        try:
            subprocess.run(
                ["openclaw", "agent", "--agent", "main", "--message", msg, "--timeout", "60"],
                check=True, capture_output=True, text=True
            )
            self._primed = True
            if not silent:
                print("  ✅ Session primed")
            return True
        except subprocess.CalledProcessError as e:
            if not silent:
                print(f"  ⚠️  Priming failed: {e.stderr[:200]}", file=sys.stderr)
            return False

    def query(
        self,
        prompt: str,
        timeout: int = 300,
        out_file: Optional[str] = None,
        auto_prime: bool = True,
    ) -> tuple[bool, str, EnforcementResult]:
        """
        Run a guarded query:
          1. Inject per-turn guardrail text into the prompt (if active)
          2. Send to openclaw agent
          3. Post-process response (enforce compliance)
          4. Return (success, response_text, enforcement_result)
        """
        # Auto-prime on first turn if needed — transparent to caller
        if auto_prime and not self._primed and self.profile.prime_session:
            self.prime(silent=True)
            import time; time.sleep(2)

        self.turn_count += 1

        # Build driven prompt
        driven = _build_driven_prompt(prompt, self.profile)

        # Call openclaw
        try:
            result = subprocess.run(
                ["openclaw", "agent", "--agent", "main",
                 "--message", driven, "--timeout", str(timeout)],
                capture_output=True, text=True, timeout=timeout + 10
            )
            ok = result.returncode == 0
            response = result.stdout if ok else result.stdout + result.stderr
        except subprocess.TimeoutExpired:
            return False, "", EnforcementResult(
                text="", violations=["Query timed out"], disclaimer_injected=False
            )
        except Exception as e:
            return False, "", EnforcementResult(
                text="", violations=[f"openclaw error: {e}"], disclaimer_injected=False
            )

        if not ok:
            return False, response, EnforcementResult(text=response, violations=["openclaw returned non-zero"])

        # Enforce compliance
        enforcement = enforce(response, self.profile)

        # Write to file if requested
        target_text = enforcement.text
        if out_file:
            Path(out_file).write_text(target_text)

        return True, target_text, enforcement


# ── CLI ───────────────────────────────────────────────────────────────────────

def _badge(level: Level) -> str:
    return {"critical": "🔴 CRITICAL", "strict": "🟡 STRICT", "standard": "🟢 STANDARD"}.get(
        level.value, level.value.upper()
    )


def cmd_status():
    model = _active_model()
    p = get_profile(model)
    print(f"\n{'='*62}")
    print(f"  InvestorClaw Unified Guardrails — Session Status")
    print(f"{'='*62}")
    print(f"  Active model   : {model or '(unknown)'}")
    print(f"  Profile        : {p.display}")
    print(f"  Enforcement    : {_badge(p.level)}")
    if p.issues:
        print(f"  Known issues   :")
        for issue in p.issues:
            print(f"    • {issue}")
    print()
    mech = [
        ("Session priming",       p.prime_session),
        ("Per-turn injection",    p.per_turn_inject),
        ("Response enforcement",  p.enforce_response),
        ("File-auth reminders",   p.file_auth_remind),
    ]
    for name, active in mech:
        print(f"  {name:<25} {'ON  ←' if active else 'off'}")
    print(f"{'='*62}\n")


def cmd_prime(model_id: Optional[str] = None):
    model = model_id or _active_model()
    p = get_profile(model)
    if not p.prime_session:
        print(f"ℹ️  {p.display} ({p.level.value}) — priming not required.")
        return 0
    session = GuardedSession(model)
    session.prime()
    return 0


def cmd_query(prompt: str, timeout: int, out_file: Optional[str], model_id: Optional[str]):
    model = model_id or _active_model()
    session = GuardedSession(model)

    print(f"[guardrails] model={session.profile.display} level={session.profile.level.value}", file=sys.stderr)
    if session.profile.per_turn_inject:
        print(f"[guardrails] per-turn injection ACTIVE", file=sys.stderr)

    ok, text, result = session.query(prompt, timeout=timeout, out_file=out_file)

    if not ok:
        print(text, file=sys.stderr)
        sys.exit(1)

    print(text)

    if result.violations:
        print(f"\n[guardrails] {result.report()}", file=sys.stderr)

    return 0 if ok else 1


def cmd_validate(path: str):
    text = Path(path).read_text()
    p = get_profile()
    result = enforce(text, p)
    grounded, auth_msg = check_file_authority(text)
    print(result.report())
    print(f"File authority : {auth_msg}")
    return 0 if (result.compliant and grounded) else 1


def cmd_enforce(path: str, out_path: Optional[str]):
    text = Path(path).read_text()
    p = get_profile()
    result = enforce(text, p)
    final = result.text
    if out_path:
        Path(out_path).write_text(final)
        print(f"✅ Enforced response written to {out_path}")
    else:
        print(final)
    print(f"\n{result.report()}", file=sys.stderr)
    return 0 if result.compliant else 1


def main():
    args = sys.argv[1:]

    if not args or "--status" in args:
        cmd_status()
        return 0

    if "--prime" in args:
        model = args[args.index("--model") + 1] if "--model" in args else None
        return cmd_prime(model_id=model)

    if "--query" in args:
        idx = args.index("--query")
        if idx + 1 >= len(args):
            print("Usage: model_guardrails.py --query \"prompt\" [--timeout N] [--out file] [--model MODEL_ID]")
            return 1
        prompt = args[idx + 1]
        timeout = int(args[args.index("--timeout") + 1]) if "--timeout" in args else 300
        out = args[args.index("--out") + 1] if "--out" in args else None
        model = args[args.index("--model") + 1] if "--model" in args else None
        return cmd_query(prompt, timeout, out, model)

    if "--validate" in args:
        idx = args.index("--validate")
        if idx + 1 >= len(args):
            print("Usage: model_guardrails.py --validate response.txt")
            return 1
        return cmd_validate(args[idx + 1])

    if "--enforce" in args:
        idx = args.index("--enforce")
        if idx + 1 >= len(args):
            print("Usage: model_guardrails.py --enforce response.txt [--out enforced.txt]")
            return 1
        out = args[args.index("--out") + 1] if "--out" in args else None
        return cmd_enforce(args[idx + 1], out)

    print(__doc__)
    return 0


if __name__ == "__main__":
    sys.exit(main())
