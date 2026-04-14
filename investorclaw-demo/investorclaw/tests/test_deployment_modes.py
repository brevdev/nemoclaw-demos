"""
tests/test_deployment_modes.py

Unit tests for feature management and deployment mode enforcement.

Covers:
- SI mode: EDUCATIONAL guardrail level
- FA mode: ADVISORY guardrail level
- SI mode: ETF expansion disabled
- FA mode: ETF expansion enabled
- FA-only features blocked in SI mode (ETF_EXPANSION, TAX_LOSS_HARVESTING,
  COMPLIANCE_DOCUMENTATION, MULTI_PORTFOLIO_MANAGEMENT, AUDIT_TRAIL,
  FIXED_INCOME_ANALYSIS, MODEL_PORTFOLIO_COMPARISON, SECTOR_REBALANCING_TACTICAL)
- Shared features available in both modes
  (HOLDINGS_SNAPSHOT, PERFORMANCE_ANALYSIS, NEWS_SENTIMENT, ANALYST_RATINGS,
   SESSION_CALIBRATION, REPORTS_EXPORT, BASIC_BOND_REPORTING, BOND_ANALYSIS,
   REBALANCING_EDUCATIONAL, SECTOR_ANALYSIS_EDUCATIONAL)
- require_feature raises FeatureNotAvailableError for blocked features
- audit trail: SI=False, FA=True
- business license: SI=False, FA=True
- data retention: SI=90 days, FA=2555 days (7 years compliance)
- LLM recommendation tiers present in both modes
- Portfolio handling: SI expand_etfs=False, FA expand_etfs=True
- Context estimation multiplier correct for both modes
"""

from __future__ import annotations

import pytest

from config.feature_manager import FeatureManager, FeatureNotAvailableError
from config.deployment_modes import DeploymentMode, Feature, GuardrailLevel

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def si():
    return FeatureManager(DeploymentMode.SINGLE_INVESTOR)


@pytest.fixture()
def fa():
    return FeatureManager(DeploymentMode.FA_PROFESSIONAL)


# ---------------------------------------------------------------------------
# Guardrail levels
# ---------------------------------------------------------------------------

def test_si_guardrail_level_is_educational(si):
    assert si.get_guardrail_level() == GuardrailLevel.EDUCATIONAL


def test_fa_guardrail_level_is_advisory(fa):
    assert fa.get_guardrail_level() == GuardrailLevel.ADVISORY


def test_si_and_fa_guardrail_levels_differ(si, fa):
    assert si.get_guardrail_level() != fa.get_guardrail_level()


# ---------------------------------------------------------------------------
# ETF expansion
# ---------------------------------------------------------------------------

def test_si_etf_expansion_disabled(si):
    assert si.should_expand_etfs() is False


def test_fa_etf_expansion_enabled(fa):
    assert fa.should_expand_etfs() is True


# ---------------------------------------------------------------------------
# Shared features: available in both modes
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("feature", [
    Feature.HOLDINGS_SNAPSHOT,
    Feature.PERFORMANCE_ANALYSIS,
    Feature.NEWS_SENTIMENT,
    Feature.ANALYST_RATINGS,
    Feature.SESSION_CALIBRATION,
    Feature.REPORTS_EXPORT,
    Feature.BASIC_BOND_REPORTING,
    Feature.BOND_ANALYSIS,
    Feature.REBALANCING_EDUCATIONAL,
    Feature.SECTOR_ANALYSIS_EDUCATIONAL,
])
def test_shared_feature_enabled_in_si(si, feature):
    assert si.is_feature_enabled(feature)


@pytest.mark.parametrize("feature", [
    Feature.HOLDINGS_SNAPSHOT,
    Feature.PERFORMANCE_ANALYSIS,
    Feature.NEWS_SENTIMENT,
    Feature.ANALYST_RATINGS,
    Feature.SESSION_CALIBRATION,
    Feature.REPORTS_EXPORT,
    Feature.BASIC_BOND_REPORTING,
    Feature.BOND_ANALYSIS,
    Feature.REBALANCING_EDUCATIONAL,
    Feature.SECTOR_ANALYSIS_EDUCATIONAL,
])
def test_shared_feature_enabled_in_fa(fa, feature):
    assert fa.is_feature_enabled(feature)


# ---------------------------------------------------------------------------
# FA-only features: blocked in SI, available in FA
# ---------------------------------------------------------------------------

FA_ONLY_FEATURES = [
    Feature.ETF_EXPANSION,
    Feature.ETF_CONSTITUENT_ANALYSIS,
    Feature.TAX_LOSS_HARVESTING,
    Feature.SECTOR_REBALANCING_TACTICAL,
    Feature.MODEL_PORTFOLIO_COMPARISON,
    Feature.COMPLIANCE_DOCUMENTATION,
    Feature.MULTI_PORTFOLIO_MANAGEMENT,
    Feature.AUDIT_TRAIL,
    Feature.FIXED_INCOME_ANALYSIS,
]


