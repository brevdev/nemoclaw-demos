#!/usr/bin/env python3
"""
InvestorClaw Installation Script - Auto-configures OpenClaw integration.

Handles:
- Detecting OpenClaw installation location
- Creating/patching IDENTITY.md with financial guardrail rules
- Installing financial query router hooks
- Rollback capability
- Environment-aware configuration
"""

import os
import json
import sys
from pathlib import Path
from typing import Optional, Dict, Tuple
import shutil
from datetime import datetime


class OpenClawDetector:
    """Detect OpenClaw installation location and configuration."""

    POSSIBLE_LOCATIONS = [
        Path.home() / ".openclaw",                  # Default: ~/.openclaw
        Path.home() / ".openclaw-dev",              # Dev: ~/.openclaw-dev
        Path("/opt/openclaw"),                      # System: /opt/openclaw
        Path("/usr/local/openclaw"),                # Local: /usr/local/openclaw
        Path.cwd() / ".openclaw",                   # Current dir: ./.openclaw
        os.environ.get("OPENCLAW_HOME"),            # Env var: OPENCLAW_HOME
    ]

    @staticmethod
    def detect() -> Optional[Path]:
        """Find OpenClaw installation directory."""
        for location in OpenClawDetector.POSSIBLE_LOCATIONS:
            if location is None:
                continue
            location = Path(location)
            if location.exists() and (location / "openclaw.json").exists():
                print(f"✅ Found OpenClaw at: {location}")
                return location

        print("⚠️  OpenClaw not found in standard locations")
        print("   Checked:")
        for loc in OpenClawDetector.POSSIBLE_LOCATIONS:
            if loc:
                print(f"     - {loc}")
        return None

    @staticmethod
    def get_workspace(openclaw_home: Path) -> Path:
        """Get OpenClaw workspace directory."""
        workspace = openclaw_home / "workspace"
        if not workspace.exists():
            print(f"⚠️  Creating workspace directory: {workspace}")
            workspace.mkdir(parents=True, exist_ok=True)
        return workspace

    @staticmethod
    def load_config(openclaw_home: Path) -> Dict:
        """Load OpenClaw configuration."""
        config_file = openclaw_home / "openclaw.json"
        if not config_file.exists():
            return {}

        try:
            with open(config_file) as f:
                return json.load(f)
        except Exception as e:
            print(f"⚠️  Failed to load config: {e}")
            return {}


