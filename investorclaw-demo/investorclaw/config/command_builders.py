#!/usr/bin/env python3
"""
Command argument synthesis for InvestorClaw skill routing.
Auto-detects input files and synthesizes output paths based on command type.
"""

import os
from pathlib import Path
from typing import Optional
from services.consultation_policy import should_inject_tier3, get_consultation_limit

_ERR_NO_HOLDINGS = "No holdings.json found. Run '/portfolio holdings' first."
_ERR_NO_BONDS = "No bond_analysis.json found. Run '/portfolio bonds' first."


def _find_holdings_file(reports_dir: Path) -> Optional[str]:
    """Return the path to holdings.json, checking .raw/ first (new CDM location)."""
    raw_path = reports_dir / ".raw" / "holdings.json"
    if raw_path.exists():
        return str(raw_path)
    legacy_path = reports_dir / "holdings.json"
    if legacy_path.exists():
        return str(legacy_path)
    return None


def synthesize_command_args(
    command: str,
    script_args: list,
    reports_dir: Path,
) -> tuple[list, int]:
    """
    Synthesize script arguments for a given command based on available data files.

    Args:
        command: Command name (from COMMANDS dict)
        script_args: User-provided script arguments
        reports_dir: Directory where reports are written

    Returns:
        Tuple of (synthesized_args: list, error_code: int)
        error_code is 0 on success, 1 if required files missing
    """
    # If user provided args, return them unchanged
    if script_args:
        return script_args, 0

    # For holdings command, auto-detect portfolio file if not specified
    if command == "holdings":
        # Note: find_portfolio_file() is called before this, so we just construct output
        # This is a fallback; the router typically provides args already
        output_file = str(reports_dir / "holdings.json")
        return [], 0  # Router handles this separately

    # For bonds command, use holdings.json
    if command == "bonds":
        holdings_file = _find_holdings_file(reports_dir)
        if holdings_file:
            output_file = str(reports_dir / "bond_analysis.json")
            return [holdings_file, output_file], 0
        else:
            print(f"❌ {_ERR_NO_HOLDINGS}")
            return [], 1

    # For news/sentiment command, auto-detect holdings.json
    if command in ["news", "sentiment"]:
        holdings_file = _find_holdings_file(reports_dir)
        if holdings_file:
            output_file = str(reports_dir / "portfolio_news.json")
            cache_file = str(reports_dir / "portfolio_news_cache.json")
            model_id = os.environ.get("OPENCLAW_MODEL", "").strip()
            model_args = ["--model", model_id] if model_id else []
            return [holdings_file, output_file, '--cache', cache_file] + model_args, 0
        else:
            print(f"❌ {_ERR_NO_HOLDINGS}")
            return [], 1

    # For run/pipeline command, auto-detect holdings.json
    if command == "run":
        holdings_file = _find_holdings_file(reports_dir)
        if holdings_file:
            return [holdings_file], 0
        else:
            print(f"❌ {_ERR_NO_HOLDINGS}")
            return [], 1

    # For news-plan/fetch-plan, show the adaptive fetch plan
    if command in ["news-plan", "fetch-plan"]:
        holdings_file = _find_holdings_file(reports_dir)
        if holdings_file:
            model_id = os.environ.get("OPENCLAW_MODEL", "").strip()
            args = [holdings_file]
            if model_id:
                args += ["--model", model_id]
            return args, 0
        else:
            print(f"❌ {_ERR_NO_HOLDINGS}")
            return [], 1

    # For analyst/ratings command, auto-detect holdings.json
    if command in ["analyst", "analysts", "ratings"]:
        holdings_file = _find_holdings_file(reports_dir)
        if holdings_file:
            output_file = str(reports_dir / "analyst_data.json")
            args = [holdings_file, output_file]
            # --tier3 injection is handled by the router after arg synthesis;
            # do not duplicate it here. consultation_policy is the authority.
            return args, 0
        else:
            print(f"❌ {_ERR_NO_HOLDINGS}")
            return [], 1

    # For portfolio analysis command
    if command in ["analysis", "portfolio-analysis", "synthesize", "synthesize-opportunities", "multi-factor", "analyze-multi", "recommend", "recommendations"]:
        holdings_file = _find_holdings_file(reports_dir)
        if holdings_file:
            output_file = str(reports_dir / "portfolio_analysis.json")
            return [holdings_file, output_file], 0
        else:
            print(f"❌ {_ERR_NO_HOLDINGS}")
            return [], 1

    # For performance analysis command
    if command in ["analyze", "performance", "returns"]:
        holdings_file = _find_holdings_file(reports_dir)
        if holdings_file:
            output_file = str(reports_dir / "performance.json")
            return [holdings_file, "ytd", "today", output_file], 0
        else:
            print(f"❌ {_ERR_NO_HOLDINGS}")
            return [], 1

    # For report/export command, auto-detect holdings.json
    if command in ["report", "export", "csv", "excel"]:
        holdings_file = _find_holdings_file(reports_dir)
        if holdings_file:
            performance_file = str(reports_dir / "performance.json")
            output_prefix = str(reports_dir / "portfolio_report")
            export_format = "csv" if command == "csv" else ("excel" if command == "excel" else "both")
            return [holdings_file, performance_file, export_format, output_prefix], 0
        else:
            print(f"❌ {_ERR_NO_HOLDINGS}")
            return [], 1

    # For fixed-income command, use bond_analysis.json
    if command in ["fixed-income", "fixed-income-analysis", "bond-strategy"]:
        bond_analysis_file = str(reports_dir / "bond_analysis.json")
        if Path(bond_analysis_file).exists():
            output_file = str(reports_dir / "fixed_income_analysis.json")
            return [bond_analysis_file, output_file], 0
        else:
            print(f"❌ {_ERR_NO_BONDS}")
            return [], 1

    # For session command, pass reports_dir
    # If INVESTORCLAW_AUTO_SESSION=true (agentic/CI), pass a default profile
    # so session_init.py doesn't block waiting for interactive user input.
    if command in ["session", "session-init", "risk-profile", "calibrate"]:
        reports_dir_str = str(reports_dir)
        if os.environ.get("INVESTORCLAW_AUTO_SESSION", "").lower() == "true":
            # heat=3 (Balanced/moderate), stance=neutral, concerns="" (none)
            return [reports_dir_str, "--profile", "3", "neutral", ""], 0
        return [reports_dir_str], 0

    # Default: return empty args (user will provide them)
    return [], 0
