#!/usr/bin/env python3
"""
Disclaimer wrapper for InvestorClaw skill outputs.
Ensures all outputs include required legal disclaimers.
"""

from datetime import datetime
from typing import Dict, Any, Optional
import json

# ANSI color codes for terminal output
_RED    = "\033[91m"
_BOLD   = "\033[1m"
_RESET  = "\033[0m"


class DisclaimerWrapper:
    """Wrap analysis outputs with required disclaimers."""

    DISCLAIMER = "⚠️  EDUCATIONAL ANALYSIS - NOT INVESTMENT ADVICE"
    CONSULT_PROFESSIONAL = "Consult a qualified financial adviser before making any investment decisions"

    # FA (Dangerous Mode) disclaimer — shown in red on terminal, prominent in JSON
    FA_DISCLAIMER = (
        "🚨 DANGEROUS MODE ACTIVE — FA PROFESSIONAL (ADVISORY GUARDRAIL) 🚨  "
        "This analysis may contain specific investment recommendations. "
        "NOT for use by individual retail investors. "
        "Recommendations are for licensed advisors acting under fiduciary duty only."
    )
    FA_DISCLAIMER_EXTRA = (
        "ADDITIONAL RISK DISCLOSURES: "
        "(1) Recommendations do not constitute a guarantee of performance. "
        "(2) Past performance does not predict future results. "
        "(3) All advisory recommendations must be reviewed against client IPS and suitability requirements. "
        "(4) Tax and legal implications require separate professional review. "
        "(5) This system does not verify advisor licensing or registration status."
    )

    @staticmethod
    def wrap_output(
        data: Dict[str, Any],
        analysis_type: str = "Portfolio Analysis",
        compact: bool = False,
        deployment_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Wrap analysis output with required disclaimers.

        Args:
            data: The actual analysis data to wrap
            analysis_type: Type of analysis (for logging)
            compact: If True, omit static metadata block (~60 token saving for stdout)
            deployment_mode: If "fa_professional", uses FA Dangerous Mode disclaimer

        Returns:
            Wrapped output with disclaimer, data, and metadata
        """
        is_fa = deployment_mode == "fa_professional"

        disclaimer_text = (
            DisclaimerWrapper.FA_DISCLAIMER if is_fa
            else DisclaimerWrapper.DISCLAIMER
        )

        wrapped = {
            "disclaimer": disclaimer_text,
            "is_investment_advice": False,
            "consult_professional": DisclaimerWrapper.CONSULT_PROFESSIONAL,
            "analysis_type": analysis_type,
            "data": data,
            "generated_at": datetime.now().isoformat(),
        }

        if is_fa:
            wrapped["fa_risk_disclosure"] = DisclaimerWrapper.FA_DISCLAIMER_EXTRA
            wrapped["deployment_mode"] = "fa_professional — Dangerous Mode"

        if not compact:
            wrapped["metadata"] = {
                "compliance": (
                    "FA PROFESSIONAL mode: Outputs may include specific recommendations. "
                    "Advisor assumes full fiduciary responsibility."
                    if is_fa else
                    "All outputs are educational only, not investment recommendations"
                ),
                "liability": "User assumes all liability for investment decisions",
                "review": "Review all data with qualified financial professional",
            }
        return wrapped

    @staticmethod
    def wrap_and_save(
        data: Dict[str, Any],
        output_file: str,
        analysis_type: str = "Portfolio Analysis",
        deployment_mode: Optional[str] = None,
    ) -> None:
        """
        Wrap output and save to JSON file.

        Args:
            data: The actual analysis data to wrap
            output_file: Path to output JSON file
            analysis_type: Type of analysis
            deployment_mode: If "fa_professional", uses FA Dangerous Mode disclaimer
        """
        wrapped = DisclaimerWrapper.wrap_output(data, analysis_type, deployment_mode=deployment_mode)
        with open(output_file, 'w') as f:
            json.dump(wrapped, f, indent=2, default=str)

    @staticmethod
    def print_disclaimer(stream=None, deployment_mode: Optional[str] = None) -> None:
        """Print disclaimer to stdout or custom stream.

        FA (Dangerous Mode) disclaimer is printed in red with extended risk disclosures.
        """
        import sys
        target = stream or sys.stdout
        is_fa = deployment_mode == "fa_professional"

        if is_fa:
            print(
                f"\n{_RED}{_BOLD}{'═' * 72}{_RESET}",
                file=target,
            )
            print(
                f"{_RED}{_BOLD}  🚨  DANGEROUS MODE — FA PROFESSIONAL  🚨{_RESET}",
                file=target,
            )
            print(
                f"{_RED}{_BOLD}{'═' * 72}{_RESET}",
                file=target,
            )
            print(
                f"{_RED}  {DisclaimerWrapper.FA_DISCLAIMER}{_RESET}",
                file=target,
            )
            print(
                f"{_RED}  {DisclaimerWrapper.FA_DISCLAIMER_EXTRA}{_RESET}",
                file=target,
            )
            print(
                f"{_RED}{_BOLD}{'═' * 72}{_RESET}\n",
                file=target,
            )
        else:
            print(f"\n{DisclaimerWrapper.DISCLAIMER}", file=target)
            print(f"{DisclaimerWrapper.CONSULT_PROFESSIONAL}\n", file=target)

    @staticmethod
    def add_mandatory_fields(
        output_dict: Dict[str, Any],
        deployment_mode: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Add mandatory disclaimer fields to existing output dictionary.
        Used when wrapping already-structured outputs.
        """
        is_fa = deployment_mode == "fa_professional"

        if "disclaimer" not in output_dict:
            output_dict["disclaimer"] = (
                DisclaimerWrapper.FA_DISCLAIMER if is_fa
                else DisclaimerWrapper.DISCLAIMER
            )

        if is_fa and "fa_risk_disclosure" not in output_dict:
            output_dict["fa_risk_disclosure"] = DisclaimerWrapper.FA_DISCLAIMER_EXTRA

        if "is_investment_advice" not in output_dict:
            output_dict["is_investment_advice"] = False

        if "consult_professional" not in output_dict:
            output_dict["consult_professional"] = DisclaimerWrapper.CONSULT_PROFESSIONAL

        if "generated_at" not in output_dict:
            output_dict["generated_at"] = datetime.now().isoformat()

        return output_dict


if __name__ == '__main__':
    # Example usage
    test_data = {
        "holdings": 5,
        "total_value": 100000,
        "cash": 10000
    }

    wrapped = DisclaimerWrapper.wrap_output(test_data, "Test Holdings Analysis")
    print(json.dumps(wrapped, indent=2))
