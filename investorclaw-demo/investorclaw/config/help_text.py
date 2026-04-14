#!/usr/bin/env python3
"""
Help text and command documentation for InvestorClaw.
"""


def show_help():
    """Display help message."""
    print("""
InvestorClaw - Portfolio & Bond Analysis

Usage: /portfolio <command>

Holdings & Prices
  holdings / snapshot / prices       - Portfolio snapshot with current prices

Performance Analysis
  performance / analyze / returns    - Returns, risk metrics, asset allocation

Bond Analysis
  bonds / bond-analysis              - Bond analysis (YTM, duration, tax yield)

Reports & Exports
  report / export / csv / excel      - Generate CSV/Excel reports

News & Sentiment
  news / sentiment                   - News correlated to holdings

Analyst Data
  analyst / analysts / ratings       - Analyst ratings and price targets

Portfolio Analysis
  analysis / portfolio-analysis      - Educational portfolio analysis
  synthesize / multi-factor / recommend - Multi-factor synthesis

Fixed Income Analysis
  fixed-income / bond-strategy       - Fixed income strategy

Risk Calibration
  session / risk-profile / calibrate - Set risk profile (heat + macro concerns)

Guardrails
  guardrails [--prime] [--query "..."] [--status] - Model compliance enforcement

Setup & Help
  setup / init                       - Auto-discover and consolidate portfolios
  update-identity                    - Update agent IDENTITY.md with rules
  run / pipeline                     - Run full analysis pipeline
  help                               - Show this help message

Reports saved to: ~/portfolio_reports/
Add --verbose to any command for detailed output.
    """.strip())
