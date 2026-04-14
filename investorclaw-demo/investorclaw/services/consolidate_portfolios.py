#!/usr/bin/env python3
"""
Consolidate multiple portfolio files into a single master portfolio using Polars.
Accepts CSV, XLS, XLSX files and merges them with deduplication and validation.
Polars provides 5-50x faster performance for large portfolio consolidation.
"""
import polars as pl
import sys
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Tuple

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

class PortfolioConsolidator:
    def __init__(self):
        self.portfolios = []
        self.consolidated = None
        self.errors = []
        self.warnings = []
        self.duplicates = []

    def load_portfolio_file(self, file_path: str) -> pl.DataFrame:
        """Load portfolio from CSV or Excel file using Polars."""
        try:
            file_path = Path(file_path).expanduser()

            if not file_path.exists():
                raise FileNotFoundError(f"File not found: {file_path}")

            if file_path.suffix in ['.xls', '.xlsx']:
                df = pl.read_excel(file_path)
            elif file_path.suffix == '.csv':
                df = pl.read_csv(file_path)
            else:
                raise ValueError(f"Unsupported format: {file_path.suffix}")

            logger.info(f"Loaded {len(df)} holdings from {file_path.name}")
            return df

        except Exception as e:
            logger.error(f"Error loading {file_path}: {e}")
            self.errors.append(f"Failed to load {file_path}: {e}")
            return None

    def validate_portfolio(self, df: pl.DataFrame, filename: str) -> bool:
        """Validate portfolio has required columns."""
        required = ['symbol', 'shares', 'purchase_price', 'purchase_date', 'asset_type']
        missing = [col for col in required if col not in df.columns]

        if missing:
            error_msg = f"{filename}: Missing columns {missing}"
            logger.error(error_msg)
            self.errors.append(error_msg)
            return False

        # Check for duplicates within this file
        duplicates = df.filter(pl.col('symbol').is_duplicated())
        if len(duplicates) > 0:
            warning_msg = f"{filename}: Contains {len(duplicates)} duplicate symbols"
            logger.warning(warning_msg)
            self.warnings.append(warning_msg)

        return True

    def normalize_portfolio(self, df: pl.DataFrame, source_name: str = None) -> pl.DataFrame:
        """Normalize portfolio data and add source tracking using Polars."""
        try:
            # Ensure required columns are present
            required = ['symbol', 'shares', 'purchase_price', 'purchase_date', 'asset_type']

            # Create expressions for each required column
            expr_list = []
            for col in required:
                if col in df.columns:
                    if col == 'symbol':
                        # Strip whitespace and convert to uppercase
                        expr_list.append(pl.col(col).str.strip_chars().str.to_uppercase().alias(col))
                    elif col in ['shares', 'purchase_price']:
                        # Convert to float
                        expr_list.append(pl.col(col).cast(pl.Float64).alias(col))
                    elif col == 'purchase_date':
                        # Convert to date string
                        expr_list.append(pl.col(col).cast(pl.Date).cast(pl.Utf8).alias(col))
                    else:
                        expr_list.append(pl.col(col))
                else:
                    # Add missing columns as None
                    expr_list.append(pl.lit(None).alias(col))

            # Add source tracking if provided
            if source_name:
                expr_list.append(pl.lit(source_name).alias('source'))

            # Select and reorder columns
            normalized = df.select(expr_list)

            # Ensure columns are in correct order
            cols = required.copy()
            if source_name:
                cols.append('source')

            # Add any extra columns that existed
            extra_cols = [c for c in df.columns if c not in cols]
            cols.extend(extra_cols)

            # Keep only available columns
            cols = [c for c in cols if c in normalized.columns]
            normalized = normalized.select(cols)

            logger.info(f"Normalized {len(normalized)} holdings from {source_name or 'portfolio'}")
            return normalized

        except Exception as e:
            logger.error(f"Error normalizing portfolio: {e}")
            self.errors.append(f"Normalization error: {e}")
            return None

    def consolidate(self, portfolio_files: List[str]) -> Tuple[pl.DataFrame, Dict]:
        """Consolidate multiple portfolio files into master portfolio using Polars."""
        if not portfolio_files:
            raise ValueError("No portfolio files provided")

        logger.info(f"Consolidating {len(portfolio_files)} portfolio files...")

        all_portfolios = []
        file_summaries = []

        # Load and validate each portfolio
        for file_path in portfolio_files:
            logger.info(f"\nProcessing: {file_path}")

            df = self.load_portfolio_file(file_path)
            if df is None:
                continue

            if not self.validate_portfolio(df, Path(file_path).name):
                continue

            # Extract source name from filename
            source_name = Path(file_path).stem

            # Normalize
            normalized = self.normalize_portfolio(df, source_name)
            if normalized is None:
                continue

            all_portfolios.append(normalized)

            # Summary for this file
            asset_types = normalized.select(pl.col('asset_type')).unique().to_series().to_list()
            total_value = (normalized.select(pl.col('shares') * pl.col('purchase_price')).sum()).item()

            file_summaries.append({
                'source': source_name,
                'count': len(normalized),
                'asset_types': asset_types,
                'total_value': float(total_value) if total_value else 0.0
            })

        if not all_portfolios:
            raise ValueError("No valid portfolios to consolidate")

        # Concatenate all portfolios using Polars (much faster than pandas)
        self.consolidated = pl.concat(all_portfolios)

        logger.info(f"\n=== CONSOLIDATION SUMMARY ===")
        logger.info(f"Total holdings: {len(self.consolidated)}")
        logger.info(f"Total sources: {len(file_summaries)}")

        # Check for duplicates across consolidated portfolio
        duplicate_symbols = self.consolidated.filter(pl.col('symbol').is_duplicated())
        if len(duplicate_symbols) > 0:
            logger.warning(f"⚠️ Found {len(duplicate_symbols)} duplicate symbols across sources")

            # Group duplicates
            for symbol in duplicate_symbols.select(pl.col('symbol')).unique().to_series().to_list():
                symbol_group = self.consolidated.filter(pl.col('symbol') == symbol)
                sources = symbol_group.select(pl.col('source')).unique().to_series().to_list()
                total_shares = symbol_group.select(pl.col('shares')).sum().item()
                avg_cost = symbol_group.select(pl.col('purchase_price')).mean().item()

                self.duplicates.append({
                    'symbol': symbol,
                    'count': len(symbol_group),
                    'sources': sources,
                    'shares': float(total_shares) if total_shares else 0.0,
                    'average_cost': float(avg_cost) if avg_cost else 0.0
                })

        return self.consolidated, {
            'timestamp': datetime.now().isoformat(),
            'total_holdings': len(self.consolidated),
            'total_sources': len(file_summaries),
            'file_summaries': file_summaries,
            'duplicates_found': len(self.duplicates),
            'duplicate_details': self.duplicates,
            'errors': self.errors if self.errors else None,
            'warnings': self.warnings if self.warnings else None
        }

    def save_master_portfolio(self, output_file: str = 'master_portfolio.csv') -> None:
        """Save consolidated portfolio to CSV using Polars."""
        try:
            self.consolidated.write_csv(output_file)
            logger.info(f"\n✅ Master portfolio saved: {output_file}")
            logger.info(f"   Holdings: {len(self.consolidated)}")

            asset_types = self.consolidated.select(pl.col('asset_type')).unique().to_series().to_list()
            logger.info(f"   Asset types: {', '.join(asset_types)}")

        except Exception as e:
            logger.error(f"Error saving master portfolio: {e}")
            raise

    def save_master_json(self, output_file: str = 'master_portfolio.json', metadata: Dict = None) -> None:
        """Save consolidated portfolio with metadata to JSON."""
        try:
            result = {
                'timestamp': datetime.now().isoformat(),
                'summary': metadata or {},
                'holdings': self.consolidated.to_dicts()
            }

            with open(output_file, 'w') as f:
                json.dump(result, f, indent=2, default=str)

            logger.info(f"✅ Master portfolio metadata saved: {output_file}")

        except Exception as e:
            logger.error(f"Error saving JSON: {e}")
            raise

    def generate_consolidation_report(self, metadata: Dict) -> None:
        """Generate and display consolidation report."""
        logger.info("\n" + "=" * 60)
        logger.info("PORTFOLIO CONSOLIDATION REPORT")
        logger.info("=" * 60)

        logger.info(f"\nSources Consolidated: {metadata['total_sources']}")
        for summary in metadata['file_summaries']:
            logger.info(f"\n  📊 {summary['source']}")
            logger.info(f"     Holdings: {summary['count']}")
            logger.info(f"     Asset types: {', '.join(summary['asset_types'])}")
            logger.info(f"     Total value: ${summary['total_value']:,.2f}")

        logger.info(f"\n{'=' * 60}")
        logger.info(f"MASTER PORTFOLIO SUMMARY")
        logger.info(f"{'=' * 60}")

        logger.info(f"\nTotal Holdings: {metadata['total_holdings']}")

        # Asset type breakdown using Polars groupby
        asset_breakdown = self.consolidated.group_by('asset_type').agg(pl.len().alias('count'))
        logger.info(f"\nAsset Type Breakdown:")
        for row in asset_breakdown.to_dicts():
            logger.info(f"  • {row['asset_type']}: {row['count']}")

        # Source breakdown using Polars groupby
        source_breakdown = self.consolidated.group_by('source').agg(pl.len().alias('count'))
        logger.info(f"\nBreakdown by Source:")
        for row in source_breakdown.to_dicts():
            logger.info(f"  • {row['source']}: {row['count']}")

        # Duplicate warning
        if metadata['duplicates_found'] > 0:
            logger.warning(f"\n⚠️ DUPLICATES FOUND: {metadata['duplicates_found']} symbols appear in multiple sources")
            logger.warning("   This may indicate:")
            logger.warning("   • Same holding tracked in multiple accounts")
            logger.warning("   • Symbol appears with different details")
            logger.warning("   • Data entry error\n")

            logger.warning("   Duplicate Details:")
            for dup in metadata['duplicate_details']:
                logger.warning(f"     {dup['symbol']}:")
                logger.warning(f"       Sources: {', '.join(dup['sources'])}")
                logger.warning(f"       Total shares: {dup['shares']}")
                logger.warning(f"       Average cost: ${dup['average_cost']:.2f}")

            logger.warning("\n   👉 RECOMMENDATION: Review duplicates and decide how to handle:")
            logger.warning("      • Keep all (treat as separate positions)")
            logger.warning("      • Merge (sum shares, average cost)")
            logger.warning("      • Remove duplicates (keep only one)")

        # Warnings
        if metadata.get('warnings'):
            logger.warning(f"\n⚠️ WARNINGS ({len(metadata['warnings'])} total)")
            for warning in metadata['warnings']:
                logger.warning(f"  • {warning}")

        # Errors
        if metadata.get('errors'):
            logger.error(f"\n❌ ERRORS ({len(metadata['errors'])} total)")
            for error in metadata['errors']:
                logger.error(f"  • {error}")

        logger.info(f"\n{'=' * 60}")

    def main(self, portfolio_files: List[str], output_prefix: str = 'master_portfolio'):
        """Main consolidation orchestration."""

        # Phase 9: Check feature availability (FA mode only)
        if _features_available:
            try:
                mode_str = get_deployment_mode()
                mode = DeploymentMode(mode_str)
                fm = FeatureManager(mode)
                fm.require_feature(Feature.MULTI_PORTFOLIO_MANAGEMENT)  # FA-only feature
                logger.info(f"Multi-portfolio management enabled for {mode_str} mode")
            except FeatureNotAvailableError as e:
                logger.error(f"Multi-portfolio management not available: {e}")
                raise

        try:
            # Consolidate
            consolidated_df, metadata = self.consolidate(portfolio_files)

            # Save outputs
            csv_file = f"{output_prefix}.csv"
            json_file = f"{output_prefix}.json"

            self.save_master_portfolio(csv_file)
            self.save_master_json(json_file, metadata)

            # Generate report
            self.generate_consolidation_report(metadata)

            logger.info(f"\n✅ Consolidation complete!")
            logger.info(f"   CSV: {csv_file}")
            logger.info(f"   JSON: {json_file}")

            return consolidated_df, metadata

        except Exception as e:
            logger.error(f"Fatal error during consolidation: {e}")
            raise

