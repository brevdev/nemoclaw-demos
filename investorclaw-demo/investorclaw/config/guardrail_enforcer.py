#!/usr/bin/env python3
"""
Guardrail Enforcer - Language Safety Per Deployment Mode

Enforces appropriate language constraints based on deployment mode:
- Single Investor (EDUCATIONAL): Educational framing only
- FA Professional (ADVISORY): Specific recommendations with audit trail
"""

import re
from typing import Tuple
from config.deployment_modes import DeploymentMode, GuardrailLevel


class GuardrailEnforcer:
    """Enforces guardrail compliance for recommendations."""

    # Words that indicate directives (unsafe in educational mode)
    DIRECTIVE_VERBS = {
        r'\bsell\b', r'\bbuy\b', r'\brebalance\b',
        r'\breduce\b', r'\badd\b', r'\bincrease\b',
        r'\bshould\b', r'\bmust\b', r'\brequire\b',
        r'\bneed\b', r'\bhave to\b', r'\bneed to\b',
    }

    # Words that indicate conditional/educational framing (safe)
    EDUCATIONAL_WORDS = {
        r'\bmay\b', r'\bcould\b', r'\bmight\b',
        r'\bconsider\b', r'\bevaluate\b', r'\breview\b',
        r'\bfor educational\b', r'\bmay indicate\b',
        r'\bquestion\b', r'\bexamine\b',
    }

    def __init__(self, mode: DeploymentMode):
        """Initialize enforcer for a deployment mode."""
        self.mode = mode

        if mode == DeploymentMode.SINGLE_INVESTOR:
            self.guardrail_level = GuardrailLevel.EDUCATIONAL
        elif mode == DeploymentMode.FA_PROFESSIONAL:
            self.guardrail_level = GuardrailLevel.ADVISORY
        else:
            self.guardrail_level = GuardrailLevel.EDUCATIONAL

    def check_recommendation(self, text: str) -> Tuple[bool, str]:
        """
        Check if recommendation complies with guardrails.

        Returns: (is_compliant: bool, message: str)
        """

        if self.guardrail_level == GuardrailLevel.EDUCATIONAL:
            return self._check_educational(text)
        elif self.guardrail_level == GuardrailLevel.ADVISORY:
            return self._check_advisory(text)
        else:
            return True, "Unknown guardrail level"

    def _check_educational(self, text: str) -> Tuple[bool, str]:
        """
        Check educational-level guardrails.

        Educational mode should:
        - Not contain directives (sell, buy, rebalance)
        - Use conditional language (may indicate, might evaluate)
        - Include disclaimers
        - Frame as questions, not answers
        """

        text_lower = text.lower()

        # Check for directive verbs
        for directive in self.DIRECTIVE_VERBS:
            if re.search(directive, text_lower, re.IGNORECASE):
                return False, f"Directive language detected: '{directive}'. Use educational framing instead."

        # Check for required educational framing
        if len(text) > 100:  # Only check longer responses
            has_educational = False
            for edu_word in self.EDUCATIONAL_WORDS:
                if re.search(edu_word, text_lower):
                    has_educational = True
                    break

            if not has_educational:
                return False, "No educational framing detected. Use 'may indicate', 'might evaluate', etc."

        # Check for disclaimer
        if "educational" not in text_lower and "advisor" not in text_lower:
            return False, "Missing advisor/educational disclaimer."

        return True, "Compliant with educational guardrails"

    def _check_advisory(self, text: str) -> Tuple[bool, str]:
        """
        Check advisory-level guardrails.

        FA Professional mode (ADVISORY level):
        - No language restrictions (specific recommendations OK)
        - No educational framing required
        - Audit trail enforcement for compliance (optional, added by caller)
        - Professional disclaimer will be added by caller

        FA mode assumes the advisor is responsible for compliance,
        not the system enforcing language choices.
        """

        # FA mode: No guardrails on language itself
        # The advisor is trusted to follow professional standards
        # System adds audit trail and professional disclaimer separately
        return True, "FA mode: No guardrail restrictions (advisor responsibility)"

    def enforce_recommendation(self, text: str) -> str:
        """
        Enforce guardrails by rewriting non-compliant text.

        Returns: Rewritten text that complies with guardrails
        """

        is_compliant, message = self.check_recommendation(text)

        if is_compliant:
            return text

        if self.guardrail_level == GuardrailLevel.EDUCATIONAL:
            return self._rewrite_educational(text)
        elif self.guardrail_level == GuardrailLevel.ADVISORY:
            return self._rewrite_advisory(text)
        else:
            return text

    def _rewrite_educational(self, text: str) -> str:
        """Rewrite text to be educational."""

        rewritten = text

        # Replace directives with conditional language
        replacements = {
            r'\bsell\b': 'consider selling',
            r'\bbuy\b': 'consider buying',
            r'\brebalance\b': 'might rebalance',
            r'\breduce\b': 'could reduce',
            r'\badd\b': 'might add',
            r'\bincrease\b': 'could increase',
            r'\bshould\b': 'may want to',
            r'\byou must\b': 'some investors might',
        }

        for directive, replacement in replacements.items():
            rewritten = re.sub(directive, replacement, rewritten, flags=re.IGNORECASE)

        # Add disclaimer if missing
        if "educational" not in rewritten.lower():
            rewritten += "\n\n⚠️ Educational purposes only. Consult a qualified financial advisor."

        return rewritten

    def _rewrite_advisory(self, text: str) -> str:
        """Rewrite text to include advisory compliance."""

        rewritten = text

        # Add audit trail if missing
        if "[audit" not in rewritten.lower():
            rewritten += "\n\n[AUDIT: Recommendation generated on analysis of client portfolio]"

        return rewritten

    def add_audit_trail(self, text: str, client_id: str, basis: str) -> str:
        """Add audit trail to a recommendation (FA mode)."""

        from datetime import datetime

        timestamp = datetime.now().isoformat()
        audit = f"\n\n[AUDIT: Client: {client_id}, Date: {timestamp}, Basis: {basis}]"

        return text + audit

    def add_professional_disclaimer(self, text: str) -> str:
        """Add professional advisor disclaimer to recommendations (FA mode)."""

        if self.guardrail_level == GuardrailLevel.EDUCATIONAL:
            # Single investor: educational disclaimer
            if "educational" not in text.lower() and "advisor" not in text.lower():
                disclaimer = "\n\n⚠️  Educational purposes only. Consult a qualified financial advisor before making investment decisions."
            else:
                return text
        else:
            # FA mode (Dangerous Mode): professional disclaimer with elevated risk notice
            if "[professional" not in text.lower():
                disclaimer = (
                    "\n\n[PROFESSIONAL DISCLOSURE — DANGEROUS MODE ACTIVE: "
                    "This analysis is provided by a registered advisor operating under fiduciary duty. "
                    "Recommendations are specific and advisory-grade; they are NOT educational content. "
                    "Recommendations are based on client-specific financial situation, goals, and risk tolerance. "
                    "Past performance does not guarantee future results. "
                    "Client must review all recommendations with their tax and legal advisors. "
                    "This system does not verify advisor licensing or registration status.]"
                )
            else:
                return text

        return text + disclaimer


# Example usage
if __name__ == "__main__":
    # Test educational mode
    enforcer_single = GuardrailEnforcer(DeploymentMode.SINGLE_INVESTOR)

    unsafe_text = "You should rebalance your portfolio. Reduce MSFT to 10% and increase bonds to 40%."
    is_safe, message = enforcer_single.check_recommendation(unsafe_text)
    print(f"Educational mode check: {is_safe} ({message})")
    print(f"Rewritten: {enforcer_single.enforce_recommendation(unsafe_text)}\n")

    # Test advisory mode
    enforcer_fa = GuardrailEnforcer(DeploymentMode.FA_PROFESSIONAL)

    advisory_text = "Based on your moderate risk tolerance and 15-year horizon, I recommend increasing equity allocation from 50% to 65%."
    is_safe, message = enforcer_fa.check_recommendation(advisory_text)
    print(f"Advisory mode check: {is_safe} ({message})\n")

    # Add audit trail
    with_audit = enforcer_fa.add_audit_trail(advisory_text, "CLIENT123", "risk profile and horizon")
    print(f"With audit: {with_audit}")