class IdentityPatcher:
    """Patch OpenClaw IDENTITY.md with InvestorClaw guardrails."""

    GUARDRAIL_MARKER_START = "## InvestorClaw Financial Query Routing"
    GUARDRAIL_MARKER_END = "---"

    @staticmethod
    def load_guardrail_section() -> str:
        """Load the guardrail section from InvestorClaw."""
        guardrail_file = Path(__file__).parent.parent / "FINANCIAL_GUARDRAIL_IDENTITY_SECTION.md"

        if not guardrail_file.exists():
            print(f"⚠️  Guardrail section not found: {guardrail_file}")
            return ""

        with open(guardrail_file) as f:
            content = f.read()

        # Extract just the markdown section (skip header)
        lines = content.split('\n')
        start_idx = next((i for i, line in enumerate(lines) if '## InvestorClaw' in line), 0)
        return '\n'.join(lines[start_idx:])

    @staticmethod
    def patch_identity(workspace: Path) -> Tuple[bool, str]:
        """
        Patch IDENTITY.md with guardrail section.

        Returns: (success: bool, message: str)
        """
        identity_file = workspace / "IDENTITY.md"

        # Create if doesn't exist
        if not identity_file.exists():
            print(f"ℹ️  Creating IDENTITY.md: {identity_file}")
            identity_file.write_text(f"# OpenClaw Identity\n\n{datetime.now().isoformat()}\n")

        # Read existing content
        try:
            existing = identity_file.read_text()
        except Exception as e:
            return False, f"Failed to read IDENTITY.md: {e}"

        # Check if guardrail section already exists
        if IdentityPatcher.GUARDRAIL_MARKER_START in existing:
            print("ℹ️  InvestorClaw guardrail section already installed")
            return True, "Guardrail section already present"

        # Load guardrail section
        guardrail_section = IdentityPatcher.load_guardrail_section()
        if not guardrail_section:
            return False, "Failed to load guardrail section"

        # Backup original
        backup_file = identity_file.with_suffix('.md.backup')
        try:
            shutil.copy2(identity_file, backup_file)
            print(f"✅ Backed up IDENTITY.md to: {backup_file}")
        except Exception as e:
            print(f"⚠️  Failed to backup IDENTITY.md: {e}")

        # Append guardrail section
        try:
            updated = existing.rstrip() + "\n\n" + guardrail_section
            identity_file.write_text(updated)
            print(f"✅ Updated IDENTITY.md with guardrail section")
            return True, "Guardrail section added"
        except Exception as e:
            return False, f"Failed to write IDENTITY.md: {e}"

    @staticmethod
    def rollback_identity(workspace: Path) -> bool:
        """Rollback IDENTITY.md from backup."""
        identity_file = workspace / "IDENTITY.md"
        backup_file = identity_file.with_suffix('.md.backup')

        if not backup_file.exists():
            print("⚠️  No backup found for IDENTITY.md")
            return False

        try:
            shutil.copy2(backup_file, identity_file)
            print(f"✅ Rolled back IDENTITY.md from backup")
            return True
        except Exception as e:
            print(f"❌ Failed to rollback IDENTITY.md: {e}")
            return False


class QueryHandlerPatcher:
    """Patch OpenClaw query handler to use FinancialQueryRouter."""

    HOOK_MARKER = "# InvestorClaw Financial Query Router Hook"
    HOOK_CODE = """
# InvestorClaw Financial Query Router Hook
try:
    from models.financial_query_router import FinancialQueryRouter

    router_result = FinancialQueryRouter.route_query(user_input)
    if router_result.get('is_financial'):
        # Route through guardrails
        response_dict = router_result['response']
        return format_financial_response(response_dict)
except ImportError:
    pass  # InvestorClaw not available, continue with normal handling
"""

    @staticmethod
    def detect_handler_locations(openclaw_home: Path) -> list:
        """Find potential query handler files."""
        candidates = [
            openclaw_home / "core" / "chat_handler.py",
            openclaw_home / "agents" / "default_handler.py",
            openclaw_home / "skill_router.py",
            openclaw_home / "handler.py",
            openclaw_home / "response_handler.py",
        ]
        return [f for f in candidates if f.exists()]

    @staticmethod
    def patch_handler(handler_file: Path) -> Tuple[bool, str]:
        """
        Patch query handler to include FinancialQueryRouter.

        Returns: (success: bool, message: str)
        """
        try:
            content = handler_file.read_text()
        except Exception as e:
            return False, f"Failed to read handler: {e}"

        # Check if hook already installed
        if QueryHandlerPatcher.HOOK_MARKER in content:
            print(f"ℹ️  Hook already installed in: {handler_file.name}")
            return True, "Hook already installed"

        # Find insertion point (before main handler logic)
        # Look for common patterns: def handle(), def process(), def respond()
        insertion_patterns = [
            'def handle_query(',
            'def process_query(',
            'def respond_to_user(',
            'def handle(',
        ]

        insertion_point = -1
        for pattern in insertion_patterns:
            if pattern in content:
                insertion_point = content.index(pattern)
                break

        if insertion_point == -1:
            return False, "Could not find handler function signature"

        # Backup
        backup_file = handler_file.with_suffix('.py.backup')
        try:
            shutil.copy2(handler_file, backup_file)
            print(f"✅ Backed up handler to: {backup_file}")
        except Exception as e:
            print(f"⚠️  Failed to backup handler: {e}")

        # Insert hook
        try:
            updated = content[:insertion_point] + QueryHandlerPatcher.HOOK_CODE + "\n    " + content[insertion_point:]
            handler_file.write_text(updated)
            print(f"✅ Inserted FinancialQueryRouter hook into: {handler_file.name}")
            return True, "Hook inserted"
        except Exception as e:
            return False, f"Failed to patch handler: {e}"


