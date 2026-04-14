#!/usr/bin/env python3
"""
Environment variable loader for InvestorClaw scripts.

Reads .env file and loads API keys into os.environ.
"""

import os
from pathlib import Path
from typing import Dict


def load_env_file(env_file: Path) -> Dict[str, str]:
    """
    Load environment variables from .env file.

    Returns dict of loaded variables (not modified os.environ).
    Caller must decide whether to merge into os.environ.
    """
    env_vars = {}
    if not env_file.exists():
        return env_vars

    try:
        with open(env_file) as fh:
            for line in fh:
                line = line.strip()
                # Skip empty lines and comments
                if not line or line.startswith('#'):
                    continue
                # Parse KEY=VALUE
                if '=' not in line:
                    continue
                key, _, value = line.partition('=')
                env_vars[key.strip()] = value.strip()
    except Exception as e:
        print(f"Warning: Failed to load .env file: {e}")

    return env_vars


def apply_env_defaults(skill_dir: Path, env: Dict[str, str]) -> Dict[str, str]:
    """
    Load .env file and merge with existing env (only if key not already set).

    Returns updated env dict (caller must decide whether to use).
    """
    env_file = skill_dir / ".env"
    loaded = load_env_file(env_file)

    # Merge: loaded vars only fill in missing keys (don't override existing)
    for k, v in loaded.items():
        env.setdefault(k, v)

    return env
