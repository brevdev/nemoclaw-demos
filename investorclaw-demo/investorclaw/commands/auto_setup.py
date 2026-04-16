#!/usr/bin/env python3
"""
Auto-setup script for portfolio analyzer skill.
Runs on first initialization to:
1. Detect PDFs and XLS files in the portfolios directory
2. Extract tables using tabula/camelot
3. Convert XLS to CSV
4. Consolidate multiple files if found
"""

import os
import sys
import json
import subprocess
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import logging
from rendering.progress import bootstrap, phase, update, complete, error as report_error, Phase
from services.extract_pdf import PDFExtractor

# Redirect logging to avoid interfering with progress reporting
logging.basicConfig(level=logging.WARNING, format='[%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

SKILL_DIR = Path(__file__).parent.parent
PORTFOLIO_DIR = SKILL_DIR / "portfolios"
EXAMPLES_DIR = PORTFOLIO_DIR / "examples"
SETUP_MARKER = PORTFOLIO_DIR / ".setup_complete"
ENV_FILE = SKILL_DIR / ".env"
ENV_EXAMPLE = SKILL_DIR / ".env.example"

# API keys required for full functionality
_REQUIRED_KEYS = {
    "FINNHUB_KEY": ("Finnhub (real-time quotes & analyst ratings)", "https://finnhub.io/register"),
    "NEWSAPI_KEY": ("NewsAPI (news correlation)", "https://newsapi.org/register"),
    "MASSIVE_API_KEY": ("Massive (market data, polygon.io-compatible)", "https://polygon.io/dashboard/signup"),
    "ALPHA_VANTAGE_KEY": ("Alpha Vantage (supplemental pricing)", "https://www.alphavantage.co/support/#api-key"),
    "FRED_API_KEY": ("FRED / St. Louis Fed (Treasury & TIPS yields)", "https://fred.stlouisfed.org/docs/api/api_key.html"),
}


def check_api_keys() -> Dict[str, bool]:
    """Check which API keys are configured in .env.

    Returns a dict mapping key name -> True (present) / False (missing).
    Prints guided instructions for any missing key.
    """
    # Load .env if it exists
    env_values: Dict[str, str] = {}
    if ENV_FILE.exists():
        with open(ENV_FILE) as fh:
            for raw in fh:
                line = raw.strip()
                if line and not line.startswith('#') and '=' in line:
                    k, _, v = line.partition('=')
                    env_values[k.strip()] = v.strip()

    results: Dict[str, bool] = {}
    missing = []

    for key, (description, signup_url) in _REQUIRED_KEYS.items():
        value = os.environ.get(key) or env_values.get(key, "")
        present = bool(value)
        results[key] = present
        if not present:
            missing.append((key, description, signup_url))

    if not missing:
        update(f"✅ All {len(_REQUIRED_KEYS)} API keys configured")
        return results

    if not ENV_FILE.exists():
        update(f"⚠️  No .env file found at {ENV_FILE}")
        if ENV_EXAMPLE.exists():
            update(f"   Copy the template: cp {ENV_EXAMPLE} {ENV_FILE}")
        else:
            update(f"   Create {ENV_FILE} and add your API keys")
        update("")

    update(f"⚠️  {len(missing)}/{len(_REQUIRED_KEYS)} API key(s) not configured — some features will be limited:")
    for key, description, signup_url in missing:
        update(f"   {key}  ({description})")
        update(f"     Get a free key: {signup_url}")
    update("")
    update("Add missing keys to skill/.env (gitignored) to enable full functionality.")

    return results


def check_dependencies() -> Dict[str, bool]:
    """Check if required dependencies are available."""
    deps = {
        'pdfplumber': False,
        'tabula': False,
        'camelot': False,
        'pypdf2': False,
        'pdfminer': False,
        'openpyxl': False,
        'polars': False,
    }

    # Check PDF extraction tools (in priority order)
    try:
        import pdfplumber
        deps['pdfplumber'] = True
    except ImportError:
        logger.warning("pdfplumber not installed. Install with: pip install pdfplumber")

    try:
        import tabula
        deps['tabula'] = True
    except ImportError:
        logger.warning("tabula-py not installed. Install with: pip install tabula-py")

    try:
        import camelot
        deps['camelot'] = True
    except ImportError:
        logger.warning("camelot-py not installed (best for complex tables). Install with: pip install camelot-py[cv]")

    try:
        import PyPDF2
        deps['pypdf2'] = True
    except ImportError:
        logger.warning("PyPDF2 not installed. Install with: pip install PyPDF2")

    try:
        import pdfminer
        deps['pdfminer'] = True
    except ImportError:
        logger.warning("pdfminer not installed. Install with: pip install pdfminer.six")

    # Excel and data processing
    try:
        import openpyxl
        deps['openpyxl'] = True
    except ImportError:
        logger.warning("openpyxl not installed. Install with: pip install openpyxl")

    try:
        import polars
        deps['polars'] = True
    except ImportError:
        logger.error("polars not installed. Install with: pip install polars")
        return deps

    return deps


def extract_pdf_tables(pdf_path: Path) -> List[Path]:
    """Extract tables from PDF and save as CSV files using PDFExtractor with fallback strategies."""
    csv_files = []

    try:
        # Use PDFExtractor with multiple strategy fallbacks
        extractor = PDFExtractor(pdf_path, timeout=30)
        result = extractor.extract()

        if result.get('status') == 'success':
            update(f"  ✅ {result['tool']}: Extracted {result['count']} holdings")

            # Save holdings as CSV
            try:
                import csv
                output_file = PORTFOLIO_DIR / f"{pdf_path.stem}_extracted.csv"
                with open(output_file, 'w') as f:
                    writer = csv.DictWriter(f, fieldnames=['symbol', 'shares', 'price', 'asset_type'])
                    writer.writeheader()
                    for holding in result['holdings']:
                        holding['asset_type'] = 'equity'  # Default
                        writer.writerow(holding)
                csv_files.append(output_file)
                logger.info(f"  Saved: {output_file.name}")
            except Exception as e:
                logger.error(f"Error saving CSV for {pdf_path.name}: {e}")

        elif result.get('status') == 'partial':
            update(f"  ⚠️  Text extracted (manual parsing required)")
            logger.warning(f"Partial extraction for {pdf_path.name} - raw text extracted")
        else:
            update(f"  ❌ All extraction strategies failed for {pdf_path.name}")
            logger.warning(f"Could not extract tables from {pdf_path.name}: {result.get('error')}")

    except Exception as e:
        logger.error(f"Error processing PDF {pdf_path.name}: {e}")
        update(f"  ❌ PDF processing error: {str(e)}")

    return csv_files


def convert_xls_to_csv(xls_path: Path) -> List[Path]:
    """Convert XLS/XLSX file to CSV using Polars."""
    logger.info(f"Converting XLS file: {xls_path.name}")
    csv_files = []

    try:
        import polars as pl
    except ImportError:
        logger.warning(f"Skipping XLS {xls_path.name} - polars not installed")
        return csv_files

    try:
        import openpyxl
        wb = openpyxl.load_workbook(xls_path, read_only=True, data_only=True)
        sheet_names = wb.sheetnames
        wb.close()

        for sheet_name in sheet_names:
            try:
                # Read with Polars using sheet name
                df = pl.read_excel(xls_path, sheet_name=sheet_name)

                if df.is_empty():
                    continue

                # Check if this sheet has portfolio data
                cols_lower = [c.lower() for c in df.columns]
                if any(col in cols_lower for col in ['symbol', 'ticker', 'security', 'shares', 'quantity', 'holdings']):
                    output_file = PORTFOLIO_DIR / f"{xls_path.stem}_{sheet_name}.csv"
                    df.write_csv(output_file)
                    csv_files.append(output_file)
                    logger.info(f"  Saved: {output_file.name}")
            except Exception as sheet_error:
                logger.warning(f"Could not process sheet '{sheet_name}': {sheet_error}")

        return csv_files

    except Exception as e:
        logger.error(f"Error converting XLS {xls_path.name}: {e}")
        return csv_files


def discover_and_convert_files() -> Dict[str, List[Path]]:
    """Discover PDFs, XLS files and convert them."""
    results = {
        'csv_files': [],
        'pdf_files': [],
        'xls_files': [],
        'converted_files': [],
    }

    # Find all files in portfolios directory (excluding subdirectories like examples/)
    PORTFOLIO_DIR.mkdir(parents=True, exist_ok=True)
    for file in PORTFOLIO_DIR.glob("*"):
        if file.is_dir():
            # Skip directories (including examples/)
            continue
        if file.name.startswith('.'):
            continue

        if file.suffix.lower() == '.pdf':
            results['pdf_files'].append(file)
            csv_files = extract_pdf_tables(file)
            results['converted_files'].extend(csv_files)

        elif file.suffix.lower() in ['.xls', '.xlsx']:
            results['xls_files'].append(file)
            csv_files = convert_xls_to_csv(file)
            results['converted_files'].extend(csv_files)

        elif file.suffix.lower() == '.csv':
            results['csv_files'].append(file)

    return results


def consolidate_portfolios(csv_files: List[Path]) -> Path:
    """Consolidate multiple CSV files into a master portfolio."""
    if not csv_files:
        return None

    if len(csv_files) == 1:
        return csv_files[0]

    logger.info(f"Consolidating {len(csv_files)} portfolio files...")

    try:
        # Use the consolidate_portfolios script if available
        consolidate_script = Path(__file__).resolve().parent.parent / "services" / "consolidate_portfolios.py"

        if consolidate_script.exists():
            cmd = [
                sys.executable,
                str(consolidate_script),
                '--input', ','.join(str(f) for f in csv_files),
                '--output', str(PORTFOLIO_DIR / "master_portfolio.csv"),
            ]
            result = subprocess.run(cmd, capture_output=True, text=True)

            if result.returncode == 0:
                master_file = PORTFOLIO_DIR / "master_portfolio.csv"
                logger.info(f"Consolidated master portfolio: {master_file.name}")
                return master_file

        return csv_files[0]

    except Exception as e:
        logger.error(f"Error consolidating portfolios: {e}")
        return csv_files[0]


def analyze_bonds_if_present(csv_files: List[Path]) -> Optional[Path]:
    """
    Automatically run bond analysis if bonds are detected in portfolio files.
    Returns path to bond_analysis.json if bonds were found and analyzed.
    """
    if not csv_files:
        return None

    try:
        import polars as pl
        from pathlib import Path

        # Check if any CSV contains bonds
        has_bonds = False
        for csv_file in csv_files:
            try:
                df = pl.read_csv(csv_file)
                asset_types = df.select('asset_type').to_series().unique().to_list()
                if any('bond' in str(t).lower() for t in asset_types if t):
                    has_bonds = True
                    break
            except Exception:
                continue

        if not has_bonds:
            return None

        update("🔍 Bonds detected. Running bond analysis...")

        # Import bond analyzer
        bond_analyzer_script = Path(__file__).parent / "bond_analyzer.py"
        if not bond_analyzer_script.exists():
            logger.warning("bond_analyzer.py not found. Skipping bond analysis.")
            return None

        # Determine input file (preferably master portfolio if available)
        input_file = None
        for csv_file in csv_files:
            if 'master' in csv_file.name.lower():
                input_file = csv_file
                break
        if not input_file:
            input_file = csv_files[0]

        # Output path
        output_path = PORTFOLIO_DIR.parent / 'portfolio_reports' / 'bond_analysis.json'
        output_path.parent.mkdir(parents=True, exist_ok=True)

        # Run bond analyzer
        cmd = [
            sys.executable,
            str(bond_analyzer_script),
            str(input_file),
            str(output_path),
        ]

        update(f"  Analyzing bonds from {input_file.name}...")
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60)

        if result.returncode == 0:
            update("  ✅ Bond analysis complete")
            logger.info(f"Bond analysis saved to {output_path}")
            return output_path
        else:
            logger.warning(f"Bond analysis failed: {result.stderr}")
            return None

    except Exception as e:
        logger.warning(f"Error running bond analysis: {e}")
        return None


