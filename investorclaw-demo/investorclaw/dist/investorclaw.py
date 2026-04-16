#!/usr/bin/env python3
"""
InvestorClaw entry point for OpenClaw skill invocation.
Thin router: bootstraps config, resolves command, runs script.
"""

import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent

# Keep import bootstrap minimal and local to the entrypoint. Subprocesses get
# their import paths from runtime/environment.py, so other modules should not
# need to mutate sys.path.
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from config.help_text import show_help
from setup.identity_updater import update_identity
from runtime.bootstrap import run_bootstrap
from runtime.router import resolve_script, synthesize_args, should_prime_guardrails
from runtime.environment import build_env
from runtime.subprocess_runner import run_script


# ---------------------------------------------------------------------------
# Guardrail priming (inlined from guardrail_primer.py — single caller)
# ---------------------------------------------------------------------------

# Models that require automatic session priming before the first query.
_PRIME_REQUIRED = {
    "xai/grok-4-1-fast-reasoning",
    "grok-4-1-fast-reasoning",
    "grok-4-1-fast",
    "xai/grok-4-1-fast",
}


def _auto_prime_guardrails(scripts_dir: Path) -> None:
    """Prime the guardrails session if the active model requires it.

    Called transparently before skill command execution.  A session marker
    prevents re-priming within the same OS session.  Non-fatal on failure.
    """
    guardrails_script = scripts_dir / "model_guardrails.py"
    if not guardrails_script.exists():
        return

    active_model = os.environ.get("OPENCLAW_MODEL", "").strip()
    if not active_model:
        try:
            cfg_path = Path.home() / ".openclaw" / "openclaw.json"
            with open(cfg_path) as fh:
                cfg = json.load(fh)
            active_model = cfg["agents"]["defaults"]["model"]["primary"]
        except Exception:
            return

    if active_model not in _PRIME_REQUIRED:
        return

    model_hash = hashlib.md5(active_model.encode()).hexdigest()[:8]
    marker_dir = Path.home() / ".investorclaw"
    marker_dir.mkdir(parents=True, exist_ok=True)
    marker = marker_dir / f".investorclaw_primed_{model_hash}"
    if marker.exists():
        return

    try:
        result = subprocess.run(
            [sys.executable, str(guardrails_script), "--prime", "--model", active_model],
            check=False, capture_output=True, timeout=90,
        )
        if result.returncode == 0:
            marker.touch()
    except Exception:
        pass  # Non-fatal

SKILL_DIR = ROOT_DIR
SCRIPTS_DIR = SKILL_DIR / "commands"

def main() -> int:
    """Thin router: bootstrap → resolve → build args → run."""
    command = sys.argv[1].lower() if len(sys.argv) > 1 else "setup"

    if command in {"-h", "--help", "help"}:
        show_help()
        return 0

    if command in {"update-identity", "update_identity", "identity"}:
        return update_identity(SKILL_DIR)

    # Bootstrap config/env for all commands except setup/help (which run without config)
    if command not in {"setup", "help", "-h", "--help"}:
        run_bootstrap(SKILL_DIR)

    if should_prime_guardrails(command):
        _auto_prime_guardrails(SCRIPTS_DIR)

    script_path = resolve_script(command, SCRIPTS_DIR)
    if script_path is None:
        return 1

    args, error_code = synthesize_args(command, list(sys.argv[2:]), SKILL_DIR)
    if error_code != 0:
        return error_code

    return run_script(script_path, args, build_env(SKILL_DIR), SKILL_DIR)


if __name__ == "__main__":
    sys.exit(main())