@pytest.mark.parametrize("feature", FA_ONLY_FEATURES)
def test_fa_only_feature_disabled_in_si(si, feature):
    assert not si.is_feature_enabled(feature)


@pytest.mark.parametrize("feature", FA_ONLY_FEATURES)
def test_fa_only_feature_enabled_in_fa(fa, feature):
    assert fa.is_feature_enabled(feature)


# ---------------------------------------------------------------------------
# require_feature raises FeatureNotAvailableError for blocked features
# ---------------------------------------------------------------------------

def test_require_fa_feature_in_si_raises(si):
    with pytest.raises(FeatureNotAvailableError):
        si.require_feature(Feature.ETF_EXPANSION)


def test_require_fa_feature_in_si_error_message_mentions_mode(si):
    with pytest.raises(FeatureNotAvailableError, match="single_investor"):
        si.require_feature(Feature.FIXED_INCOME_ANALYSIS)


def test_require_shared_feature_in_si_does_not_raise(si):
    assert si.require_feature(Feature.HOLDINGS_SNAPSHOT) is True


def test_require_fa_feature_in_fa_does_not_raise(fa):
    assert fa.require_feature(Feature.ETF_EXPANSION) is True


# ---------------------------------------------------------------------------
# Audit trail and compliance
# ---------------------------------------------------------------------------

def test_si_audit_trail_disabled(si):
    assert si.is_audit_trail_enabled() is False


def test_fa_audit_trail_enabled(fa):
    assert fa.is_audit_trail_enabled() is True


def test_si_no_business_license_required(si):
    assert si.requires_business_license() is False


def test_fa_business_license_required(fa):
    assert fa.requires_business_license() is True


def test_si_data_retention_90_days(si):
    assert si.get_data_retention_days() == 90


def test_fa_data_retention_7_years(fa):
    assert fa.get_data_retention_days() == 2555


# ---------------------------------------------------------------------------
# LLM recommendations
# ---------------------------------------------------------------------------

def test_si_has_four_llm_tiers(si):
    recs = si.get_llm_recommendations()
    assert set(recs.keys()) == {"simple", "medium", "complex", "enterprise"}


def test_fa_has_four_llm_tiers(fa):
    recs = fa.get_llm_recommendations()
    assert set(recs.keys()) == {"simple", "medium", "complex", "enterprise"}


def test_si_enterprise_tier_uses_grok(si):
    rec = si.get_llm_recommendations()["enterprise"]
    assert "grok" in rec.model.lower()


def test_fa_complex_tier_uses_grok(fa):
    rec = fa.get_llm_recommendations()["complex"]
    assert "grok" in rec.model.lower()


def test_si_simple_tier_max_holdings_under_100(si):
    rec = si.get_llm_recommendations()["simple"]
    assert rec.max_holdings <= 100


def test_fa_complex_tier_max_holdings_over_500(fa):
    rec = fa.get_llm_recommendations()["complex"]
    assert rec.max_holdings > 500


# ---------------------------------------------------------------------------
# Portfolio handling config
# ---------------------------------------------------------------------------

def test_si_context_multiplier_is_5(si):
    cfg = si.get_portfolio_handling_config()
    assert cfg.context_estimation_multiplier == 5


def test_fa_context_multiplier_is_5(fa):
    cfg = fa.get_portfolio_handling_config()
    assert cfg.context_estimation_multiplier == 5


def test_si_max_holdings_300(si):
    cfg = si.get_portfolio_handling_config()
    assert cfg.max_holdings_without_upgrade == 300


def test_fa_max_holdings_500(fa):
    cfg = fa.get_portfolio_handling_config()
    assert cfg.max_holdings_without_upgrade == 500


# ---------------------------------------------------------------------------
# Guardrail rules
# ---------------------------------------------------------------------------

def test_si_has_guardrail_rules(si):
    rules = si.get_guardrail_rules()
    assert len(rules) > 0


def test_fa_has_guardrail_rules(fa):
    rules = fa.get_guardrail_rules()
    assert len(rules) > 0


def test_si_guardrail_rules_include_disclaimer(si):
    rule_names = [r.name for r in si.get_guardrail_rules()]
    assert "disclaimer_required" in rule_names


def test_fa_guardrail_rules_include_fiduciary(fa):
    rule_names = [r.name for r in fa.get_guardrail_rules()]
    assert "fiduciary_language" in rule_names


# ---------------------------------------------------------------------------
# Invalid mode raises ValueError
# ---------------------------------------------------------------------------

def test_invalid_mode_raises():
    with pytest.raises((ValueError, AttributeError)):
        FeatureManager("not_a_real_mode")
