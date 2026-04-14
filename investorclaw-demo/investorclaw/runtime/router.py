"""
InvestorClaw command router.

Contains the COMMANDS registry, argument synthesis, and tier-3 injection.
This is the single place that maps user commands to scripts and builds
the argument list that gets passed to each script subprocess.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Command → script mapping
# All paths are relative to SCRIPTS_DIR (investorclaw/commands/).
# "../pipeline.py" resolves to the InvestorClaw parent directory.
# ---------------------------------------------------------------------------

COMMANDS: dict = {
    "setup":                         "auto_setup.py",
    "auto-setup":                    "auto_setup.py",
    "init":                          "auto_setup.py",
    "initialize":                    "auto_setup.py",
    "bonds":                         "bond_analyzer.py",
    "bond-analysis":                 "bond_analyzer.py",
    "analyze-bonds":                 "bond_analyzer.py",
    "holdings":                      "fetch_holdings.py",
    "snapshot":                      "fetch_holdings.py",
    "prices":                        "fetch_holdings.py",
    "performance":                   "analyze_performance_polars.py",
    "analyze":                       "analyze_performance_polars.py",
    "returns":                       "analyze_performance_polars.py",
    "synthesize":                    "portfolio_analyzer.py",
    "synthesize-opportunities":      "portfolio_analyzer.py",
    "analyze-multi":                 "portfolio_analyzer.py",
    "multi-factor":                  "portfolio_analyzer.py",
    "recommend":                     "portfolio_analyzer.py",
    "recommendations":               "portfolio_analyzer.py",
    "report":                        "export_report.py",
    "export":                        "export_report.py",
    "csv":                           "export_report.py",
    "excel":                         "export_report.py",
    "news":                          "fetch_portfolio_news.py",
    "sentiment":                     "fetch_portfolio_news.py",
    "news-plan":                     "news_fetch_planner.py",
    "fetch-plan":                    "news_fetch_planner.py",
    "analyst":                       "fetch_analyst_recommendations_parallel.py",
    "analysts":                      "fetch_analyst_recommendations_parallel.py",
    "ratings":                       "fetch_analyst_recommendations_parallel.py",
    "analysis":                      "portfolio_analyzer.py",
    "portfolio-analysis":            "portfolio_analyzer.py",
    "fixed-income":                  "fixed_income_analysis.py",
    "fixed-income-analysis":         "fixed_income_analysis.py",
    "bond-strategy":                 "fixed_income_analysis.py",
    "session":                       "session_init.py",
    "session-init":                  "session_init.py",
    "risk-profile":                  "session_init.py",
    "calibrate":                     "session_init.py",
    "guardrails":                    "model_guardrails.py",
    "guardrail":                     "model_guardrails.py",
    "guardrails-prime":              "model_guardrails.py",
    "guardrails-status":             "model_guardrails.py",
    "lookup":                        "lookup.py",
    "query":                         "lookup.py",
    "detail":                        "lookup.py",
    "ollama-setup":                  "ollama_model_config.py",
    "model-setup":                   "ollama_model_config.py",
    "consult-setup":                 "ollama_model_config.py",
    "eod-report":                    "eod_report.py",
    "eod":                           "eod_report.py",
    "daily-report":                  "eod_report.py",
    "end-of-day":                    "eod_report.py",
    "fa-topics":                     "fa_discussion.py",
    "fa-discussion":                 "fa_discussion.py",
    "discussion-topics":             "fa_discussion.py",
    "run":                           "../pipeline.py",
    "pipeline":                      "../pipeline.py",
}

# Commands that should NOT trigger guardrail auto-priming (saves ~80 tokens/call)
NON_ANALYSIS_COMMANDS: frozenset = frozenset({
    "guardrails", "guardrail", "guardrails-prime", "guardrails-status",
    "setup", "auto-setup", "init", "initialize",
    "session", "session-init", "risk-profile", "calibrate",
    "report", "export", "csv", "excel",
    "lookup", "query", "detail",
    "ollama-setup", "model-setup", "consult-setup",
    "eod-report", "eod", "daily-report", "end-of-day",
    "fa-topics", "fa-discussion", "discussion-topics",
    "help", "update-identity", "update_identity", "identity",
})

# Commands where synthesize_command_args should be called if no user args given
_AUTO_SYNTHESIZE: frozenset = frozenset({
    "bonds", "news", "sentiment", "run", "news-plan", "fetch-plan",
    "analyst", "analysts", "ratings", "analysis", "portfolio-analysis",
    "analyze", "performance", "returns", "report", "export", "csv", "excel",
    "fixed-income", "fixed-income-analysis", "bond-strategy",
    "session", "session-init", "risk-profile", "calibrate",
    "synthesize", "synthesize-opportunities", "analyze-multi", "multi-factor",
    "recommend", "recommendations",
    "lookup", "query", "detail",
})


def resolve_script(command: str, scripts_dir: Path) -> Optional[Path]:
    """
    Return the absolute script Path for *command*, or None on failure.

    Prints actionable error messages to stderr so the caller can simply
    return 1 without additional diagnostics.
    """
    if command not in COMMANDS:
        print(f"❌ Unknown command: {command}", file=sys.stderr)
        print(f"Available commands: {', '.join(sorted(COMMANDS.keys()))}", file=sys.stderr)
        print("Run 'python3 investorclaw.py help' for more information.", file=sys.stderr)
        return None

    script_path = scripts_dir / COMMANDS[command]
    if not script_path.exists():
        print(f"❌ Script not found: {script_path}", file=sys.stderr)
        return None

    return script_path


def synthesize_args(
    command: str,
    user_args: List[str],
    skill_dir: Path,
) -> Tuple[List[str], int]:
    """
    Build the complete argument list for *command*.

    Returns (args, exit_code).  exit_code != 0 indicates a hard error
    (e.g. required input file missing); the caller should propagate it
    directly as the process exit code.

    Injection order:
      1. User-provided args (pass-through when present)
      2. Auto-synthesized args from command_builders (when user gave none)
      3. --tier3 / --tier3-limit appended by consultation_policy (authority)
    """
    from config.path_resolver import find_portfolio_file, get_reports_dir
    from services.consultation_policy import should_inject_tier3, get_consultation_limit, get_dynamic_consultation_limit

    reports_dir = get_reports_dir()
    args = list(user_args)

    # Holdings: special-case source-file detection
    if command == "holdings" and not args:
        portfolio_file = find_portfolio_file(skill_dir)
        if portfolio_file:
            # Full CDM goes to .raw/holdings.json; compact summary saved to holdings_summary.json
            raw_dir = reports_dir / ".raw"
            raw_dir.mkdir(parents=True, exist_ok=True)
            args = [portfolio_file, str(raw_dir / "holdings.json")]
        else:
            print(
                "❌ No portfolio file found. "
                "Run '/portfolio setup' first to extract holdings.",
                file=sys.stderr,
            )
            return [], 1

    # Lookup/query: always prepend reports_dir so lookup.py can locate .raw/
    if command in ("lookup", "query", "detail"):
        args = [str(reports_dir)] + list(user_args)
        return args, 0

    # General argument synthesis for all other auto-synthesize commands
    if command in _AUTO_SYNTHESIZE and not args:
        from config.command_builders import synthesize_command_args
        args, error_code = synthesize_command_args(command, args, reports_dir)
        if error_code != 0:
            return [], error_code

    # Tier-3 consultation injection — consultation_policy is the single authority
    if should_inject_tier3(command) and "--tier3" not in args:
        args.append("--tier3")
        # Use dynamic limit scaled to portfolio size when holdings_summary is available
        limit = get_consultation_limit(command)
        try:
            holdings_summary = reports_dir / "holdings_summary.json"
            if holdings_summary.exists():
                import json as _json
                with open(holdings_summary) as _f:
                    _hs = _json.load(_f)
                _pc = _hs.get("data", _hs).get("summary", {}).get("position_count", {})
                _equity = _pc.get("equity", 0) if isinstance(_pc, dict) else 0
                if _equity > 0:
                    limit = get_dynamic_consultation_limit(_equity)
        except Exception:
            pass
        if limit:
            args.extend(["--tier3-limit", str(limit)])

    return args, 0


def should_prime_guardrails(command: str) -> bool:
    """Return True if the command should trigger auto-priming of guardrails."""
    return command not in NON_ANALYSIS_COMMANDS
