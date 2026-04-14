"""
Unit tests for runtime/router.py.

Tests command resolution and guardrail-priming decisions without needing
actual script files or a live portfolio.
"""
import sys
import tempfile
from pathlib import Path

_skill_root = Path(__file__).parent.parent
if str(_skill_root) not in sys.path:
    sys.path.insert(0, str(_skill_root))

import pytest
from runtime.router import (
    COMMANDS,
    NON_ANALYSIS_COMMANDS,
    resolve_script,
    should_prime_guardrails,
)


# ---------------------------------------------------------------------------
# COMMANDS registry sanity checks
# ---------------------------------------------------------------------------

def test_commands_dict_not_empty():
    assert len(COMMANDS) > 10


def test_all_command_values_are_py_files():
    for cmd, script in COMMANDS.items():
        assert script.endswith(".py"), f"Command '{cmd}' maps to non-.py: {script}"


def test_known_commands_present():
    for cmd in ("holdings", "bonds", "news", "analyst", "performance", "setup"):
        assert cmd in COMMANDS, f"Expected command '{cmd}' missing from COMMANDS"


# ---------------------------------------------------------------------------
# resolve_script
# ---------------------------------------------------------------------------

def test_resolve_script_unknown_command(tmp_path, capsys):
    result = resolve_script("not-a-real-command", tmp_path)
    assert result is None
    captured = capsys.readouterr()
    assert "Unknown command" in captured.err


def test_resolve_script_missing_script_file(tmp_path, capsys):
    # holdings → fetch_holdings.py, but we use an empty tmp dir
    result = resolve_script("holdings", tmp_path)
    assert result is None
    captured = capsys.readouterr()
    assert "Script not found" in captured.err


def test_resolve_script_returns_path_when_file_exists(tmp_path):
    # Create a stub script file so exists() returns True
    (tmp_path / "fetch_holdings.py").touch()
    result = resolve_script("holdings", tmp_path)
    assert result is not None
    assert result == tmp_path / "fetch_holdings.py"


def test_resolve_script_alias(tmp_path):
    """'snapshot' is an alias for 'holdings' → fetch_holdings.py."""
    (tmp_path / "fetch_holdings.py").touch()
    result = resolve_script("snapshot", tmp_path)
    assert result is not None
    assert result.name == "fetch_holdings.py"


# ---------------------------------------------------------------------------
# should_prime_guardrails
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("command", [
    "holdings", "bonds", "news", "analyst", "performance",
    "synthesize", "analysis",
])
def test_analysis_commands_should_prime(command):
    assert should_prime_guardrails(command) is True


@pytest.mark.parametrize("command", list(NON_ANALYSIS_COMMANDS))
def test_non_analysis_commands_skip_priming(command):
    assert should_prime_guardrails(command) is False


# ---------------------------------------------------------------------------
# NON_ANALYSIS_COMMANDS coverage
# ---------------------------------------------------------------------------

def test_setup_in_non_analysis():
    assert "setup" in NON_ANALYSIS_COMMANDS


def test_report_in_non_analysis():
    assert "report" in NON_ANALYSIS_COMMANDS


def test_help_in_non_analysis():
    assert "help" in NON_ANALYSIS_COMMANDS