def generate_setup_summary(results: Dict) -> str:
    """Generate a summary of what was discovered and converted."""
    summary = []
    summary.append("\n📊 **Portfolio Auto-Setup Complete**\n")

    if results['pdf_files']:
        summary.append(f"📄 PDFs found: {len(results['pdf_files'])}")
        for pdf in results['pdf_files']:
            summary.append(f"  - {pdf.name}")

    if results['xls_files']:
        summary.append(f"\n📊 Excel files found: {len(results['xls_files'])}")
        for xls in results['xls_files']:
            summary.append(f"  - {xls.name}")

    if results['converted_files']:
        summary.append(f"\n✅ Converted files: {len(results['converted_files'])}")
        for csv in results['converted_files']:
            summary.append(f"  - {csv.name}")

    if results['csv_files']:
        summary.append(f"\n📋 CSV portfolios available: {len(results['csv_files'])}")
        for csv in results['csv_files']:
            summary.append(f"  - {csv.name}")

    if results['converted_files'] or results['csv_files']:
        summary.append("\n✨ Ready for analysis. Use `/InvestorClaw` to start.")
    else:
        summary.append("\n⚠️  No portfolio files found. Add CSV, XLS, or PDF files to your portfolios directory.")
        summary.append("📖 See the examples/ folder in your skill directory for format reference.")

    return "\n".join(summary)