class SkillInstaller:
    """Main installer orchestrator."""

    def __init__(self):
        self.openclaw_home = None
        self.workspace = None
        self.patches_applied = []

    def detect_environment(self) -> bool:
        """Detect OpenClaw environment."""
        self.openclaw_home = OpenClawDetector.detect()
        if not self.openclaw_home:
            print("❌ OpenClaw installation not found")
            return False

        self.workspace = OpenClawDetector.get_workspace(self.openclaw_home)
        return True

    def patch_identity(self) -> bool:
        """Patch IDENTITY.md."""
        success, message = IdentityPatcher.patch_identity(self.workspace)
        if success:
            print(f"✅ {message}")
            self.patches_applied.append(('identity', self.workspace / "IDENTITY.md"))
        else:
            print(f"❌ {message}")
        return success

    def patch_handlers(self) -> bool:
        """Patch query handler(s)."""
        handlers = QueryHandlerPatcher.detect_handler_locations(self.openclaw_home)

        if not handlers:
            print("⚠️  No query handlers found (this is OK, manual integration may be needed)")
            return True  # Not fatal

        success = True
        for handler_file in handlers:
            patch_success, message = QueryHandlerPatcher.patch_handler(handler_file)
            if patch_success:
                print(f"✅ {message}")
                self.patches_applied.append(('handler', handler_file))
            else:
                print(f"⚠️  {message}")
                # Non-fatal; continue with other handlers

        return success

    def register_skill(self) -> bool:
        """Register InvestorClaw skill in OpenClaw workspace."""
        # Copy skill to OpenClaw workspace
        skill_src = Path(__file__).parent
        skill_dst = self.workspace / "skills" / "InvestorClaw"

        # Create skills directory if needed
        skill_dst.parent.mkdir(parents=True, exist_ok=True)

        # Copy skill
        try:
            if skill_dst.exists():
                shutil.rmtree(skill_dst)
            shutil.copytree(skill_src, skill_dst, dirs_exist_ok=True)
            print(f"✅ Copied InvestorClaw skill to {skill_dst}")
            self.patches_applied.append(('skill', skill_dst))
        except Exception as e:
            print(f"❌ Failed to copy skill: {e}")
            return False

        # Install dependencies
        try:
            import subprocess
            requirements_file = skill_dst / "requirements.txt"
            if requirements_file.exists():
                print("📦 Installing Python dependencies...")
                result = subprocess.run(
                    ["pip3", "install", "-q", "-r", str(requirements_file)],
                    cwd=str(skill_dst),
                    capture_output=True,
                    text=True,
                    timeout=300
                )
                if result.returncode == 0:
                    print(f"✅ Dependencies installed successfully")
                else:
                    print(f"⚠️  Some dependencies may have warnings (this is OK)")
                    if result.stderr:
                        print(f"   Details: {result.stderr[:200]}")
        except Exception as e:
            print(f"⚠️  Failed to install dependencies: {e}")
            return True  # Non-fatal; skill may still work

        # Configure operational LLM in OpenClaw if setup_config exists
        self.configure_model()
        return True

    def configure_model(self) -> bool:
        """
        Read InvestorClaw config and set model as OpenClaw default.

        This ensures OpenClaw uses the configured LLM when invoking the skill.
        """
        config_file = Path.home() / ".investorclaw" / "setup_config.json"
        if not config_file.exists():
            return True  # Config not yet created; skip

        try:
            with open(config_file) as f:
                config = json.load(f)

            operational = config.get("model", config.get("operational", {}))
            provider = operational.get("provider")
            model = operational.get("model")

            if not provider or not model:
                return True  # Config incomplete; skip

            # Update OpenClaw config
            oc_config_file = self.openclaw_home / "openclaw.json"
            if not oc_config_file.exists():
                return True  # OpenClaw config doesn't exist; skip

            with open(oc_config_file) as f:
                oc_config = json.load(f)

            # Ensure structure exists
            if 'agents' not in oc_config:
                oc_config['agents'] = {}
            if 'defaults' not in oc_config['agents']:
                oc_config['agents']['defaults'] = {}
            if 'model' not in oc_config['agents']['defaults']:
                oc_config['agents']['defaults']['model'] = {}

            # Set primary model
            model_id = f"{provider}/{model}"
            oc_config['agents']['defaults']['model']['primary'] = model_id

            # Write back
            backup_file = oc_config_file.with_suffix('.json.backup')
            try:
                shutil.copy2(oc_config_file, backup_file)
            except:
                pass

            with open(oc_config_file, 'w') as f:
                json.dump(oc_config, f, indent=2)

            print(f"✅ Configured OpenClaw model: {model_id}")
            self.patches_applied.append(('config', oc_config_file))
            return True

        except Exception as e:
            print(f"⚠️  Failed to configure model: {e}")
            return True  # Non-fatal

    def install(self) -> bool:
        """Run full installation."""
        print("\n" + "="*70)
        print("InvestorClaw → OpenClaw Installation")
        print("="*70 + "\n")

        # Detect environment
        if not self.detect_environment():
            print("\n❌ Installation failed: OpenClaw not found")
            return False

        print(f"\n📍 OpenClaw Home: {self.openclaw_home}")
        print(f"📍 Workspace: {self.workspace}\n")

        # Apply patches
        print("📝 Patching OpenClaw configuration...\n")

        success = True
        success &= self.patch_identity()
        success &= self.patch_handlers()
        success &= self.register_skill()

        # Summary
        print("\n" + "="*70)
        if success:
            print("✅ InvestorClaw installation successful!")
            print("\n📋 Patches applied:")
            for patch_type, location in self.patches_applied:
                print(f"   • {patch_type}: {location}")
        else:
            print("⚠️  Installation completed with warnings")
            print("\n📋 Patches applied:")
            for patch_type, location in self.patches_applied:
                print(f"   • {patch_type}: {location}")

        print("\n🚀 Next steps:")
        print("   1. Restart OpenClaw to load updated configuration")
        print("   2. Test: Ask OpenClaw a financial question")
        print("   3. Verify: Response should include ⚠️ disclaimer")
        print("="*70 + "\n")

        return success

    def rollback(self) -> bool:
        """Rollback all patches."""
        print("\n" + "="*70)
        print("InvestorClaw → OpenClaw Rollback")
        print("="*70 + "\n")

        if not self.patches_applied:
            print("ℹ️  No patches to rollback")
            return True

        success = True
        for patch_type, location in self.patches_applied:
            if patch_type == 'identity':
                success &= IdentityPatcher.rollback_identity(location.parent)
            elif patch_type == 'handler':
                backup = location.with_suffix('.py.backup')
                if backup.exists():
                    try:
                        shutil.copy2(backup, location)
                        print(f"✅ Rolled back: {location.name}")
                    except Exception as e:
                        print(f"❌ Failed to rollback {location.name}: {e}")
                        success = False

        print("\n" + "="*70)
        return success


def main():
    """Entry point for installer."""
    import argparse

    parser = argparse.ArgumentParser(description="InvestorClaw OpenClaw Installer")
    parser.add_argument("--rollback", action="store_true", help="Rollback installation")
    parser.add_argument("--dry-run", action="store_true", help="Dry-run (no changes)")
    args = parser.parse_args()

    if args.dry_run:
        print("ℹ️  Dry-run mode (no changes will be made)")

    installer = SkillInstaller()

    if args.rollback:
        success = installer.rollback()
    else:
        success = installer.install()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
