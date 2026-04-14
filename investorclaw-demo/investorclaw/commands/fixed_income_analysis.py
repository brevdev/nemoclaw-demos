#!/usr/bin/env python3
"""
Fixed Income (Bond) Portfolio Analysis
Provides laddering strategies, duration matching, credit analysis, and income optimization.
"""
import polars as pl
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Tuple
from dataclasses import dataclass, asdict
from rendering.disclaimer_wrapper import DisclaimerWrapper

# Phase 9: Mode and feature enforcement
try:
    from config.feature_manager import FeatureManager, FeatureNotAvailableError
    from config.config_loader import get_deployment_mode
    from config.deployment_modes import DeploymentMode, Feature
    from config.guardrail_enforcer import GuardrailEnforcer
    _features_available = True
except ImportError as e:
    _features_available = False

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

@dataclass
class BondAlert:
    """Bond-specific alert"""
    severity: str  # 'critical', 'medium', 'info'
    category: str  # 'duration', 'credit', 'laddering', 'income', 'concentration'
    message: str
    recommendation: str
    impact: str

class FixedIncomeAnalyzer:
    """Provides educational fixed income analysis for portfolio holdings."""

    # Bond ladder stages
    LADDER_STAGES = {
        '0-2y': 'Short-term (1-2 years)',
        '2-5y': 'Medium-term (2-5 years)',
        '5-10y': 'Long-term (5-10 years)',
        '10+y': 'Very long-term (10+ years)'
    }

    # Duration targets by investor profile
    DURATION_TARGETS = {
        'Conservative': {'target': 4.0, 'range': (3.0, 5.0)},
        'Balanced': {'target': 5.0, 'range': (4.0, 6.0)},
        'Growth': {'target': 6.0, 'range': (5.0, 7.0)}
    }

    # Credit quality distribution targets
    CREDIT_DISTRIBUTION = {
        'Conservative': {'AAA-A': 0.80, 'BBB': 0.15, 'Below-BBB': 0.05},
        'Balanced': {'AAA-A': 0.60, 'BBB': 0.30, 'Below-BBB': 0.10},
        'Growth': {'AAA-A': 0.40, 'BBB': 0.40, 'Below-BBB': 0.20}
    }

    def __init__(self):
        self.bonds = []
        self.alerts = []
        self.recommendations = []

    def load_bond_analysis(self, bond_data_file: str) -> None:
        """Load bond analysis from JSON file"""
        try:
            with open(bond_data_file, 'r') as f:
                data = json.load(f)

            # Handle disclaimer-wrapped format (unwrap if needed)
            if 'data' in data and isinstance(data['data'], dict):
                data = data['data']

            # Support both bond_analyzer formats
            self.bonds = data.get('bonds_analyzed', []) or data.get('individual_bonds', [])

            # Normalize bond fields - map bond_analyzer fields to expected names
            for bond in self.bonds:
                if 'value' not in bond and 'market_value' in bond:
                    bond['value'] = bond['market_value']
                # Map credit_quality_estimate to credit_rating
                if 'credit_rating' not in bond and 'credit_quality_estimate' in bond:
                    bond['credit_rating'] = bond['credit_quality_estimate'] or 'Not Rated'
                # Ensure credit_rating exists
                if 'credit_rating' not in bond:
                    bond['credit_rating'] = 'Not Rated'
                # Map shares to quantity (or default to 1.0 if not present)
                if 'quantity' not in bond:
                    bond['quantity'] = bond.get('shares') or 1.0

            logger.info(f"Loaded {len(self.bonds)} bonds")
        except FileNotFoundError:
            logger.error(f"Bond data file not found: {bond_data_file}")
            raise

    def analyze_duration_risk(self) -> Tuple[List[BondAlert], Dict]:
        """Analyze portfolio duration and interest rate risk"""
        alerts = []
        analysis = {}

        if not self.bonds:
            return alerts, analysis

        # Calculate weighted average duration
        total_value = sum(b['value'] for b in self.bonds)
        if total_value == 0:
            return alerts, analysis

        weighted_duration = sum(
            b['modified_duration'] * b['value'] for b in self.bonds
        ) / total_value

        analysis['weighted_duration'] = weighted_duration
        analysis['total_value'] = total_value

        # Check duration risk
        if weighted_duration > 7:
            alerts.append(BondAlert(
                severity='medium',
                category='duration',
                message=f"Portfolio duration is {weighted_duration:.1f} years (high interest rate risk)",
                recommendation="Interest rate increases will significantly reduce bond values. Consider shortening duration by selling long bonds and buying short bonds.",
                impact="1% interest rate increase = ~{:.1f}% portfolio loss".format(weighted_duration)
            ))
        elif weighted_duration < 2:
            alerts.append(BondAlert(
                severity='info',
                category='duration',
                message=f"Portfolio duration is {weighted_duration:.1f} years (very low interest rate risk)",
                recommendation="Your portfolio is protected from rising rates but has limited upside if rates fall.",
                impact="Limited capital appreciation potential if rates decline"
            ))
        else:
            alerts.append(BondAlert(
                severity='info',
                category='duration',
                message=f"Portfolio duration is {weighted_duration:.1f} years (balanced interest rate risk)",
                recommendation="Your duration is well-balanced for moderate interest rate exposure.",
                impact="Moderate sensitivity to interest rate changes"
            ))

        return alerts, analysis

    def analyze_credit_quality(self) -> Tuple[List[BondAlert], Dict]:
        """Analyze credit quality distribution"""
        alerts = []
        analysis = {}

        if not self.bonds:
            return alerts, analysis

        # Categorize bonds by credit quality
        investment_grade = []
        speculative = []

        for bond in self.bonds:
            rating = bond['credit_rating'].split('/')[0]
            if rating in ['AAA', 'AA+', 'AA', 'AA-', 'A+', 'A', 'A-', 'BBB+', 'BBB', 'BBB-']:
                investment_grade.append(bond)
            else:
                speculative.append(bond)

        ig_value = sum(b['value'] for b in investment_grade)
        spec_value = sum(b['value'] for b in speculative)
        total_value = ig_value + spec_value

        if total_value > 0:
            ig_pct = (ig_value / total_value) * 100
            spec_pct = (spec_value / total_value) * 100
        else:
            ig_pct = spec_pct = 0

        analysis['investment_grade_pct'] = ig_pct
        analysis['speculative_pct'] = spec_pct
        analysis['investment_grade_value'] = ig_value
        analysis['speculative_value'] = spec_value

        # Alert if too much speculative
        if spec_pct > 15:
            alerts.append(BondAlert(
                severity='medium',
                category='credit',
                message=f"Speculative-grade bonds are {spec_pct:.1f}% of portfolio (limit: 15%)",
                recommendation="Reduce speculative bonds by selling high-yield positions. Redeploy to investment-grade.",
                impact="Default risk concentrated in high-risk bonds"
            ))
        elif spec_pct == 0:
            alerts.append(BondAlert(
                severity='info',
                category='credit',
                message=f"All bonds are investment-grade ({ig_pct:.1f}%) - excellent credit quality",
                recommendation="Your portfolio has strong credit protection. Consider adding small allocation to high-yield for yield enhancement if risk tolerance allows.",
                impact="Very low default risk"
            ))
        else:
            alerts.append(BondAlert(
                severity='info',
                category='credit',
                message=f"Investment-grade bonds {ig_pct:.1f}%, Speculative {spec_pct:.1f}% - balanced credit quality",
                recommendation="Your credit quality mix is well-balanced.",
                impact="Controlled default risk"
            ))

        return alerts, analysis

    def analyze_laddering(self) -> Tuple[List[BondAlert], Dict]:
        """Analyze bond ladder (maturity distribution)"""
        alerts = []
        analysis = {}

        if not self.bonds:
            return alerts, analysis

        # Categorize by maturity
        buckets = {
            '0-2y': [],
            '2-5y': [],
            '5-10y': [],
            '10+y': []
        }

        for bond in self.bonds:
            ytm = bond['years_to_maturity']
            if ytm < 2:
                buckets['0-2y'].append(bond)
            elif ytm < 5:
                buckets['2-5y'].append(bond)
            elif ytm < 10:
                buckets['5-10y'].append(bond)
            else:
                buckets['10+y'].append(bond)

        # Calculate distribution
        total_value = sum(b['value'] for b in self.bonds)

        analysis['ladder_distribution'] = {}
        for stage, bonds_in_stage in buckets.items():
            value = sum(b['value'] for b in bonds_in_stage)
            pct = (value / total_value) * 100 if total_value > 0 else 0
            analysis['ladder_distribution'][stage] = {
                'count': len(bonds_in_stage),
                'value': value,
                'percentage': pct
            }

        # Alert if ladder is unbalanced
        percentages = [analysis['ladder_distribution'][s]['percentage'] for s in buckets.keys()]
        max_pct = max(percentages) if percentages else 0
        min_pct = min(percentages) if percentages else 0

        if max_pct > 60:
            alerts.append(BondAlert(
                severity='medium',
                category='laddering',
                message=f"Bond ladder is unbalanced: {max_pct:.1f}% in one maturity bucket",
                recommendation="Rebalance by selling from overweight maturity and buying underweight maturities. A balanced ladder ensures steady income.",
                impact="Concentration risk in one maturity; reinvestment risk if many bonds mature simultaneously"
            ))
        elif min_pct == 0:
            alerts.append(BondAlert(
                severity='medium',
                category='laddering',
                message="No bonds in one or more maturity buckets - ladder is incomplete",
                recommendation="Add bonds to missing maturity buckets to create a proper ladder (equal distribution across 4-5 years).",
                impact="Uneven cash flow from maturities; reinvestment risk"
            ))
        else:
            alerts.append(BondAlert(
                severity='info',
                category='laddering',
                message=f"Bond ladder is well-distributed across maturities",
                recommendation="Maintain current ladder structure. As bonds mature, reinvest in longest maturity bucket.",
                impact="Steady income stream and reinvestment opportunities"
            ))

        return alerts, analysis

    def analyze_income_generation(self) -> Tuple[List[BondAlert], Dict]:
        """Analyze current and projected income"""
        alerts = []
        analysis = {}

        if not self.bonds:
            return alerts, analysis

        total_value = sum(b['value'] for b in self.bonds)
        annual_income = sum(
            (b['quantity'] * b['coupon_rate'] * 100) if b['coupon_rate'] > 0 else 0
            for b in self.bonds
        )

        if total_value > 0:
            current_yield = (annual_income / total_value) * 100
        else:
            current_yield = 0

        analysis['total_bond_value'] = total_value
        analysis['annual_coupon_income'] = annual_income
        analysis['current_yield'] = current_yield

        # Alert based on yield
        if current_yield < 2:
            alerts.append(BondAlert(
                severity='info',
                category='income',
                message=f"Current yield is {current_yield:.2f}% (low income generation)",
                recommendation="Consider adding higher-yielding bonds (corporate, high-yield) if risk tolerance allows.",
                impact="Lower annual income; focus is on capital preservation"
            ))
        elif current_yield > 6:
            alerts.append(BondAlert(
                severity='info',
                category='income',
                message=f"Current yield is {current_yield:.2f}% (strong income generation)",
                recommendation="Your bonds are generating substantial income. Monitor credit quality to ensure sustainability.",
                impact="Higher annual income but may indicate higher credit risk"
            ))
        else:
            alerts.append(BondAlert(
                severity='info',
                category='income',
                message=f"Current yield is {current_yield:.2f}% (balanced income)",
                recommendation="Your yield is in a healthy range for balanced income generation.",
                impact="Moderate income with reasonable risk"
            ))

        return alerts, analysis

    def generate_recommendations(self, investor_profile: str = 'Balanced') -> List[str]:
        """Generate personalized recommendations"""
        recommendations = []

        if not self.bonds:
            recommendations.append("No bonds in portfolio. Consider adding fixed income for stability and income.")
            return recommendations

        # Get duration analysis
        dur_alerts, dur_analysis = self.analyze_duration_risk()
        weighted_duration = dur_analysis.get('weighted_duration', 0)

        # Laddering recommendation
        recommendations.append(
            "Implement a bond ladder: stagger maturities across 4-5 years to ensure steady income and reinvestment opportunities."
        )

        # Credit quality recommendation
        credit_alerts, credit_analysis = self.analyze_credit_quality()
        if credit_analysis['speculative_pct'] > 15:
            recommendations.append(
                "Reduce high-yield bond allocation. Shift to investment-grade for stability."
            )
        else:
            recommendations.append(
                "Your credit quality is well-managed. Maintain investment-grade focus."
            )

        # Duration recommendation
        duration_target = self.DURATION_TARGETS[investor_profile]['target']
        if abs(weighted_duration - duration_target) > 1.0:
            if weighted_duration > duration_target:
                recommendations.append(
                    f"Your duration ({weighted_duration:.1f}y) is too long. Shorten by buying shorter-duration bonds."
                )
            else:
                recommendations.append(
                    f"Your duration ({weighted_duration:.1f}y) is too short. Extend by buying longer-duration bonds."
                )

        # Income recommendation
        income_alerts, income_analysis = self.analyze_income_generation()
        annual_income = income_analysis.get('annual_coupon_income', 0)
        if annual_income > 0:
            recommendations.append(
                f"Your bonds generate ${annual_income:,.0f}/year in coupon income. Consider reinvesting in bond ladder."
            )

        # Tax-loss harvesting
        recommendations.append(
            "Review bonds trading below purchase price for tax-loss harvesting opportunities (in taxable accounts)."
        )

        return recommendations

    def generate_report(self, bond_data_file: str, output_file: str = None) -> Dict:
        """Generate comprehensive fixed income analysis report"""

        # Phase 9: Check feature availability (FA mode only)
        if _features_available:
            try:
                mode_str = get_deployment_mode()
                mode = DeploymentMode(mode_str)
                fm = FeatureManager(mode)
                fm.require_feature(Feature.FIXED_INCOME_ANALYSIS)  # FA-only feature
                logger.info(f"Fixed income analysis enabled for {mode_str} mode")
            except FeatureNotAvailableError as e:
                logger.error(f"Fixed income analysis not available: {e}")
                raise

        self.load_bond_analysis(bond_data_file)

        # Run all analyses
        dur_alerts, dur_analysis = self.analyze_duration_risk()
        self.alerts.extend(dur_alerts)

        credit_alerts, credit_analysis = self.analyze_credit_quality()
        self.alerts.extend(credit_alerts)

        ladder_alerts, ladder_analysis = self.analyze_laddering()
        self.alerts.extend(ladder_alerts)

        income_alerts, income_analysis = self.analyze_income_generation()
        self.alerts.extend(income_alerts)

        # Generate recommendations
        self.recommendations = self.generate_recommendations()

        # Build report
        analysis_data = {
            'bonds_analyzed': len(self.bonds),
            'portfolio_summary': {
                'total_value': income_analysis.get('total_bond_value', 0),
                'annual_income': income_analysis.get('annual_coupon_income', 0),
                'current_yield': income_analysis.get('current_yield', 0),
                'weighted_duration': dur_analysis.get('weighted_duration', 0),
                'investment_grade_pct': credit_analysis.get('investment_grade_pct', 0),
                'speculative_pct': credit_analysis.get('speculative_pct', 0)
            },
            'analysis': {
                'duration': dur_analysis,
                'credit_quality': credit_analysis,
                'laddering': ladder_analysis,
                'income': income_analysis
            },
            'alerts': [asdict(a) for a in self.alerts],
            'recommendations': self.recommendations,
            'education': {
                'duration': {
                    'what': 'Measure of how much a bond price changes when interest rates change',
                    'why': 'Higher duration = bigger price drops if rates rise',
                    'example': '5-year duration bond drops ~5% if rates rise 1%',
                    'goal': 'Match duration to your time horizon'
                },
                'yield_to_maturity': {
                    'what': 'Total return you get from a bond if held to maturity',
                    'why': 'More informative than coupon rate alone',
                    'example': 'Bond with 3% coupon may have 4% YTM if purchased below par',
                    'goal': 'Compare bonds by YTM, not coupon'
                },
                'credit_rating': {
                    'what': 'Assessment of issuer\'s ability to pay interest and principal',
                    'why': 'Lower rated = higher default risk = higher yield',
                    'example': 'AAA-rated Treasury at 4% YTM vs BBB-rated Corp at 5.5% YTM',
                    'goal': 'Diversify credit quality, limit speculative bonds'
                },
                'bond_ladder': {
                    'what': 'Buying bonds with staggered maturity dates (1yr, 2yr, 3yr, etc)',
                    'why': 'Ensures regular income, reinvestment opportunities, and less reinvestment risk',
                    'example': 'Instead of 10 bonds maturing same year, stagger across 5 years',
                    'goal': 'Create steady cash flow from maturities'
                }
            }
        }

        # Phase 9: Apply guardrails based on deployment mode (FA mode only)
        if _features_available:
            try:
                mode_str = get_deployment_mode()
                mode = DeploymentMode(mode_str)
                enforcer = GuardrailEnforcer(mode)

                # Apply appropriate disclaimer based on mode
                fixed_income_text = json.dumps(analysis_data, indent=2, default=str)
                enforcer.add_professional_disclaimer(fixed_income_text)
                logger.info(f"Applied {mode_str} guardrails and disclaimers")
            except Exception as e:
                logger.warning(f"Could not apply mode-specific guardrails: {e}")

        # Wrap with compliance disclaimers (mode-aware: FA Dangerous Mode gets expanded disclaimer)
        _mode_str = mode_str if 'mode_str' in dir() else (get_deployment_mode() if _features_available else None)
        report = DisclaimerWrapper.wrap_output(analysis_data, "Fixed Income (Bond) Portfolio Analysis", compact=True, deployment_mode=_mode_str)

        if output_file:
            DisclaimerWrapper.wrap_and_save(analysis_data, output_file, "Fixed Income (Bond) Portfolio Analysis", deployment_mode=_mode_str)
            logger.info(f"Report saved to {output_file}")

        return report

