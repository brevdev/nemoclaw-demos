"""
Unit tests for config/env_loader.py.

Tests the .env file parser used by both the bootstrap chain and subprocess
environment builder.  No filesystem side-effects: all tests use tmp_path.
"""
import sys
from pathlib import Path

_skill_root = Path(__file__).parent.parent
if str(_skill_root) not in sys.path:
    sys.path.insert(0, str(_skill_root))

import pytest
from config.env_loader import load_env_file, apply_env_defaults


# ---------------------------------------------------------------------------
# load_env_file — file presence
# ---------------------------------------------------------------------------

def test_missing_file_returns_empty_dict(tmp_path):
    result = load_env_file(tmp_path / "nonexistent.env")
    assert result == {}


def test_empty_file_returns_empty_dict(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("")
    assert load_env_file(env_file) == {}


# ---------------------------------------------------------------------------
# load_env_file — parsing correctness
# ---------------------------------------------------------------------------

def test_simple_key_value_parsed(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\n")
    assert load_env_file(env_file) == {"FOO": "bar"}


def test_multiple_keys_parsed(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("A=1\nB=2\nC=3\n")
    result = load_env_file(env_file)
    assert result == {"A": "1", "B": "2", "C": "3"}


def test_comment_lines_skipped(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("# this is a comment\nKEY=value\n")
    assert load_env_file(env_file) == {"KEY": "value"}


def test_blank_lines_skipped(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("\n\nKEY=value\n\n")
    assert load_env_file(env_file) == {"KEY": "value"}


def test_lines_without_equals_skipped(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("NOEQUALS\nKEY=value\n")
    assert load_env_file(env_file) == {"KEY": "value"}


def test_value_with_embedded_equals(tmp_path):
    """partition('=') takes the first '=' only — value may contain '='."""
    env_file = tmp_path / ".env"
    env_file.write_text("URL=http://host/path?a=1&b=2\n")
    result = load_env_file(env_file)
    assert result["URL"] == "http://host/path?a=1&b=2"


def test_whitespace_stripped_from_key_and_value(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("  KEY  =  value  \n")
    result = load_env_file(env_file)
    assert result == {"KEY": "value"}


def test_empty_value_allowed(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("EMPTY_KEY=\n")
    result = load_env_file(env_file)
    assert "EMPTY_KEY" in result
    assert result["EMPTY_KEY"] == ""


# ---------------------------------------------------------------------------
# apply_env_defaults — merge semantics
# ---------------------------------------------------------------------------

def test_apply_env_defaults_fills_missing_keys(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("NEW_KEY=from_file\n")
    env = {}
    result = apply_env_defaults(tmp_path, env)
    assert result["NEW_KEY"] == "from_file"


def test_apply_env_defaults_does_not_overwrite_existing(tmp_path):
    env_file = tmp_path / ".env"
    env_file.write_text("EXISTING=from_file\n")
    env = {"EXISTING": "original"}
    result = apply_env_defaults(tmp_path, env)
    assert result["EXISTING"] == "original"


def test_apply_env_defaults_no_file_leaves_env_unchanged(tmp_path):
    env = {"KEY": "value"}
    result = apply_env_defaults(tmp_path, env)
    assert result == {"KEY": "value"}
