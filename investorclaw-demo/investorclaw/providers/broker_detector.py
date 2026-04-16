#!/usr/bin/env python3
"""
Broker detection module for portfolio PDFs and text files.
Identifies brokerage platform before attempting extraction.
"""

import re
from pathlib import Path
from typing import Optional, Dict, List, Tuple
import logging

logger = logging.getLogger(__name__)


class BrokerDetector:
    """Detect brokerage platform from PDF/text content."""

    # Broker signatures: (broker_name, confidence_patterns, required_keywords)
    BROKER_SIGNATURES = {
        'UBS': {
            'confidence_patterns': [
                (r'UBS\s+(?:AG|WEALTH|GLOBAL|FINANCIAL)', 95),
                (r'UBS\s+Wealth\s+Management', 100),
                (r'UBS\s+Financial\s+Services', 95),
                (r'ubs\.com', 85),
                (r'UBS\s+account', 80),
            ],
            'must_haves': ['ROTH', 'SEP', 'IRA'],  # At least one account type indicator
            'distinguishing_features': [
                'account sections with headers',
                'CUSIP codes for bonds',
                'DD/MM/YY date format',
            ]
        },
        'Schwab': {
            'confidence_patterns': [
                (r'Charles\s+Schwab', 100),
                (r'Schwab\.com', 95),
                (r'(?:®|&reg;).*schwab', 90),
                (r'Schwab\s+(?:Account|Statement|Portfolio)', 90),
                (r'SCHWAB', 85),
            ],
            'must_haves': ['††'],  # Ticker markers in Schwab format
            'distinguishing_features': [
                'double-dagger (††) symbols as holders',
                'Schwab-specific account types',
                'brokerage account prefix',
            ]
        },
        'Fidelity': {
            'confidence_patterns': [
                (r'Fidelity\s+Investments', 100),
                (r'fidelity\.com', 95),
                (r'Fidelity\s+(?:Account|Statement|Portfolio)', 90),
                (r'Fidelity\s+Brokerage', 95),
            ],
            'must_haves': ['Fidelity'],
            'distinguishing_features': [
                'Fidelity-specific account structure',
                'detailed cash holdings',
                'Fidelity fund identifiers',
            ]
        },
        'Vanguard': {
            'confidence_patterns': [
                (r'Vanguard', 100),
                (r'vanguard\.com', 95),
                (r'Vanguard\s+(?:Account|Statement|Portfolio)', 90),
            ],
            'must_haves': ['Vanguard'],
            'distinguishing_features': [
                'Vanguard mutual fund format',
                'Admiral/Investor shares distinction',
                'Vanguard account structure',
            ]
        },
        'Interactive Brokers': {
            'confidence_patterns': [
                (r'Interactive\s+Brokers', 100),
                (r'ibkr\.com', 95),
                (r'IBKR', 90),
            ],
            'must_haves': ['Interactive'],
            'distinguishing_features': [
                'IB account structure',
                'multi-currency support indicators',
            ]
        },
        'E-Trade': {
            'confidence_patterns': [
                (r'E[*-]?TRADE', 100),
                (r'etrade\.com', 95),
            ],
            'must_haves': ['ETRADE'],
            'distinguishing_features': [
                'E-Trade account format',
            ]
        },
        'TD Ameritrade': {
            'confidence_patterns': [
                (r'TD\s+Ameritrade', 100),
                (r'tdameritrade\.com', 95),
                (r'Ameritrade', 90),
            ],
            'must_haves': ['TD|Ameritrade'],
            'distinguishing_features': [
                'Ameritrade account structure',
            ]
        },
        'Wells Fargo': {
            'confidence_patterns': [
                (r'Wells\s+Fargo', 100),
                (r'wellsfargo\.com', 95),
            ],
            'must_haves': ['Wells'],
            'distinguishing_features': [
                'Wells Fargo investment platform',
            ]
        }
    }

    def __init__(self, file_path: Path):
        self.file_path = file_path
        self.is_text = str(file_path).endswith('.txt')
        self.content = None
        self.detected_broker = None
        self.confidence_score = 0
        self.detection_details = {}

    def detect(self) -> Tuple[Optional[str], int, Dict]:
        """
        Detect broker from file content.

        Returns:
            Tuple of (broker_name, confidence_score, detection_details)
            - broker_name: Name of detected broker (e.g., 'UBS', 'Schwab')
            - confidence_score: 0-100 confidence
            - detection_details: Details about what was detected
        """
        try:
            # Load content
            self.content = self._load_content()
            if not self.content:
                return None, 0, {'error': 'Could not load file content'}

            # Run detection
            results = self._run_detection()

            if results:
                broker, score, details = results
                self.detected_broker = broker
                self.confidence_score = score
                self.detection_details = details
                return broker, score, details
            else:
                return None, 0, {'error': 'No broker signatures matched'}

        except Exception as e:
            logger.error(f"Broker detection failed: {e}")
            return None, 0, {'error': str(e)}

    def _load_content(self) -> Optional[str]:
        """Load content from PDF or text file."""
        try:
            if self.is_text:
                with open(self.file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    return f.read()
            else:
                # Try pdfplumber first
                try:
                    import pdfplumber
                    with pdfplumber.open(self.file_path) as pdf:
                        text = '\n'.join(page.extract_text() or '' for page in pdf.pages)
                        return text
                except ImportError:
                    logger.warning("pdfplumber not available, skipping PDF detection")
                    return None
        except Exception as e:
            logger.error(f"Error loading content: {e}")
            return None

    def _run_detection(self) -> Optional[Tuple[str, int, Dict]]:
        """Run detection against all broker signatures."""
        results = []
        content_lower = self.content.lower()

        for broker_name, signature in self.BROKER_SIGNATURES.items():
            score = self._calculate_score(broker_name, signature, content_lower)
            if score > 0:
                details = {
                    'broker': broker_name,
                    'confidence': score,
                    'patterns_matched': self._get_matched_patterns(broker_name, signature, content_lower),
                    'has_account_indicators': any(acc in self.content for acc in signature.get('must_haves', [])),
                    'distinguishing_features': signature.get('distinguishing_features', [])
                }
                results.append((broker_name, score, details))

        # Return highest confidence match
        if results:
            results.sort(key=lambda x: x[1], reverse=True)
            return results[0]

        return None

    def _calculate_score(self, broker_name: str, signature: Dict, content_lower: str) -> int:
        """Calculate confidence score for a broker."""
        score = 0

        # Check confidence patterns
        for pattern, weight in signature.get('confidence_patterns', []):
            if re.search(pattern.lower(), content_lower):
                score = max(score, weight)  # Use highest matching pattern

        # Check for required keywords (if any are missing, reduce score)
        if signature.get('must_haves'):
            must_have_found = False
            for keyword in signature['must_haves']:
                if re.search(keyword.lower(), content_lower):
                    must_have_found = True
                    break

            # If must-haves exist but none found, significantly reduce score
            if not must_have_found and score > 0:
                score = score // 2  # Reduce by half

        return max(0, min(100, score))  # Clamp 0-100

    def _get_matched_patterns(self, broker_name: str, signature: Dict, content_lower: str) -> List[str]:
        """Get list of patterns that matched."""
        matched = []
        for pattern, _ in signature.get('confidence_patterns', []):
            if re.search(pattern.lower(), content_lower):
                # Extract pattern name for readability
                pattern_name = pattern[:50].replace(r'\b', '').replace(r'(?:', '')
                matched.append(pattern_name)
        return matched

    def get_extraction_strategy(self, broker_name: Optional[str]) -> List[str]:
        """
        Get recommended extraction strategies for detected broker.

        Returns:
            List of strategy names in priority order:
            ['account_sections', 'schwab_format', 'ubs_bonds', 'text_parsing', 'table_parsing']
        """
        strategies_by_broker = {
            'UBS': ['account_sections', 'ubs_bonds', 'text_parsing', 'table_parsing'],
            'Schwab': ['schwab_format', 'table_parsing', 'text_parsing'],
            'Fidelity': ['table_parsing', 'text_parsing', 'account_sections'],
            'Vanguard': ['table_parsing', 'text_parsing'],
            'Interactive Brokers': ['table_parsing', 'text_parsing'],
            'E-Trade': ['table_parsing', 'text_parsing'],
            'TD Ameritrade': ['table_parsing', 'text_parsing'],
            'Wells Fargo': ['table_parsing', 'text_parsing'],
        }

        # Return strategies for detected broker, or fallback to generic order
        if broker_name and broker_name in strategies_by_broker:
            return strategies_by_broker[broker_name]
        else:
            # Generic fallback order
            return ['account_sections', 'schwab_format', 'ubs_bonds', 'text_parsing', 'table_parsing']

    def create_detection_report(self) -> Dict:
        """Create a detailed detection report."""
        return {
            'file': str(self.file_path),
            'is_text': self.is_text,
            'detected_broker': self.detected_broker,
            'confidence_score': self.confidence_score,
            'detection_details': self.detection_details,
            'recommended_strategies': self.get_extraction_strategy(self.detected_broker),
            'all_candidates': self._get_all_candidates(),
        }

    def _get_all_candidates(self) -> List[Dict]:
        """Get all broker candidates with scores (for debugging)."""
        if not self.content:
            return []

        candidates = []
        content_lower = self.content.lower()

        for broker_name, signature in self.BROKER_SIGNATURES.items():
            score = self._calculate_score(broker_name, signature, content_lower)
            if score > 0:
                candidates.append({
                    'broker': broker_name,
                    'score': score,
                    'patterns': self._get_matched_patterns(broker_name, signature, content_lower)
                })

        candidates.sort(key=lambda x: x['score'], reverse=True)
        return candidates


if __name__ == '__main__':
    import sys

    if len(sys.argv) < 2:
        print("Usage: python broker_detector.py <file_path>")
        sys.exit(1)

    detector = BrokerDetector(Path(sys.argv[1]))
    broker, score, details = detector.detect()

    print(f"\n{'='*60}")
    print(f"BROKER DETECTION REPORT")
    print(f"{'='*60}")
    print(f"File: {sys.argv[1]}")
    print(f"Detected Broker: {broker or 'UNKNOWN'}")
    print(f"Confidence: {score}%")
    print(f"\nDetection Details:")
    for key, value in details.items():
        print(f"  {key}: {value}")

    report = detector.create_detection_report()
    print(f"\nRecommended Strategies:")
    for i, strategy in enumerate(report['recommended_strategies'], 1):
        print(f"  {i}. {strategy}")

    print(f"\nAll Candidates:")
    for candidate in report['all_candidates']:
        print(f"  {candidate['broker']}: {candidate['score']}% ({', '.join(candidate['patterns'][:2])})")