def main():
    """Main setup function."""
    try:
        # Bootstrap: immediate acknowledgement
        bootstrap("portfolio_skill_setup")

        # Check if already setup
        if SETUP_MARKER.exists():
            phase(Phase.COMPLETE, "Setup already complete. Skipping.")
            return 0

        phase(Phase.INIT, "Initializing portfolio analyzer...",
              {"portfolio_dir": str(PORTFOLIO_DIR)})

        # Check API keys
        update("Checking API key configuration...")
        check_api_keys()

        # Check dependencies
        update("Checking dependencies...")
        deps = check_dependencies()

        # Report available PDF extraction tools
        pdf_tools = [tool for tool in ['pdfplumber', 'tabula', 'camelot', 'pypdf2', 'pdfminer'] if deps.get(tool)]
        if pdf_tools:
            update(f"✅ PDF extraction tools available: {', '.join(pdf_tools)}")
        else:
            update("⚠️  No PDF extraction tools found. For best results: pip install pdfplumber")

        if not deps.get('polars') or not deps.get('openpyxl'):
            update("⚠️  Optional: pip install polars tabula-py camelot-py[cv] pdfplumber openpyxl (for Excel/PDF support)")

        # Discover and convert files
        phase(Phase.DISCOVER, "Discovering portfolio files...")
        results = discover_and_convert_files()

        update(f"Found {len(results['pdf_files'])} PDFs, {len(results['xls_files'])} Excel files, {len(results['csv_files'])} CSVs")

        # Extract from PDFs if tabula available
        if results['pdf_files']:
            phase(Phase.EXTRACT_PDF, f"Extracting tables from {len(results['pdf_files'])} PDF files...")
            for pdf in results['pdf_files']:
                update(f"Processing {pdf.name}...")

        # Convert Excel files
        if results['xls_files']:
            phase(Phase.CONVERT_XLS, f"Converting {len(results['xls_files'])} Excel files to CSV...")
            for xls in results['xls_files']:
                update(f"Converting {xls.name}...")

        # Consolidate if multiple files
        all_csv = results['csv_files'] + results['converted_files']
        if len(all_csv) > 1:
            phase(Phase.CONSOLIDATE, f"Consolidating {len(all_csv)} portfolio files...")
            update("Merging holdings, detecting duplicates...")
            master = consolidate_portfolios(all_csv)
            if master:
                results['master_portfolio'] = str(master)
                update(f"Created master_portfolio.csv")

        # Analyze bonds if present
        phase(Phase.ANALYZE, "Analyzing bonds if present...")
        bond_analysis = analyze_bonds_if_present(all_csv if all_csv else results['csv_files'])
        if bond_analysis:
            results['bond_analysis'] = str(bond_analysis)

        # Generate summary
        summary = generate_setup_summary(results)
        update("Setup summary:")
        for line in summary.split('\n'):
            if line.strip():
                update(line)

        # Mark setup as complete (create parent dir if fresh install)
        SETUP_MARKER.parent.mkdir(parents=True, exist_ok=True)
        SETUP_MARKER.touch()

        # Save results to manifest
        import time
        manifest_path = PORTFOLIO_DIR / "setup_results.json"
        results_to_save = {
            'timestamp': time.strftime('%Y-%m-%d %H:%M:%S', time.localtime()),
            'pdf_files': [str(f) for f in results['pdf_files']],
            'xls_files': [str(f) for f in results['xls_files']],
            'csv_files': [str(f) for f in results['csv_files']],
            'converted_files': [str(f) for f in results['converted_files']],
        }

        with open(manifest_path, 'w') as f:
            json.dump(results_to_save, f, indent=2)

        phase(Phase.COMPLETE, "Portfolio analyzer setup complete", {
            "pdfs_found": len(results['pdf_files']),
            "excel_files_found": len(results['xls_files']),
            "csv_files": len(results['csv_files']),
            "converted_files": len(results['converted_files']),
            "ready_for_analysis": "Yes" if all_csv else "No"
        })

        return 0

    except Exception as e:
        report_error(f"Setup failed: {str(e)}", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
