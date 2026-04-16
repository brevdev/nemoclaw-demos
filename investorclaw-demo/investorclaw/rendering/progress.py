#!/usr/bin/env python3
"""
Progress reporting system for portfolio analyzer skill.
Provides real-time feedback during long operations.
"""

import sys
import json
from datetime import datetime
from typing import Optional, Dict, Any
from enum import Enum


class Phase(Enum):
    """Progress phases for portfolio analysis operations."""
    INIT = "initializing"
    DISCOVER = "discovering_files"
    EXTRACT_PDF = "extracting_pdf"
    CONVERT_XLS = "converting_excel"
    CONSOLIDATE = "consolidating_portfolios"
    FETCH = "fetching_holdings"
    ANALYZE = "analyzing_performance"
    REPORT = "generating_reports"
    COMPLETE = "complete"
    ERROR = "error"


class ProgressReporter:
    """Report progress of long-running operations."""

    def __init__(self, operation: str = "portfolio_analysis", verbose: bool = True):
        self.operation = operation
        self.verbose = verbose
        self.start_time = datetime.now()
        self.current_phase = None
        self.phase_details = {}

    def bootstrap(self):
        """Send initial acknowledgement."""
        self._report(
            phase=Phase.INIT,
            message="🚀 Starting operation...",
            details={"operation": self.operation}
        )

    def phase(self, phase: Phase, message: str, details: Optional[Dict[str, Any]] = None):
        """Report entering a new phase."""
        self.current_phase = phase
        self.phase_details = details or {}

        phase_icons = {
            Phase.INIT: "🚀",
            Phase.DISCOVER: "🔍",
            Phase.EXTRACT_PDF: "📄",
            Phase.CONVERT_XLS: "📊",
            Phase.CONSOLIDATE: "🔗",
            Phase.FETCH: "💾",
            Phase.ANALYZE: "📈",
            Phase.REPORT: "📑",
            Phase.COMPLETE: "✅",
            Phase.ERROR: "❌",
        }

        icon = phase_icons.get(phase, "→")
        full_message = f"{icon} **{message}**"

        self._report(phase=phase, message=full_message, details=self.phase_details)

    def update(self, message: str, details: Optional[Dict[str, Any]] = None):
        """Report progress within a phase."""
        self._report(
            phase=self.current_phase,
            message=f"  {message}",
            details=details or self.phase_details
        )

    def complete(self, message: str = "Operation complete", summary: Optional[Dict] = None):
        """Report successful completion."""
        elapsed = (datetime.now() - self.start_time).total_seconds()
        details = {
            "elapsed_seconds": round(elapsed, 2),
            **(summary or {})
        }
        self._report(
            phase=Phase.COMPLETE,
            message=f"✅ {message}",
            details=details
        )

    def error(self, message: str, exception: Optional[Exception] = None):
        """Report an error."""
        details = {}
        if exception:
            details["error_type"] = type(exception).__name__
            details["error_message"] = str(exception)

        self._report(
            phase=Phase.ERROR,
            message=f"❌ {message}",
            details=details
        )

    def _report(self, phase: Phase, message: str, details: Optional[Dict] = None):
        """Send progress report."""
        if self.verbose:
            # For CLI: print human-readable format
            print(message)
            if details and any(v for v in details.values() if v):
                for key, value in details.items():
                    if value is not None and value != "":
                        print(f"     {key}: {value}")

        # Always output JSON for agent parsing
        report = {
            "timestamp": datetime.now().isoformat(),
            "operation": self.operation,
            "phase": phase.value,
            "message": message,
            "details": details or {},
        }
        print(json.dumps(report), file=sys.stderr)


# Singleton instance
_reporter = None


def get_reporter(operation: str = "portfolio_analysis", verbose: bool = True) -> ProgressReporter:
    """Get or create the progress reporter."""
    global _reporter
    if _reporter is None:
        _reporter = ProgressReporter(operation, verbose)
    return _reporter


def bootstrap(operation: str = "portfolio_analysis"):
    """Send initial bootstrap acknowledgement."""
    reporter = get_reporter(operation)
    reporter.bootstrap()


def phase(phase: Phase, message: str, details: Optional[Dict[str, Any]] = None):
    """Report a new phase."""
    get_reporter().phase(phase, message, details)


def update(message: str, details: Optional[Dict[str, Any]] = None):
    """Report progress update."""
    get_reporter().update(message, details)


def complete(message: str = "Operation complete", summary: Optional[Dict] = None):
    """Report completion."""
    get_reporter().complete(message, summary)


def error(message: str, exception: Optional[Exception] = None):
    """Report error."""
    get_reporter().error(message, exception)