if __name__ == '__main__':
    if len(sys.argv) < 2:
        print("Usage: python3 fixed_income_analysis.py <bond_data.json> [output.json]")
        print("\nExample:")
        print("  python3 fixed_income_analysis.py ~/portfolio_reports/bond_analysis.json ~/portfolio_reports/fi_analyzer.json")
        sys.exit(1)

    bond_data_file = sys.argv[1]
    output_file = sys.argv[2] if len(sys.argv) > 2 else None

    analyzer = FixedIncomeAnalyzer()
    report = analyzer.generate_report(bond_data_file, output_file)

    print("\n" + "="*60)
    print("FIXED INCOME PORTFOLIO ANALYSIS")
    print("="*60)

    _data = report.get('data', report)
    summary = _data['portfolio_summary']
    print(f"\nTotal Bond Value: ${summary['total_value']:,.2f}")
    print(f"Annual Income: ${summary['annual_income']:,.2f}")
    print(f"Current Yield: {summary['current_yield']:.2f}%")
    print(f"Weighted Duration: {summary['weighted_duration']:.2f} years")
    print(f"Investment Grade: {summary['investment_grade_pct']:.1f}%")
    print(f"Speculative: {summary['speculative_pct']:.1f}%")

    print("\n" + "="*60)
    print("KEY ALERTS")
    print("="*60)
    for alert in _data['alerts']:
        severity_icon = "🔴" if alert['severity'] == 'critical' else "🟡" if alert['severity'] == 'medium' else "ℹ️"
        print(f"\n{severity_icon} {alert['category'].upper()}")
        print(f"   {alert['message']}")
        print(f"   → {alert['recommendation']}")

    print("\n" + "="*60)
    print("RECOMMENDATIONS")
    print("="*60)
    for i, rec in enumerate(_data['recommendations'], 1):
        print(f"{i}. {rec}")

    if output_file:
        print(f"\nFull report saved to: {output_file}")
