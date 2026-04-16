#!/usr/bin/env python3
"""
InvestorClaw Session Initialization — Risk Calibration Intake

Establishes investor risk profile and macro context at session start.
Output is printed as structured markdown that the agent stores in
session memory and uses to govern advice framing throughout the session.

Usage:
    python3 session_init.py [--auto]
    --auto: emit the intake prompt for the agent to ask (no pre-set values)
"""

import sys
import json
from datetime import datetime, timezone
from pathlib import Path

from config.path_resolver import get_reports_dir

# ── Heat level definitions ────────────────────────────────────────────────────

HEAT_LEVELS = {
    1: {
        "label": "Capital Preservation",
        "description": "Protect principal above all. Accept minimal returns to avoid loss.",
        "advice_framing": "defensive",
        "max_equity_pct": 30,
        "drawdown_tolerance_pct": 5,
    },
    2: {
        "label": "Income",
        "description": "Steady yield priority. Modest growth acceptable. Protect against large drawdowns.",
        "advice_framing": "conservative",
        "max_equity_pct": 50,
        "drawdown_tolerance_pct": 10,
    },
    3: {
        "label": "Balanced",
        "description": "Balance growth and safety. ~60/40 benchmark. Sit through normal corrections.",
        "advice_framing": "balanced",
        "max_equity_pct": 70,
        "drawdown_tolerance_pct": 20,
    },
    4: {
        "label": "Growth",
        "description": "Higher returns over safety. Accept volatility. 10-year+ horizon.",
        "advice_framing": "growth",
        "max_equity_pct": 85,
        "drawdown_tolerance_pct": 30,
    },
    5: {
        "label": "Aggressive Growth",
        "description": "Maximum returns. Accept high volatility and significant drawdowns.",
        "advice_framing": "aggressive",
        "max_equity_pct": 95,
        "drawdown_tolerance_pct": 50,
    },
}

# ── Macro risk categories ─────────────────────────────────────────────────────

MACRO_RISK_CATEGORIES = [
    "Geopolitical conflict (Iran/Middle East, Russia/Ukraine)",
    "Tariff/trade war impacts",
    "Oil and energy price volatility",
    "Federal Reserve rate policy",
    "Tech sector concentration / AI bubble concerns",
    "Recession risk / economic slowdown",
    "Credit market stress",
    "China/Taiwan tensions",
    "Currency risk (USD strength/weakness)",
    "Inflation persistence",
]


def emit_agent_intake_prompt() -> str:
    """
    Returns a structured prompt the agent should present to the user
    at the start of an InvestorClaw session.
    """
    macro_list = "\n".join(
        f"  {i+1}. {risk}" for i, risk in enumerate(MACRO_RISK_CATEGORIES)
    )

    return f"""
## InvestorClaw Session Setup — Risk Calibration

Before I analyze your portfolio, I need to understand your current priorities.
This takes 60 seconds and ensures I frame everything appropriately for *you*.

---

**Question 1 — Investment Objective**
How would you describe your primary goal right now?

  1. Capital Preservation — protect what I have, minimal risk
  2. Income — steady yield, modest growth is fine
  3. Balanced — growth and safety in roughly equal measure
  4. Growth — higher returns, comfortable with volatility
  5. Aggressive Growth — maximum returns, I can handle significant drawdowns

*Reply with a number (1-5) or describe in your own words.*

---

**Question 2 — Current Volatility Stance**
Given today's market environment, which best describes your posture?

  A. Defensive — reduce risk, move to safer assets
  B. Neutral — hold current allocation, ride it out
  C. Opportunistic — use volatility to buy dips in quality names

*Reply with A, B, or C.*

---

**Question 3 — Macro Concerns** *(optional — press Enter to skip)*
Any specific risks you want me to weigh in today's analysis?

{macro_list}
  Other: describe in your own words

*Reply with numbers (e.g. "1, 3, 5"), keyword, or describe your concern.*

---

Once you answer, I'll confirm your profile and we'll proceed with portfolio analysis
calibrated to your current goals and risk tolerance.
""".strip()