if __name__ == '__main__':
    # Phase 9: Check feature availability (FA mode only)
    if _features_available:
        try:
            mode_str = get_deployment_mode()
            mode = DeploymentMode(mode_str)
            fm = FeatureManager(mode)
            fm.require_feature(Feature.MULTI_PORTFOLIO_MANAGEMENT)  # FA-only feature
            logger.info(f"Multi-portfolio management enabled for {mode_str} mode")
        except FeatureNotAvailableError as e:
            logger.error(f"Multi-portfolio management not available: {e}")
            print(f"❌ Multi-portfolio management requires FA Professional mode: {e}")
            sys.exit(1)

    if len(sys.argv) < 2:
        print("Usage: python3 consolidate_portfolios.py <file1.csv> <file2.xlsx> ... [--output master_portfolio]")
        print("\nExample:")
        print("  python3 consolidate_portfolios.py ~/portfolio_ubs.csv ~/portfolio_yahoo.csv")
        sys.exit(1)

    # Parse arguments
    portfolio_files = []
    output_prefix = 'master_portfolio'

    for i, arg in enumerate(sys.argv[1:]):
        if arg == '--output' and i + 1 < len(sys.argv) - 1:
            output_prefix = sys.argv[i + 2]
        elif not arg.startswith('--'):
            portfolio_files.append(arg)

    if not portfolio_files:
        print("Error: No portfolio files provided")
        sys.exit(1)

    consolidator = PortfolioConsolidator()
    consolidator.main(portfolio_files, output_prefix)
