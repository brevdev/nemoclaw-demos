"""
Subprocess environment builder for InvestorClaw script dispatch.

Constructs the env dict passed to each script subprocess:
  - Inherits os.environ (which already reflects the bootstrap precedence chain)
  - Prepends skill_dir and its parent to PYTHONPATH
  - Applies skill/.env one more time via setdefault (belt-and-suspenders for
    keys only needed at subprocess level and not loaded during bootstrap)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Dict

# env_loader is on PYTHONPATH once bootstrap has run; import deferred to
# build_env() so this module remains importable before sys.path is set up.



def build_env(skill_dir: Path) -> Dict[str, str]:
    """
    Return an environment dict suitable for passing to subprocess.run().

    PYTHONPATH is constructed so that both the InvestorClaw parent directory
    and the skill directory itself are importable inside scripts.
    """
    env = os.environ.copy()

    # Build PYTHONPATH so scripts can import without per-file sys.path surgery:
    #   <InvestorClaw/>       — parent package root
    #   <skill/>              — lib/, runtime/, root-level modules (config_loader, etc.)
    #   <skill/commands/>     — router-mapped command scripts
    #   <skill/internal/>     — tier3_enrichment, ConsultationClient
    #   <skill/rendering/>    — disclaimer_wrapper, compact_serializers, cards, progress
    #   <skill/providers/>    — price_provider, broker_detector, bond/nasdaq data
    #   <skill/services/>     — portfolio_utils, extract_pdf, consultation_policy
    #   <skill/workers/>      — background_enricher
    #   <skill/config/>       — config_loader, deployment_modes, feature_manager, guardrail_enforcer, schema
    #   <skill/setup/>        — setup_wizard, installer, identity_updater, first_run_check
    #   <skill/models/>       — holdings, cdm_portfolio, models, context_budget
    invest_dir      = str(skill_dir.parent.absolute())
    skill_dir_str   = str(skill_dir.absolute())
    commands_dir    = str((skill_dir / "commands").absolute())
    internal_dir    = str((skill_dir / "internal").absolute())
    rendering_dir   = str((skill_dir / "rendering").absolute())
    providers_dir   = str((skill_dir / "providers").absolute())
    services_dir    = str((skill_dir / "services").absolute())
    workers_dir     = str((skill_dir / "workers").absolute())
    config_dir      = str((skill_dir / "config").absolute())
    setup_dir       = str((skill_dir / "setup").absolute())
    models_dir      = str((skill_dir / "models").absolute())
    pythonpath = f"{invest_dir}:{skill_dir_str}:{commands_dir}:{internal_dir}:{rendering_dir}:{providers_dir}:{services_dir}:{workers_dir}:{config_dir}:{setup_dir}:{models_dir}"
    if "PYTHONPATH" in env:
        env["PYTHONPATH"] = pythonpath + ":" + env["PYTHONPATH"]
    else:
        env["PYTHONPATH"] = pythonpath

    # Apply .env a second time for keys that scripts need but bootstrap didn't set
    from config.env_loader import load_env_file
    for k, v in load_env_file(skill_dir / ".env").items():
        env.setdefault(k, v)

    return env
