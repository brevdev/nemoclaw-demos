#!/usr/bin/env python3
"""
Feature Manager - Runtime feature enablement/enforcement

Controls which features are available for the current deployment mode.
Prevents accessing mode-disabled features (security boundary).
"""

from typing import Set, List
from config.deployment_modes import (
    DeploymentMode,
    Feature,
    GuardrailLevel,
    get_mode,
)


class FeatureManager:
    """Manages feature availability and enforcement per deployment mode."""

    def __init__(self, mode: DeploymentMode):
        """Initialize feature manager for a deployment mode."""
        self.mode = mode
        self.mode_def = get_mode(mode)

        if not self.mode_def:
            raise ValueError(f"Unknown deployment mode: {mode}")

        self.enabled_features = self.mode_def.enabled_features

    def is_feature_enabled(self, feature: Feature) -> bool:
        """Check if a feature is enabled in this mode."""
        return feature in self.enabled_features

    def require_feature(self, feature: Feature) -> bool:
        """
        Require a feature, raise error if not available.
        Use this at feature boundaries to enforce mode restrictions.
        """
        if not self.is_feature_enabled(feature):
            raise FeatureNotAvailableError(
                f"Feature '{feature.value}' is not available in {self.mode.value} mode. "
                f"Available features: {self.list_enabled_features()}"
            )
        return True

    def list_enabled_features(self) -> List[str]:
        """List all enabled features as strings."""
        return [f.value for f in self.enabled_features]

    def list_disabled_features(self) -> List[str]:
        """List all disabled features as strings."""
        all_features = set(Feature)
        disabled = all_features - self.enabled_features
        return [f.value for f in disabled]

    def get_guardrail_level(self) -> GuardrailLevel:
        """Get guardrail enforcement level for this mode."""
        return self.mode_def.guardrail_level

    def get_guardrail_rules(self) -> List:
        """Get guardrail rules for this mode."""
        return self.mode_def.guardrail_rules

    def is_audit_trail_enabled(self) -> bool:
        """Check if audit trail is required."""
        return self.mode_def.audit_trail_enabled

    def requires_business_license(self) -> bool:
        """Check if business license is required."""
        return self.mode_def.requires_business_license

    def get_data_retention_days(self) -> int:
        """Get data retention requirement (days)."""
        return self.mode_def.data_retention_days

    def get_portfolio_handling_config(self):
        """Get portfolio handling configuration."""
        return self.mode_def.portfolio_handling

    def should_expand_etfs(self) -> bool:
        """Should ETFs be expanded to constituents?"""
        return self.mode_def.portfolio_handling.expand_etfs

    def get_llm_recommendations(self) -> dict:
        """Get LLM recommendations for this mode."""
        return self.mode_def.llm_recommendations

    def print_mode_info(self) -> None:
        """Print information about current mode."""
        mode_def = self.mode_def
        print(f"\n{'='*70}")
        print(f"Deployment Mode: {mode_def.display_name}")
        print(f"{'='*70}")
        print(f"\n{mode_def.description}")
        print(f"User Profile: {mode_def.user_profile}")

        print(f"\n📋 Features Enabled ({len(self.enabled_features)}):")
        for feature in sorted(self.enabled_features, key=lambda f: f.value):
            print(f"  ✓ {feature.value}")

        if self.list_disabled_features():
            print(f"\n❌ Features Disabled ({len(self.list_disabled_features())}):")
            for feature_name in sorted(self.list_disabled_features()):
                print(f"  ✗ {feature_name}")

        print(f"\n🛡️  Guardrails: {mode_def.guardrail_level.value.upper()}")
        for rule in mode_def.guardrail_rules:
            print(f"  • {rule.name}: {rule.description}")

        if mode_def.requires_business_license:
            print(f"\n⚖️  Compliance Requirements:")
            print(f"  • Business license required")
            print(f"  • Audit trail enabled: {mode_def.audit_trail_enabled}")
            print(f"  • Data retention: {mode_def.data_retention_days} days")

        print(f"\n{'='*70}\n")


class FeatureNotAvailableError(Exception):
    """Raised when a feature is not available in the current mode."""
    pass


# ============================================================================
# FEATURE USAGE PATTERNS (Examples)
# ============================================================================

def example_usage():
    """Example feature manager usage."""

    # Single investor mode
    fm_single = FeatureManager(DeploymentMode.SINGLE_INVESTOR)

    # Check if ETF expansion is available
    if fm_single.should_expand_etfs():
        print("Expanding ETFs...")
    else:
        print("ETF expansion disabled (single investor mode)")

    # Require a feature (will raise if not available)
    try:
        fm_single.require_feature(Feature.MULTI_PORTFOLIO_MANAGEMENT)
    except FeatureNotAvailableError as e:
        print(f"Cannot use multi-portfolio: {e}")

    # FA professional mode
    fm_fa = FeatureManager(DeploymentMode.FA_PROFESSIONAL)

    # Same check in FA mode
    if fm_fa.should_expand_etfs():
        print("Expanding ETFs (FA mode enabled)...")

    # This will succeed in FA mode
    fm_fa.require_feature(Feature.MULTI_PORTFOLIO_MANAGEMENT)
    print("Multi-portfolio management available in FA mode")

    # Show mode information
    fm_fa.print_mode_info()


if __name__ == "__main__":
    # For testing
    from config.deployment_modes import DeploymentMode
    example_usage()
