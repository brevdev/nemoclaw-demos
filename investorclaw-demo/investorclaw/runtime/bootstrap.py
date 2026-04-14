"""
InvestorClaw startup bootstrap — first-run checks and configuration loading.

Env/config precedence enforced here (highest → lowest):
  1. os.environ at process start  — explicit agent/shell overrides; never touched
  2. ~/.investorclaw/setup_config.json  — applied via os.environ.setdefault()
  3. skill/.env  — applied last via os.environ.setdefault(); fills remaining gaps
"""
from __future__ import annotations

import os
from pathlib import Path


def run_bootstrap(skill_dir: Path) -> None:
    """
    Run startup initialization for a normal InvestorClaw invocation.

    Should be called once per process for all commands except setup/help.
    Imports are deferred so this module is importable before sys.path is fully
    resolved (though in practice investorclaw.py sets sys.path first).
    """
    from setup.first_run_check import check_and_offer
    from config.config_loader import initialize as initialize_config, get_deployment_type
    from services.context_window_monitor import warn_if_low_context

    from config.env_loader import load_env_file

    check_and_offer()
    initialize_config()  # loads setup_config.json; applies via setdefault

    # Load skill/.env last so it only fills remaining gaps in os.environ
    for k, v in load_env_file(skill_dir / ".env").items():
        os.environ.setdefault(k, v)

    # Warn if operational model has insufficient context window
    if get_deployment_type() == "focused":
        warn_if_low_context()
