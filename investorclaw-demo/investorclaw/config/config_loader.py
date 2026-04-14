#!/usr/bin/env python3
"""
Configuration loader for InvestorClaw.

Reads setup_wizard output and applies LLM configuration.
Sets environment variables for the configured LLM.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional


CONFIG_FILE = Path.home() / ".investorclaw" / "setup_config.json"


def load_config() -> Optional[Dict]:
    """
    Load InvestorClaw configuration.

    Returns:
        Configuration dict, or None if not configured
    """
    if not CONFIG_FILE.exists():
        return None

    try:
        with open(CONFIG_FILE, 'r') as f:
            return json.load(f)
    except Exception as e:
        print(f"⚠️  Error loading config: {e}", file=sys.stderr)
        return None


def apply_config(config: Dict) -> None:
    """
    Apply configuration to environment using setdefault.

    Env/config precedence (highest to lowest):
      1. os.environ at process start  — explicit agent or shell overrides
      2. ~/.investorclaw/setup_config.json  — this function (setdefault, fills gaps)
      3. skill/.env  — loaded last by investorclaw.py (setdefault, fills remaining gaps)

    Uses os.environ.setdefault() so that values already present in the
    environment (e.g. set by the calling agent) are never overwritten.

    Args:
        config: Configuration dict from setup_wizard
    """
    model = config.get("model", {})

    # Set LLM environment variables
    if model.get("api_key"):
        provider = model.get("provider", "").lower()
        api_key = model.get("api_key")
        model_name = model.get("model", "")

        # Map provider to environment variable
        env_map = {
            "xai": "XAI_API_KEY",
            "openai": "OPENAI_API_KEY",
        }

        env_var = env_map.get(provider, f"{provider.upper()}_API_KEY")
        os.environ.setdefault(env_var, api_key)

        # Set InvestorClaw model info
        os.environ.setdefault("INVESTORCLAW_API_KEY", api_key)
        os.environ.setdefault("INVESTORCLAW_MODEL", model_name)
        os.environ.setdefault("INVESTORCLAW_PROVIDER", provider)

        # Set base URL based on provider
        base_urls = {
            "openai": "https://api.openai.com/v1",
            "xai": "https://api.x.ai/v1",
        }
        base_url = base_urls.get(provider, "")
        if base_url:
            os.environ.setdefault("INVESTORCLAW_BASE_URL", base_url)

    # Store model info for logging
    os.environ.setdefault("INVESTORCLAW_LLM", model.get("provider", "unknown"))


def get_model_config() -> Dict:
    """Get InvestorClaw model configuration."""
    config = load_config()
    if config:
        return config.get("model", {})
    return {}


def get_deployment_type() -> str:
    """Get deployment type (recommended, local, custom, or unknown)."""
    config = load_config()
    if config:
        return config.get("deployment_type", "unknown")
    return "unknown"


def get_deployment_mode() -> str:
    """Get deployment mode from config (PHASE 9): single_investor or fa_professional."""
    config = load_config()
    if config:
        return config.get("deployment_mode", "single_investor")
    return "single_investor"  # Default to single investor


def is_fa_mode() -> bool:
    """Check if running in FA professional mode."""
    return get_deployment_mode() == "fa_professional"


def is_single_investor_mode() -> bool:
    """Check if running in single investor mode."""
    return get_deployment_mode() == "single_investor"


def get_espp_programs() -> Dict:
    """Get ESPP (Employee Stock Purchase Plan) programs from config.

    Returns dict of employer -> {symbol, shares, notes}
    Used to exclude ESPP shares from concentration risk warnings.
    """
    config = load_config()
    if config:
        return config.get("espp_programs", {})
    return {}


def get_espp_symbols() -> list:
    """Get list of symbols held through ESPP programs.

    Falls back to parsing ESPP_HOLDINGS env var when no config file is present.
    Format: ESPP_HOLDINGS=SYMBOL:account,SYMBOL2:account2
    """
    espp = get_espp_programs()
    from_config = list(set(prog.get("symbol", "") for prog in espp.values() if prog.get("symbol")))
    if from_config:
        return from_config
    # Fallback: parse ESPP_HOLDINGS env var directly
    import os
    espp_str = os.environ.get('ESPP_HOLDINGS', '').strip()
    symbols = []
    for pair in espp_str.split(','):
        if ':' in pair:
            sym = pair.split(':', 1)[0].strip().upper()
            if sym:
                symbols.append(sym)
    return list(set(symbols))


def has_espp_holding(symbol: str) -> bool:
    """Check if a symbol is held through ESPP."""
    return symbol.upper() in [s.upper() for s in get_espp_symbols()]


def initialize() -> bool:
    """
    Initialize configuration.

    Loads config and applies to environment.
    Returns True if configured, False otherwise.
    """
    config = load_config()
    if not config:
        return False

    # Migration: add deployment_mode if missing (pre-mode-system configs)
    if "deployment_mode" not in config:
        config["deployment_mode"] = "single_investor"
        print("Note: Added deployment_mode=single_investor to config (migration).")
        try:
            with open(CONFIG_FILE, 'w') as f:
                json.dump(config, f, indent=2)
        except Exception as e:
            print(f"Warning: Could not save migrated config: {e}", file=sys.stderr)

    apply_config(config)
    return True


if __name__ == "__main__":
    # Test script
    print("InvestorClaw Configuration Loader")
    print("=" * 50)

    if not CONFIG_FILE.exists():
        print(f"\n❌ Configuration not found: {CONFIG_FILE}")
        print("\nRun setup wizard:")
        print("  python skill/setup_wizard.py\n")
        sys.exit(1)

    config = load_config()
    if not config:
        print("❌ Failed to load configuration\n")
        sys.exit(1)

    print(f"\n✓ Configuration loaded")
    print(f"  Deployment: {config.get('deployment_type', 'unknown')}")
    print(f"  Model: {config['model'].get('provider')} / {config['model'].get('model')}")

    initialize()
    print(f"\n✓ Environment variables applied")
    print(f"  INVESTORCLAW_LLM = {os.environ.get('INVESTORCLAW_LLM')}")
    print(f"  INVESTORCLAW_MODEL = {os.environ.get('INVESTORCLAW_MODEL')}\n")
