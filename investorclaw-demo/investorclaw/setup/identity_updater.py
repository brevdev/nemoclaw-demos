#!/usr/bin/env python3
"""
Identity file updater for InvestorClaw data-integrity rules.
Updates workspace IDENTITY.md with guardrails for portfolio data handling.
"""

from pathlib import Path


_IDENTITY_DATA_INTEGRITY_SECTION = """
---

## InvestorClaw Data Integrity Rules

When working with InvestorClaw output, ALWAYS treat the output files as the
authoritative source of truth. Do NOT use cached session-context values.

**Rule: File Authority**
- Before citing any portfolio value (total, equity, bond, cash), READ the
  actual file: `~/portfolio_reports/holdings.json`
- Extract the value from `data.summary.total_portfolio_value` (and related keys)
- NEVER paraphrase from memory what you think the portfolio is worth
- If the file is missing or unreadable, say so — do not invent values

**Why this matters**: Users make financial decisions based on these numbers.
A stale cached value from a previous session is potentially harmful.

**Canonical value locations**:
| Data | File | JSON path |
|------|------|-----------|
| Portfolio total | `~/portfolio_reports/holdings.json` | `data.summary.total_portfolio_value` |
| Equity value | `~/portfolio_reports/holdings.json` | `data.summary.equity_value` |
| Bond value | `~/portfolio_reports/holdings.json` | `data.summary.bond_value` |
| Cash | `~/portfolio_reports/holdings.json` | `data.summary.cash_value` |
| Performance | `~/portfolio_reports/performance.json` | `data.portfolio_summary` |
| Analysis | `~/portfolio_reports/analysis.json` | `data.portfolio_value` |

---

## Financial Advice Guardrail

**EVERY response that discusses portfolio positions, allocation, or potential actions MUST include an explicit disclaimer.**

**Rule: Educational Framing Only**
- NEVER say "Execute", "Buy", "Sell", "Rotate into", or imply an action the user should take immediately
- NEVER suggest specific dollar amounts to move between holdings as a directive
- ALWAYS frame analysis as: "Based on the data...", "For informational purposes...", "A financial advisor might consider..."
- ALWAYS end responses that contain allocation or rebalancing discussion with:
  > ⚠️ **This analysis is for educational purposes only and is not financial advice. Consult a qualified financial advisor before making investment decisions.**

**Why this matters**: Investors may act on agent responses without understanding the risk. A suggestion to "Rotate $100k into NVDA" could cause significant harm if acted upon without professional guidance, especially in volatile markets.

**Triggered by**: Any mention of rebalancing, buying, selling, rotating, trimming, adding to positions, or allocation targets.
"""


def update_identity(skill_dir: Path) -> int:
    """
    Write/update the InvestorClaw data-integrity section into workspace IDENTITY.md.

    Args:
        skill_dir: Path to skill directory

    Returns:
        0 on success, 1 on failure
    """
    # Candidate locations for IDENTITY.md — OpenClaw workspace takes priority
    candidates = [
        Path.home() / ".openclaw" / "workspace" / "IDENTITY.md",       # OpenClaw workspace (primary)
        skill_dir.parent / "IDENTITY.md",                              # skill/../IDENTITY.md (local dev)
    ]

    identity_path = None
    for c in candidates:
        if c.exists():
            identity_path = c
            break

    if identity_path is None:
        # Create at the most likely location
        identity_path = skill_dir.parent / "IDENTITY.md"
        print(f"IDENTITY.md not found; creating at {identity_path}")

    MARKER_START = "## InvestorClaw Data Integrity Rules"
    MARKER_END = "---"

    # Read existing content
    existing = identity_path.read_text() if identity_path.exists() else ""

    # Remove any existing InvestorClaw section to replace with fresh version
    if MARKER_START in existing:
        # Find and strip from the marker to the next "---" separator or EOF
        start_idx = existing.index(MARKER_START)
        # Walk back to the preceding "---" separator line
        preceding = existing.rfind("\n---\n", 0, start_idx)
        if preceding != -1:
            existing = existing[:preceding]
        else:
            existing = existing[:start_idx]
        existing = existing.rstrip()

    new_content = existing + _IDENTITY_DATA_INTEGRITY_SECTION
    identity_path.write_text(new_content)
    print(f"✅ IDENTITY.md updated with data-integrity rules: {identity_path}")
    return 0