def build_session_profile(
    heat_level: int,
    volatility_stance: str,
    macro_concerns: list,
) -> dict:
    """Build a session profile dict from intake answers."""
    level_info = HEAT_LEVELS.get(heat_level, HEAT_LEVELS[3])
    return {
        "heat_level": heat_level,
        "objective": level_info["label"],
        "advice_framing": level_info["advice_framing"],
        "max_equity_pct": level_info["max_equity_pct"],
        "drawdown_tolerance_pct": level_info["drawdown_tolerance_pct"],
        "volatility_stance": volatility_stance,
        "macro_concerns": macro_concerns,
        "established": datetime.now(timezone.utc).isoformat(),
    }


def format_session_context_for_agent(profile: dict) -> str:
    """
    Format profile as structured context block for injection into
    agent session memory / IDENTITY.md override.
    """
    heat = profile["heat_level"]
    level_info = HEAT_LEVELS.get(heat, HEAT_LEVELS[3])
    concerns_str = ", ".join(profile["macro_concerns"]) if profile["macro_concerns"] else "None specified"

    framing_rules = {
        "defensive":   "Emphasize capital protection. Flag ALL downside risks prominently. Do not suggest increasing equity exposure.",
        "conservative": "Lead with income and safety. Show yield data prominently. Caution on duration risk.",
        "balanced":    "Present both upside and downside. Note benchmark deviations. Balanced risk language.",
        "growth":      "Show growth opportunities clearly. Note volatility. Include standard disclaimer on all suggestions.",
        "aggressive":  "Show upside potential. BUT given current market volatility, explicitly note elevated risk on every suggestion. STRONG disclaimer required.",
    }

    framing = framing_rules.get(profile["advice_framing"], framing_rules["balanced"])

    return f"""
## ACTIVE SESSION INVESTOR PROFILE
**Established**: {profile['established'][:10]}
**Objective**: {profile['objective']} (Heat Level {heat}/5)
**Volatility Stance**: {profile['volatility_stance']}
**Max Equity Target**: {profile['max_equity_pct']}%
**Drawdown Tolerance**: {profile['drawdown_tolerance_pct']}%
**Macro Concerns**: {concerns_str}

### Advice Framing Rule for This Session
{framing}

### Guardrail Override
- Heat level {heat}/5 means: {level_info['description']}
- Do NOT escalate recommendations beyond this heat level even if the user
  asks aggressive questions mid-session. If user asks for more aggressive
  advice, acknowledge the request but remind them of their stated profile.
- Re-run /portfolio session if the user wants to update their profile.

⚠️ **All portfolio analysis is for educational purposes only.
Consult a qualified financial advisor before acting on any analysis.**
""".strip()


def save_session_profile(profile: dict) -> Path:
    """Save session profile to the configured reports directory."""
    reports_dir = get_reports_dir()
    path = reports_dir / "session_profile.json"
    with open(path, "w") as f:
        json.dump(profile, f, indent=2)
    return path


def main():
    auto = "--auto" in sys.argv

    if auto:
        # Emit the intake prompt for the agent to present
        print(emit_agent_intake_prompt())
        return 0

    # Interactive mode: print the intake prompt and structured instructions
    # for the agent to use when it calls this script
    print("=" * 60)
    print("  InvestorClaw Session Initialization")
    print("  Risk Calibration Intake")
    print("=" * 60)
    print()
    print(emit_agent_intake_prompt())
    print()
    print("─" * 60)
    print("AGENT INSTRUCTIONS:")
    print("Present the above questions to the user.")
    print("When they respond, call: session_init.py --profile <heat> <stance> <concerns>")
    print("Where:")
    print("  heat: 1-5 integer")
    print("  stance: defensive|neutral|opportunistic")
    print("  concerns: comma-separated list of concern keywords")
    print()
    print("Example: session_init.py --profile 3 neutral 'tariffs,oil'")
    print()

    # Also check for --profile mode (called by agent after user responds)
    if "--profile" in sys.argv:
        idx = sys.argv.index("--profile")
        try:
            heat = int(sys.argv[idx + 1])
            stance = sys.argv[idx + 2]
            concerns_raw = sys.argv[idx + 3] if len(sys.argv) > idx + 3 else ""
            concerns = [c.strip() for c in concerns_raw.split(",") if c.strip()]

            profile = build_session_profile(heat, stance, concerns)
            context = format_session_context_for_agent(profile)
            path = save_session_profile(profile)

            print("\n## SESSION PROFILE CONFIRMED")
            print(context)
            print(f"\nProfile saved: {path}")
        except (IndexError, ValueError) as e:
            print(f"Error parsing profile args: {e}", file=sys.stderr)
            return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
