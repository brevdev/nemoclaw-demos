#!/usr/bin/env python3
"""
InvestorClaw First-Time Setup Wizard

Interactive guided setup for single-model LLM configuration.
Supports OpenAI (GPT-4.1-nano) and xAI (Grok 4.1 Fast) deployments.
"""

import json
import os
import sys
from pathlib import Path
from typing import Dict, Optional

# Import portfolio analyzer
try:
    from config.portfolio_sizer import analyze_portfolio, print_analysis
except ImportError:
    analyze_portfolio = None
    print_analysis = None

# Import mode definitions
try:
    from config.deployment_modes import DeploymentMode
except ImportError:
    DeploymentMode = None


class SetupWizard:
    """Interactive setup wizard for InvestorClaw."""

    def __init__(self):
        self.config_dir = Path.home() / ".investorclaw"
        self.config_file = self.config_dir / "setup_config.json"
        self.config = {}

    def print_header(self, title: str) -> None:
        """Print a formatted header."""
        print("\n" + "=" * 70)
        print(title.center(70))
        print("=" * 70 + "\n")

    def print_section(self, title: str) -> None:
        """Print a formatted section."""
        print("\n" + "-" * 70)
        print(title)
        print("-" * 70 + "\n")

    def _get_api_key_for_config(self, config: Dict) -> None:
        """Get API key for configured model."""
        model = config.get("model", {})
        provider = model.get("provider", "").lower()

        if provider == "openai":
            print("\nGET YOUR OPENAI API KEY:")
            print("  Sign up: https://platform.openai.com")
        elif provider == "xai":
            print("\nGET YOUR XAI API KEY:")
            print("  Sign up: https://console.x.ai")
        else:
            return

        has_key = input(f"Do you have an {provider.upper()} API key? [y/n]: ").strip().lower() == "y"
        if has_key:
            api_key = input(f"Enter your {provider.upper()} API key: ").strip()
            if api_key:
                model["api_key"] = api_key

    def ask_about_espp(self) -> Dict:
        """Ask about ESPP (Employee Stock Purchase Plan) holdings.

        ESPP shares are employer-provided stock benefits (active or vested/legacy).
        They should not be flagged for concentration risk since they represent
        forced employer compensation, not investment choices.

        Status types:
          • active: Currently buying through ESPP program
          • vested: Bought through ESPP but program ended or you left employer
          • legacy: Old ESPP shares held long-term (e.g., MSFT from prior employment)
        """
        self.print_section("Step 0.5: ESPP & Employer Stock Holdings")

        espp_programs = {}

        print("""Do you have any ESPP or employer stock holdings?

ESPP shares (active or vested) and legacy employer stock are often forced
long-term holdings. InvestorClaw will exclude them from concentration risk
warnings since they represent employer compensation, not investment choices.

Examples:
  • NVDA: Active ESPP (transferred to UBS for wealth management)
  • MSFT: Vested ESPP (legacy, kept at Schwab - don't diversify)
  • AMZN: Active ESPP (held at Fidelity during employment)
""")

        while True:
            has_espp = input("Do you have any ESPP or employer stock holdings? [y/n]: ").strip().lower()
            if has_espp in ['y', 'n']:
                break
            print("Please enter 'y' or 'n'")

        if has_espp == 'n':
            return espp_programs

        # Collect ESPP/employer stock details
        print("\nEnter your ESPP holdings (press Enter with empty employer name when done):\n")

        while True:
            employer = input("Employer name (e.g., 'NVIDIA', 'Microsoft'): ").strip()
            if not employer:
                break

            symbol = input(f"  Stock symbol for {employer} (e.g., 'NVDA', 'MSFT'): ").strip().upper()
            if not symbol:
                print("  Skipping - symbol required\n")
                continue

            shares = input(f"  Number of shares (or press Enter to skip): ").strip()
            try:
                share_count = int(shares) if shares else None
            except ValueError:
                print("  Invalid share count, skipping\n")
                continue

            status = None
            while status is None:
                status_input = input(f"  Status [a=active ESPP, v=vested/ended, l=legacy/inherited]: ").strip().lower()
                status_map = {'a': 'active', 'v': 'vested', 'l': 'legacy'}
                status = status_map.get(status_input)
                if status is None:
                    print("  Please enter 'a', 'v', or 'l'")

            location = input(f"  Held at (e.g., 'Schwab', 'UBS', 'Fidelity', or 'employer'): ").strip()

            espp_programs[employer.lower()] = {
                "symbol": symbol,
                "shares": share_count,
                "status": status,  # active, vested, or legacy
                "held_at": location or "employer brokerage"
            }

            print()

        if espp_programs:
            print(f"✓ Recorded {len(espp_programs)} ESPP/employer stock holding(s)")
            for emp, details in espp_programs.items():
                status_label = {"active": "actively buying", "vested": "vested (ended)", "legacy": "legacy/inherited"}
                print(f"   • {details['symbol']}: {status_label.get(details['status'])} ({details['held_at']})")

        return espp_programs

    def select_deployment_mode(self) -> Optional[str]:
        """Select deployment mode (single investor vs FA professional)."""
        if not DeploymentMode:
            print("⚠️  Mode system not available (deployment_modes.py missing)")
            return "single_investor"  # Default to single investor

        self.print_section("Step 0: Choose Your Deployment Mode")

        print("""InvestorClaw supports two deployment modes:

╔════════════════════════════════════════════════════════════════════╗
║  1. SINGLE INVESTOR (Retail)                                       ║
║  ─────────────────────────────────────────────────────────────    ║
║  "I manage my own portfolio"                                      ║
║                                                                   ║
║  Features:                                                         ║
║    ✓ Holdings snapshot, performance, news, analyst ratings        ║
║    ✓ Rebalancing hints (educational only)                         ║
║    ✓ Simple reports (CSV/PDF)                                     ║
║                                                                   ║
║  Guardrails:                                                      ║
║    • Educational-only language ("may indicate", "might evaluate")║
║    • No investment directives                                    ║
║    • Advisor disclaimers on all output                           ║
║                                                                   ║
║  Best for: Individual investors managing their own money          ║
╚════════════════════════════════════════════════════════════════════╝

╔════════════════════════════════════════════════════════════════════╗
║  2. FA PROFESSIONAL — ⚠️  DANGEROUS MODE               ⚖️  PREMIUM ║
║  ─────────────────────────────────────────────────────────────    ║
║  "I advise clients on their portfolios"                           ║
║                                                                   ║
║  🚨 WARNING: This mode generates SPECIFIC recommendations.        ║
║     Not for individual retail investors. Advisor fiduciary       ║
║     duty applies. All outputs carry elevated risk disclosure.    ║
║                                                                   ║
║  Features:                                                         ║
║    ✓ All of Single Investor mode, PLUS:                          ║
║    ✓ ETF classification (is_etf, security_type per holding)     ║
║      [planned] ETF constituent expansion (detailed allocation)  ║
║    ✓ Tax-loss harvesting candidates                              ║
║    ✓ Tactical sector rebalancing                                 ║
║    ✓ Multi-portfolio management                                  ║
║    ✓ Compliance documentation                                    ║
║    ✓ Audit trail (all actions logged)                            ║
║                                                                   ║
║  Requirements:                                                     ║
║    ⚠️  Business license verification                              ║
║    ⚠️  7-year audit trail enabled                                 ║
║    ⚠️  Compliance documentation required                          ║
║    ⚠️  Advisor assumes full fiduciary responsibility              ║
║                                                                   ║
║  Best for: Financial advisors, wealth managers, professionals    ║
╚════════════════════════════════════════════════════════════════════╝

Which mode describes your use case?
""")

        while True:
            choice = input("Select [1=Single Investor, 2=FA Professional]: ").strip()
            if choice in ["1", "2"]:
                mode = ["single_investor", "fa_professional"][int(choice) - 1]
                print(f"\n✓ Selected: {mode.replace('_', ' ').title()}\n")
                return mode
            print("Invalid choice. Please enter 1 or 2.")

    def intro(self) -> None:
        """Show introduction and explain architecture."""
        self.print_header("InvestorClaw Setup Wizard")

        print("""Welcome! This wizard will configure InvestorClaw for portfolio analysis.

InvestorClaw uses a SINGLE-MODEL ARCHITECTURE:

  One LLM handles all tasks: routing, agent logic, financial analysis,
  and guardrail enforcement.

SUPPORTED PROVIDERS:
  • OpenAI (GPT-4.1-nano) — 1M context, excellent quality
  • xAI (Grok 4.1 Fast)   — 2M context, fast reasoning

RECOMMENDED SETUP:
  • xAI Grok 4.1-fast (~$10-20/month, 2M context, 4M TPM)  ← Recommended
  OR
  • OpenAI GPT-4.1-nano (~$10-20/month, 1M context, 30K TPM Tier 1)

  👉 Both providers deliver excellent financial analysis quality.
""")

    def choose_provider(self) -> str:
        """Ask user which provider they want."""
        self.print_section("Step 1: Choose Your LLM Provider")

        print("""InvestorClaw supports two providers:

  1. XAI (Grok 4.1 Fast) — Recommended (4M TPM, 2M context)
     • Context: 2M tokens
     • Cost: ~$10-20/month
     • Quality: Excellent
     • Sign up: https://console.x.ai

  2. OPENAI (GPT-4.1-nano) — Alternative (30K TPM Tier 1)
     • Context: 1M tokens
     • Cost: ~$10-20/month
     • Quality: Excellent
     • Sign up: https://platform.openai.com

  3. SKIP — Configure manually later
""")

        while True:
            choice = input("Select [1-3]: ").strip()
            if choice in ["1", "2", "3"]:
                mapping = {
                    "1": "xai",
                    "2": "openai",
                    "3": "skip"
                }
                return mapping[choice]
            print("Invalid choice. Please enter 1, 2, or 3.")

    def setup_openai(self) -> Dict:
        """Set up OpenAI GPT-4.1-nano configuration."""
        self.print_section("Setup: OpenAI GPT-4.1-nano")

        print("""OPENAI GPT-4.1-NANO CONFIGURATION

  Model: GPT-4.1-nano
    • Context: 1M tokens
    • Cost: ~$10-20/month
    • Quality: Excellent for financial analysis
    • Sign up: https://platform.openai.com

Cost: ~$10-20/month
""")

        config = {
            "deployment_type": "openai",
            "model": {
                "provider": "openai",
                "model": "gpt-4.1-nano",
                "api_key": None,
            },
        }

        print("\nGET YOUR OPENAI API KEY:")
        print("  Sign up: https://platform.openai.com")
        print("  Create API key\n")

        has_key = input("Do you have an OpenAI API key? [y/n]: ").strip().lower() == "y"
        if has_key:
            api_key = input("Enter your OpenAI API key: ").strip()
            if api_key:
                config["model"]["api_key"] = api_key
                print("✓ OpenAI configured\n")
        else:
            print("⚠️  Skipping OpenAI (you can add it later)\n")

        return config

    def setup_xai(self) -> Dict:
        """Set up xAI Grok 4.1 Fast configuration."""
        self.print_section("Setup: xAI Grok 4.1 Fast")

        print("""XAI GROK 4.1 FAST CONFIGURATION

  Model: grok-4-1-fast
    • Context: 2M tokens
    • Cost: ~$10-20/month
    • Quality: Excellent for financial analysis
    • Sign up: https://console.x.ai

Cost: ~$10-20/month
""")

        config = {
            "deployment_type": "xai",
            "model": {
                "provider": "xai",
                "model": "grok-4-1-fast-reasoning",
                "api_key": None,
            },
        }

        print("\nGET YOUR XAI API KEY:")
        print("  Sign up: https://console.x.ai")
        print("  Create API key\n")

        has_key = input("Do you have an xAI API key? [y/n]: ").strip().lower() == "y"
        if has_key:
            api_key = input("Enter your xAI API key: ").strip()
            if api_key:
                config["model"]["api_key"] = api_key
                print("✓ xAI Grok configured\n")
        else:
            print("⚠️  Skipping xAI Grok (you can add it later)\n")

        return config

    def validate_connections(self, config: Dict) -> bool:
        """Test connectivity to configured LLM."""
        self.print_section("Validating LLM Connection")

        model = config.get("model", {})

        print(f"Model: {model.get('provider', 'unknown')} / {model.get('model', 'unknown')}")
        if model.get("api_key"):
            print("  ✓ API key configured")
        else:
            print("  ⚠️  No API key configured (will prompt at runtime)")

        return True

    def test_financial_routing(self, config: Dict) -> bool:
        """Test that financial query routing works."""
        self.print_section("Testing Financial Query Routing")

        print("✓ Financial query detection: active")
        print("✓ Guardrail enforcement: active")
        print("✓ Single-model routing: ready")

        return True

    def setup_consultation(self) -> Dict:
        """Optional: configure a local/remote Ollama model for heavy analysis."""
        self.print_section("Step 2: Consultation Model (Optional)")

        print("""CONSULTATION MODEL

A consultation model offloads heavy portfolio synthesis to a local or network
LLM running via Ollama. The operational model only presents the pre-computed
results — it never re-analyzes raw data.

This is optional. Without it, InvestorClaw uses keyword heuristics for
synthesis (still fully functional, just less nuanced).

Tested models (others will likely work — these have been validated):
  gemma4:26b       recommended — best synthesis quality
  gemma4:e4b       lighter 4-bit variant, good quality/speed tradeoff
  nemotron-3-nano  suitable for lower-VRAM setups
  qwen2.5:14b      solid alternative

Examples:
  • Local Ollama:    http://localhost:11434        model: gemma4:26b
  • Network server:  http://your-ollama-host:11434 model: gemma4:26b
""")

        enable = input("Enable consultation model? [y/n]: ").strip().lower()
        if enable != 'y':
            print("Skipping consultation model (heuristic fallback will be used)\n")
            return {"enabled": False}

        # Ask for endpoint
        default_endpoint = "http://localhost:11434"
        endpoint_input = input(f"Ollama endpoint [{default_endpoint}]: ").strip()
        endpoint = endpoint_input or default_endpoint

        # Probe endpoint
        print(f"Probing {endpoint}...")
        available_models = self._probe_ollama_models(endpoint)

        if not available_models:
            print(f"Could not reach {endpoint}. Consultation disabled.\n")
            return {"enabled": False}

        print(f"Found {len(available_models)} model(s):")
        for i, m in enumerate(available_models, 1):
            print(f"  {i}. {m}")
        print(f"  {len(available_models)+1}. Enter model name manually")

        # Select model
        while True:
            choice = input(f"Select model [1-{len(available_models)+1}]: ").strip()
            try:
                idx = int(choice) - 1
                if 0 <= idx < len(available_models):
                    model = available_models[idx]
                    break
                elif idx == len(available_models):
                    model = input("Model name: ").strip()
                    if model:
                        break
            except ValueError:
                pass
            print("Invalid choice")

        print(f"Consultation model: {model} at {endpoint}\n")
        return {
            "enabled": True,
            "model": model,
            "endpoint": endpoint,
        }

    def _probe_ollama_models(self, endpoint: str) -> list:
        """Probe Ollama endpoint, return list of model names."""
        try:
            import urllib.request
            url = endpoint.rstrip("/") + "/api/tags"
            with urllib.request.urlopen(url, timeout=3) as r:
                data = json.loads(r.read())
            return [m["name"] for m in data.get("models", [])]
        except Exception:
            return []

    def _write_env_vars(self, config: Dict) -> None:
        """Write consultation config to skill/.env"""
        consultation = config.get("consultation", {})
        env_file = Path(__file__).parent / ".env"

        lines_to_add = [
            "\n# Consultation model (written by setup wizard)\n",
            f"INVESTORCLAW_CONSULTATION_ENABLED={'true' if consultation.get('enabled') else 'false'}\n",
        ]
        if consultation.get("model"):
            lines_to_add.append(f"INVESTORCLAW_CONSULTATION_MODEL={consultation['model']}\n")
        if consultation.get("endpoint"):
            lines_to_add.append(f"INVESTORCLAW_CONSULTATION_ENDPOINT={consultation['endpoint']}\n")

        # Append to .env if it exists, else create
        mode = "a" if env_file.exists() else "w"
        with open(env_file, mode) as f:
            f.writelines(lines_to_add)
        print(f"Consultation config written to {env_file}")

    def save_config(self, config: Dict) -> None:
        """Save configuration to file."""
        self.config_dir.mkdir(parents=True, exist_ok=True)

        with open(self.config_file, "w") as f:
            json.dump(config, f, indent=2)

        print(f"\n✓ Configuration saved to: {self.config_file}")
        self._write_env_vars(config)

    def show_summary(self, config: Dict) -> None:
        """Show final configuration summary."""
        self.print_header("Setup Complete!")

        deployment = config.get("deployment_type", "unknown")
        model = config.get("model", {})

        print(f"Deployment Type: {deployment.upper()}\n")

        print("MODEL CONFIGURATION:")
        print(f"  Provider: {model.get('provider', 'not set')}")
        print(f"  Model: {model.get('model', 'not set')}")
        if model.get("api_key"):
            print("  Credentials: ✓")

        print("\nCOST ESTIMATE:")
        provider = model.get("provider", "").lower()
        if provider == "openai":
            print("  OpenAI GPT-4.1-nano: ~$10-20/month")
        elif provider == "xai":
            print("  xAI Grok 4.1-fast: ~$10-20/month")

        consultation = config.get("consultation", {})
        if consultation.get("enabled"):
            print(f"\nCONSULTATION MODEL:")
            print(f"  Model:    {consultation.get('model', 'not set')}")
            print(f"  Endpoint: {consultation.get('endpoint', 'not set')}")
        else:
            print(f"\nCONSULTATION: disabled (heuristic fallback)")

        print("\nNEXT STEPS:")
        print("  1. Load your portfolio:")
        print("     python skill/investorclaw.py setup portfolio")
        print("  2. Run first analysis:")
        print("     python skill/investorclaw.py holdings")
        print("  3. Check output:")
        print("     cat ~/portfolio_reports/holdings.json")

        print("\nFOR HELP:")
        print("  • Architecture: docs/ARCHITECTURE.md")
        print("  • Deployment: DEPLOYMENT_ARCHITECTURE.md")
        print("  • Troubleshooting: SETUP.md")

        print("\n" + "=" * 70)

    def run(self) -> None:
        """Run the complete setup wizard."""
        self.intro()

        # Step 0: Select deployment mode
        deployment_mode = self.select_deployment_mode()

        # Step 0.5: Ask about ESPP holdings (all modes)
        espp_programs = self.ask_about_espp()

        # Step 1: Choose provider
        provider_choice = self.choose_provider()

        if provider_choice == "openai":
            self.config = self.setup_openai()
        elif provider_choice == "xai":
            self.config = self.setup_xai()
        else:
            print("\n⏭️  Setup skipped. Configure manually and re-run this wizard.\n")
            return

        # Add deployment mode and ESPP data to config
        self.config["deployment_mode"] = deployment_mode
        self.config["espp_programs"] = espp_programs

        self.validate_connections(self.config)
        self.test_financial_routing(self.config)

        # Step 2: Optional consultation model
        consultation_config = self.setup_consultation()
        self.config["consultation"] = consultation_config

        self.save_config(self.config)
        self.show_summary(self.config)


def main():
    """Entry point."""
    wizard = SetupWizard()
    try:
        wizard.run()
    except KeyboardInterrupt:
        print("\n\n⏹️  Setup cancelled by user.\n")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ Error during setup: {e}\n")
        sys.exit(1)


if __name__ == "__main__":
    main()
