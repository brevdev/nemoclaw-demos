"""
Command-contract tests for runtime/router.py.

Verifies that every COMMANDS entry resolves to a script file that actually
exists on disk.  These tests act as a release gate: any Phase 4 rename or
move that breaks a router mapping will fail here before reaching production.
"""
import sys
from pathlib import Path

_skill_root = Path(__file__).parent.parent
if str(_skill_root) not in sys.path:
    sys.path.insert(0, str(_skill_root))

import pytest
from runtime.router import COMMANDS, NON_ANALYSIS_COMMANDS, should_prime_guardrails

COMMANDS_DIR = _skill_root / "commands"


# ---------------------------------------------------------------------------
# Every COMMANDS entry must point to an existing script
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command,script", COMMANDS.items())
def test_command_script_exists(command, script):
    """Resolve each COMMANDS entry against the real commands/ directory."""
    resolved = (COMMANDS_DIR / script).resolve()
    assert resolved.exists(), (
        f"Command '{command}' → '{script}' resolved to {resolved} which does not exist. "
        "Update COMMANDS in runtime/router.py or restore the missing file."
    )


# ---------------------------------------------------------------------------
# Canonical command names present (public API surface)
# ---------------------------------------------------------------------------

CANONICAL_COMMANDS = {
    "setup", "holdings", "performance", "analysis", "bonds",
    "news", "analyst", "report", "lookup", "session",
    "guardrails", "consult-setup",
}

@pytest.mark.parametrize("command", sorted(CANONICAL_COMMANDS))
def test_canonical_command_registered(command):
    """Each canonical public command must appear in COMMANDS."""
    assert command in COMMANDS, (
        f"Canonical command '{command}' is missing from COMMANDS registry."
    )


# ---------------------------------------------------------------------------
# Alias consistency: aliases that share a script must resolve to the same file
# ---------------------------------------------------------------------------

def test_aliases_agree_on_script():
    """Aliases that should share a script must map to the same filename."""
    alias_groups = [
        ("holdings", "snapshot", "prices"),
        ("performance", "analyze", "returns"),
        ("bonds", "bond-analysis", "analyze-bonds"),
        ("analyst", "analysts", "ratings"),
        ("report", "export", "csv", "excel"),
        ("news", "sentiment"),
        ("setup", "auto-setup", "init", "initialize"),
        ("run", "pipeline"),
    ]
    for group in alias_groups:
        scripts = {COMMANDS[cmd] for cmd in group if cmd in COMMANDS}
        assert len(scripts) == 1, (
            f"Alias group {group} maps to multiple scripts: {scripts}"
        )


# ---------------------------------------------------------------------------
# Non-analysis guard: setup/report/lookup commands must skip priming
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "setup", "auto-setup", "report", "export", "lookup",
    "guardrails", "session", "ollama-setup",
])
def test_non_analysis_commands_do_not_prime(command):
    assert should_prime_guardrails(command) is False


@pytest.mark.parametrize("command", ["holdings", "bonds", "news", "analyst", "performance"])
def test_analysis_commands_do_prime(command):
    assert should_prime_guardrails(command) is True


# ---------------------------------------------------------------------------
# No orphan scripts: every .py in commands/ is reachable via COMMANDS
# ---------------------------------------------------------------------------

def test_no_orphan_command_scripts():
    """Every .py in commands/ (except __init__.py) must be referenced by COMMANDS."""
    registered = set(COMMANDS.values())
    for script_path in COMMANDS_DIR.glob("*.py"):
        if script_path.name == "__init__.py":
            continue
        assert script_path.name in registered, (
            f"commands/{script_path.name} exists but is not registered in COMMANDS. "
            "Add an entry in runtime/router.py or move the file."
        )
