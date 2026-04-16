"""
InvestorClaw unified pipeline orchestrator.
Provides a single entry point for full portfolio analysis.
"""

import json
from pathlib import Path

from config.schema import normalize_portfolio, validate_portfolio
from services.portfolio_utils import load_holdings_list
from commands.analyze_performance_polars import PerformanceAnalyzer
from commands.export_report import ReportExporter


def run_pipeline(holdings_file: str, output_dir: str = None):
    """Run full pipeline: load → normalize → validate → analyze → export"""

    holdings_path = Path(holdings_file).expanduser()
    if not holdings_path.exists():
        raise FileNotFoundError(f"Holdings file not found: {holdings_file}")

    with open(holdings_path, 'r') as f:
        raw = json.load(f)

    # Normalize + validate
    data = normalize_portfolio(raw)
    validate_portfolio(data)

    # Load holdings list
    holdings = load_holdings_list(data)

    # Output paths
    output_dir = Path(output_dir or Path.home() / "portfolio_reports")
    output_dir.mkdir(parents=True, exist_ok=True)

    holdings_out = output_dir / "holdings.normalized.json"
    performance_out = output_dir / "performance.json"

    # Save normalized holdings snapshot
    with open(holdings_out, 'w') as f:
        json.dump(data, f, indent=2)

    # Run performance analysis
    analyzer = PerformanceAnalyzer()
    perf = analyzer.analyze_portfolio(str(holdings_path), str(performance_out))

    # Export reports
    exporter = ReportExporter()
    exporter.load_data(str(holdings_out), str(performance_out))
    exporter.export_to_csv(str(output_dir / "portfolio_report"))

    return {
        "normalized_holdings": str(holdings_out),
        "performance": str(performance_out),
        "reports_dir": str(output_dir)
    }


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python pipeline.py <holdings.json>")
        exit(1)

    result = run_pipeline(sys.argv[1])

    print("\nPipeline complete:")
    for k, v in result.items():
        print(f"  {k}: {v}")
