#!/usr/bin/env python3
"""
Advanced PDF extraction with broker detection and multiple strategy fallbacks.
Identifies broker platform, then uses optimized extraction strategies.
"""

import sys
import json
from pathlib import Path
from typing import List, Dict, Optional, Tuple
import logging

# Ensure scripts directory is in path for imports
script_dir = Path(__file__).parent
if str(script_dir) not in sys.path:
    sys.path.insert(0, str(script_dir))

from rendering.progress import phase, update, error as report_error, Phase
from providers.broker_detector import BrokerDetector

logging.basicConfig(level=logging.WARNING)
logger = logging.getLogger(__name__)


class PDFExtractor:
    """Extract portfolio data from PDFs and text files with multiple strategies."""

    def __init__(self, pdf_path: Path, timeout: int = 30):
        self.pdf_path = pdf_path
        self.timeout = timeout
        self.strategies = []
        self.is_text_file = str(pdf_path).endswith('.txt')
        self.detected_broker = None
        self.broker_confidence = 0

        # Run broker detection FIRST
        if not self.is_text_file:
            self._detect_broker()

        if not self.is_text_file:
            self._detect_available_tools()

    def _detect_broker(self):
        """Detect broker platform from PDF/text content."""
        try:
            detector = BrokerDetector(self.pdf_path)
            broker, confidence, details = detector.detect()
            self.detected_broker = broker
            self.broker_confidence = confidence

            if broker:
                update(f"Detected broker: {broker} ({confidence}% confidence)")
                logger.info(f"Broker detection: {broker} at {confidence}%")
                logger.info(f"Details: {details}")
            else:
                update("No broker detected - using generic extraction")
                logger.warning("Could not detect broker platform")

        except Exception as e:
            logger.warning(f"Broker detection failed: {e}")
            update("Broker detection failed - using generic extraction")

    def _detect_available_tools(self):
        """Detect which PDF tools are available."""
        tools = {}

        try:
            import pdfplumber
            tools['pdfplumber'] = {'priority': 1, 'speed': 'fast', 'accuracy': 'high'}
        except ImportError:
            pass

        try:
            import tabula
            tools['tabula'] = {'priority': 2, 'speed': 'medium', 'accuracy': 'medium'}
        except ImportError:
            pass

        try:
            import camelot
            tools['camelot'] = {'priority': 3, 'speed': 'slow', 'accuracy': 'high'}
        except ImportError:
            pass

        try:
            import PyPDF2
            tools['pypdf2'] = {'priority': 4, 'speed': 'fast', 'accuracy': 'low'}
        except ImportError:
            pass

        try:
            import pdfminer
            tools['pdfminer'] = {'priority': 5, 'speed': 'medium', 'accuracy': 'medium'}
        except ImportError:
            pass

        # Sort by priority
        self.strategies = sorted(
            [(tool, info) for tool, info in tools.items()],
            key=lambda x: x[1]['priority']
        )

    def extract_with_pdfplumber(self) -> Optional[List[Dict]]:
        """Extract using pdfplumber with broker-optimized strategies."""
        import pdfplumber
        holdings = []

        try:
            with pdfplumber.open(self.pdf_path) as pdf:
                # Extract text from all pages upfront (handle errors gracefully)
                full_text = ''
                for page_num, page in enumerate(pdf.pages, 1):
                    try:
                        text = page.extract_text()
                        if text:
                            full_text += '\n' + text
                    except Exception as page_error:
                        logger.debug(f"Could not extract text from page {page_num}: {page_error}")
                        continue

                # Get broker-optimized extraction strategy order
                from providers.broker_detector import BrokerDetector
                detector = BrokerDetector(self.pdf_path)
                _, _, details = detector.detect()
                strategies = details.get('recommended_strategies', []) if details.get('recommended_strategies') else None

                if not strategies:
                    strategies = ['account_sections', 'schwab_format', 'ubs_bonds', 'text_parsing', 'table_parsing']

                update(f"Using extraction strategies for {self.detected_broker or 'unknown broker'}: {' → '.join(strategies)}")

                # Execute strategies in priority order
                for strategy in strategies:
                    if strategy == 'account_sections':
                        account_holdings = self._extract_by_account_sections(full_text)
                        if account_holdings:
                            holdings.extend(account_holdings)
                            unique_accounts = len(set(h.get('account_type') for h in account_holdings if h.get('account_type')))
                            update(f"Found {len(account_holdings)} holdings across {unique_accounts} accounts")
                            return holdings

                    elif strategy == 'schwab_format':
                        try:
                            schwab_holdings = self._extract_schwab_format(pdf)
                            if schwab_holdings:
                                update(f"Found {len(schwab_holdings)} holdings in Schwab format")
                                return schwab_holdings
                        except Exception as schwab_error:
                            logger.debug(f"Schwab format extraction failed: {schwab_error}")

                    elif strategy == 'ubs_bonds':
                        bond_holdings = self._extract_ubs_bonds(full_text)
                        if bond_holdings:
                            holdings.extend(bond_holdings)
                            update(f"Found {len(bond_holdings)} bond holdings")

                    elif strategy == 'text_parsing':
                        # Try to extract equities from text (for UBS text-based format)
                        text_equities = self._parse_text_for_holdings(full_text)
                        if text_equities:
                            holdings.extend(text_equities)
                            update(f"Found {len(text_equities)} equity holdings from text")

                    elif strategy == 'table_parsing':
                        # Fallback: extract equity holdings from tables
                        try:
                            for page_num, page in enumerate(pdf.pages, 1):
                                update(f"pdfplumber: Extracting page {page_num}...")

                                # Try to extract tables
                                tables = page.extract_tables()
                                if tables:
                                    for table in tables:
                                        holdings.extend(self._parse_table(table))
                        except Exception as table_error:
                            logger.warning(f"Table extraction failed: {table_error}")

            return holdings if holdings else None

        except Exception as e:
            logger.warning(f"pdfplumber failed: {e}")
            return None

    def _extract_schwab_format(self, pdf) -> Optional[List[Dict]]:
        """Extract Schwab-style PDF with †† markers for holdings."""
        import re

        holdings = []
        all_text = '\n'.join(page.extract_text() for page in pdf.pages)
        lines = all_text.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Look for Schwab ticker marker: SYMBOL††
            if '††' in line:
                # Extract symbol (everything before ††)
                symbol_match = re.match(r'^([A-Z]{1,6})\s*††', line)
                if not symbol_match:
                    i += 1
                    continue

                symbol = symbol_match.group(1)

                # Filter out non-tickers
                if any(word in symbol for word in ['TOTAL', 'FUND', 'ETF', 'CLOSED']):
                    i += 1
                    continue

                holding = {'symbol': symbol}

                # Next line should have: Quantity Price Cost Value
                if i + 1 < len(lines):
                    next_line = lines[i + 1].strip()

                    # Extract quantity (first number in next line)
                    qty_match = re.match(r'^([\d,]+(?:\.\d+)?)\s+', next_line)
                    if qty_match:
                        try:
                            holding['shares'] = float(qty_match.group(1).replace(',', ''))
                        except (ValueError, TypeError):
                            pass

                    # Extract price (dollar amount in next line, often after spaces/dashes)
                    price_matches = re.findall(r'\$[\d,]+\.?\d*', next_line)
                    if price_matches:
                        try:
                            # First dollar amount is usually price per share
                            price_str = price_matches[0].replace('$', '').replace(',', '')
                            holding['price'] = float(price_str)
                        except (ValueError, TypeError):
                            pass

                holdings.append(holding)

            i += 1

        return holdings if holdings else None

    def extract_from_schwab_text(self) -> Optional[List[Dict]]:
        """Extract Schwab Summary.txt format with †† markers."""
        import re

        try:
            with open(self.pdf_path, 'r', encoding='utf-8', errors='ignore') as f:
                text = f.read()
        except Exception as e:
            logger.warning(f"Could not read text file: {e}")
            return None

        holdings = []
        lines = text.split('\n')

        i = 0
        while i < len(lines):
            line = lines[i].strip()

            # Look for symbol with †† marker
            # Format: SYMBOL†† (sometimes with a number like AAPL††2)
            if line and '††' in line and len(line) < 50:  # Symbol line is usually short
                # Extract symbol (everything before ††)
                symbol_match = re.match(r'^([A-Z]{1,6})\s*††', line)
                if not symbol_match:
                    i += 1
                    continue

                symbol = symbol_match.group(1)

                # Skip known non-holdings markers/headers
                if symbol in ['TOTAL', 'CASH', 'EQUITIES', 'BONDS', 'OPTIONS', 'FUND', 'ETF', 'FIXED', 'MUTUAL']:
                    i += 1
                    continue

                holding = {'symbol': symbol, 'asset_type': 'equity'}

                # The Schwab Summary.txt format is:
                # Line i:     SYMBOL††
                # Line i+1:   Company Name
                # Line i+2:   Quantity
                # Line i+3:   <quantity value>
                # Line i+4:   Price
                # Line i+5:   <price value>
                # Line i+6:   Price Change
                # Line i+7:   <value>
                # Line i+8:   Market Value
                # Line i+9:   <market value>
                # ...
                # Line i+12:  Gain Loss
                # Line i+13:  <gain/loss value>

                # Extract quantity (usually at i+3)
                if i + 3 < len(lines):
                    try:
                        qty_str = lines[i + 3].strip()
                        if qty_str and qty_str != '--':
                            holding['shares'] = float(qty_str.replace(',', ''))
                    except (ValueError, TypeError):
                        pass

                # Extract price (usually at i+5)
                if i + 5 < len(lines):
                    try:
                        price_str = lines[i + 5].strip()
                        if price_str and price_str != '--':
                            price_val = price_str.replace('$', '').replace(',', '')
                            if price_val and price_val != '--':
                                holding['price'] = float(price_val)
                    except (ValueError, TypeError):
                        pass

                # Extract market value (usually at i+9)
                if i + 9 < len(lines):
                    try:
                        market_str = lines[i + 9].strip()
                        if market_str:
                            market_val = market_str.replace('$', '').replace(',', '')
                            if market_val and market_val != '--':
                                holding['market_value'] = float(market_val)
                    except (ValueError, TypeError):
                        pass

                # Extract gain/loss (usually at i+13)
                if i + 13 < len(lines):
                    try:
                        gain_str = lines[i + 13].strip()
                        if gain_str and gain_str not in ['--', 'N/A']:
                            gain_val = gain_str.replace('$', '').replace(',', '').replace('+', '')
                            if gain_val:
                                holding['gain_loss'] = float(gain_val)
                    except (ValueError, TypeError):
                        pass

                # Only add if we have symbol and at least some data (shares, price, or market_value)
                if ('shares' in holding or 'price' in holding or 'market_value' in holding):
                    holdings.append(holding)

            i += 1

        return holdings if holdings else None

    def _extract_ubs_bonds(self, text: str) -> Optional[List[Dict]]:
        """Extract UBS Fixed Income/Municipal Bonds section from PDF text."""
        import re

        if not text:
            return None

        # Look for the Fixed Income section header
        if 'coupon' not in text.lower() or 'municipal' not in text.lower():
            return None

        bonds = []
        seen_cusips = set()  # Track to avoid duplicates
        lines = text.split('\n')

        # Find the start of the Fixed Income section
        section_start = None
        for i, line in enumerate(lines):
            if 'coupon' in line.lower() and 'municipal' in line.lower():
                section_start = i
                break

        if section_start is None:
            return None

        # Parse bond entries - CUSIP is the unique identifier
        # Look for CUSIP (9-character code) which is the reliable identifier
        for i, line in enumerate(lines[section_start:], section_start):
            # Look for CUSIP pattern - 9 alphanumeric characters
            cusip_match = re.search(r'\b([A-Z0-9]{9})\b', line)

            if not cusip_match:
                continue

            cusip = cusip_match.group(1)

            # Skip if we've already processed this CUSIP (avoid duplicates)
            if cusip in seen_cusips:
                continue

            seen_cusips.add(cusip)

            bond = {
                'asset_type': 'municipal_bond',
                'cusip': cusip
            }

            # Extract bond name from the line containing CUSIP or previous lines
            # Look backward for a descriptive name (don't create fake symbols)
            bond_name = None
            for j in range(i, max(section_start, i - 3), -1):
                test_line = lines[j].strip()
                # Look for bond name pattern (text that's likely a proper name)
                if len(test_line) > 5 and len(test_line) < 100:
                    # Keep the original line as bond name (don't strip to all caps)
                    if any(c.isalpha() for c in test_line):
                        bond_name = test_line[:80].strip()
                        # Filter out technical terms that aren't bond names
                        if bond_name and bond_name.upper() not in ['PAR', 'CUSIP', 'RATE', 'PRICE', 'MATURITY']:
                            bond['name'] = bond_name
                            break

            # Extract Market Value - look for dollar amounts in surrounding lines
            for j in range(i, min(i + 8, len(lines))):
                test_line = lines[j]
                # Look for dollar amounts
                amounts = re.findall(r'\$[\d,]+\.\d{2}', test_line)
                if amounts:
                    # Take the largest dollar amount (likely market value)
                    try:
                        market_vals = [float(amt.replace('$', '').replace(',', '')) for amt in amounts]
                        bond['market_value'] = max(market_vals)
                        break
                    except (ValueError, TypeError):
                        pass

            # Extract Coupon Rate - look for patterns like "5.000%" or "5%"
            for j in range(i, min(i + 8, len(lines))):
                test_line = lines[j]
                coupon_match = re.search(r'(\d\.?\d+)\s*%', test_line)
                if coupon_match:
                    try:
                        rate_str = coupon_match.group(1)
                        rate = float(rate_str)
                        # Sanity check - coupon rates are typically 0.5% to 10%
                        if 0.1 < rate < 20:
                            bond['coupon_rate'] = rate
                            break
                    except (ValueError, TypeError):
                        pass

            # Extract Maturity Date - look for date patterns like 10/01/32 (DD/MM/YY format)
            for j in range(i, min(i + 8, len(lines))):
                test_line = lines[j]
                maturity_match = re.search(r'(\d{1,2}/\d{1,2}/\d{2}(?:\d{2})?)', test_line)
                if maturity_match:
                    date_str = maturity_match.group(1)
                    # Normalize date from DD/MM/YY or DD/MM/YYYY to YYYY-MM-DD
                    normalized_date = self._normalize_maturity_date(date_str)
                    if normalized_date:
                        bond['maturity_date'] = normalized_date
                    break

            # Extract Par Value - look for "Par" label followed by amount
            for j in range(i, min(i + 8, len(lines))):
                test_line = lines[j]
                if 'par' in test_line.lower():
                    par_match = re.search(r'\$?([\d,]+(?:\.\d+)?)', test_line)
                    if par_match:
                        try:
                            par = float(par_match.group(1).replace(',', ''))
                            # Par values are typically $10k-$100k
                            if 1000 < par < 1000000:
                                bond['par_value'] = par
                                break
                        except (ValueError, TypeError):
                            pass

            # Only add if we have CUSIP + market_value or par_value
            # Note: Municipal bonds use CUSIP as unique identifier, not symbol
            if 'cusip' in bond and ('market_value' in bond or 'par_value' in bond):
                bonds.append(bond)

        return bonds if bonds else None

    def _extract_by_account_sections(self, text: str) -> Optional[List[Dict]]:
        """Extract holdings grouped by account type (ROTH, SEP, IRA, etc.)."""
        import re

        if not text:
            return None

        holdings = []
        lines = text.split('\n')

        # Account type patterns (case-insensitive)
        account_patterns = {
            'ROTH': r'\b(roth\s+(?:ira|account)?)\b',
            'SEP': r'\b(sep\s+(?:ira|account)?)\b',
            'IRA': r'\b((?:traditional\s+)?ira\s+(?:global\s+stock|account)?)\b',
            'TAXABLE': r'\b(taxable|brokerage|margin)\b'
        }

        current_account = None
        current_account_name = None

        for i, line in enumerate(lines):
            line_lower = line.lower()

            # Detect account headers
            for account_type, pattern in account_patterns.items():
                if re.search(pattern, line_lower):
                    current_account = account_type
                    # Extract full account name if present
                    match = re.search(pattern, line_lower, re.IGNORECASE)
                    if match:
                        current_account_name = match.group(1).strip()
                    logger.info(f"Found account section: {current_account} - {current_account_name}")
                    break

            # Skip if no account detected yet
            if not current_account:
                continue

            # Skip header/section lines
            if any(word in line_lower for word in ['symbol', 'quantity', 'price', 'value', 'total', '---']):
                continue

            # Try to extract holdings from this line
            # Look for symbol followed by quantity and price
            symbol_match = re.search(r'\b([A-Z]{1,5})\b', line)
            if not symbol_match:
                continue

            symbol = symbol_match.group(1)

            # Skip section headers
            if any(word in symbol for word in ['TOTAL', 'ACCOUNT', 'ROTH', 'SEP', 'IRA']):
                continue

            holding = {
                'symbol': symbol,
                'account_type': current_account,
                'account_name': current_account_name
            }

            # Extract numbers (quantity, price, value)
            numbers = re.findall(r'[\d,]+\.?\d*', line)
            if len(numbers) >= 2:
                try:
                    quantity = float(numbers[0].replace(',', ''))
                    if 0 < quantity < 1000000:  # Sanity check
                        holding['shares'] = quantity
                        if len(numbers) >= 2:
                            price = float(numbers[1].replace(',', ''))
                            if price > 0:
                                holding['price'] = price
                except (ValueError, TypeError):
                    pass

            if 'shares' in holding:
                holdings.append(holding)

        return holdings if holdings else None

    def _normalize_maturity_date(self, date_str: str) -> Optional[str]:
        """
        Normalize maturity date to YYYY-MM-DD format.
        Handles: DD/MM/YY, DD/MM/YYYY, MM/DD/YYYY, MM/DD/YY formats.
        UBS exports typically use DD/MM/YY format.
        """
        from datetime import datetime

        if not date_str:
            return None

        # Try common formats
        formats = [
            '%d/%m/%y',     # DD/MM/YY (UBS format - try first)
            '%d/%m/%Y',     # DD/MM/YYYY
            '%m/%d/%y',     # MM/DD/YY
            '%m/%d/%Y',     # MM/DD/YYYY
            '%Y-%m-%d',     # YYYY-MM-DD (already normalized)
        ]

        for fmt in formats:
            try:
                dt = datetime.strptime(date_str.strip(), fmt)
                # Handle YY format - assume 20XX for 00-50, 19XX for 51-99
                if dt.year < 100:
                    dt = dt.replace(year=2000 + dt.year if dt.year <= 50 else 1900 + dt.year)
                return dt.strftime('%Y-%m-%d')
            except ValueError:
                continue

        logger.debug(f"Could not parse maturity date: {date_str}")
        return None

    def extract_with_tabula(self) -> Optional[List[Dict]]:
        """Extract using tabula-py (good for simple layouts)."""
        try:
            import tabula
            import polars as pl

            update("tabula: Reading PDF with timeout...")
            dfs = tabula.read_pdf(
                str(self.pdf_path),
                pages='all',
                multiple_tables=True,
                timeout=self.timeout
            )

            holdings = []
            for df_pandas in dfs:
                if not df_pandas.empty:
                    df = pl.from_pandas(df_pandas)
                    holdings.extend(self._parse_dataframe(df))

            return holdings if holdings else None

        except Exception as e:
            logger.warning(f"tabula failed: {e}")
            return None

    def extract_with_camelot(self) -> Optional[List[Dict]]:
        """Extract using camelot (best for complex tables)."""
        try:
            import camelot
            import polars as pl

            update("camelot: Analyzing table structures...")
            tables = camelot.read_pdf(str(self.pdf_path), pages='all')

            holdings = []
            for table in tables:
                df_pandas = table.df
                if not df_pandas.empty:
                    df = pl.from_pandas(df_pandas)
                    holdings.extend(self._parse_dataframe(df))

            return holdings if holdings else None

        except Exception as e:
            logger.warning(f"camelot failed: {e}")
            return None

    def extract_text_only(self) -> Optional[str]:
        """Fallback: Extract raw text preserving layout (for UBS-style PDFs)."""
        try:
            import pdfplumber

            # Use pdfplumber's layout-aware text extraction instead of pdfminer
            # This preserves the line-by-line structure better
            update("Extracting text with layout preservation...")
            all_text = []

            with pdfplumber.open(str(self.pdf_path)) as pdf:
                for page in pdf.pages:
                    all_text.append(page.extract_text())

            text = '\n'.join(all_text)
            return text if text else None

        except Exception as e:
            logger.warning(f"Text extraction failed: {e}")
            return None

    def _parse_text_for_holdings(self, text: str) -> Optional[List[Dict]]:
        """Parse raw text to extract holdings when table extraction fails (UBS format)."""
        import re

        if not text:
            return None

        holdings = []

        # UBS format: [Company Name] [SYMBOL] [Time] [Quantity] [Price] [Cost] [Value]
        # Example: "AIA GROUP LTD SPON ADR AAGIY 20 hours ago 149.000 $42.79 $4,908.05 $6,375.71"

        lines = text.split('\n')

        for line in lines:
            line = line.strip()

            if not line or len(line) < 10:
                continue

            # Skip header rows and section headers
            if any(word in line.lower() for word in ['symbol', 'refresh', 'quantity', 'price', 'value', 'total cost', 'equity', 'fund', 'closed', 'common stock', '---', 'http']):
                continue

            # Look for a 1-5 uppercase letter symbol followed by "ago"
            symbol_match = re.search(r'\b([A-Z]{1,5})\s+\d+\s+hours?\s+ago\b', line)

            if not symbol_match:
                continue

            symbol = symbol_match.group(1)

            # Filter out non-tickers
            if any(word in symbol for word in ['TOTAL', 'CASH', 'SUMMARY', 'EQUITY']):
                continue

            holding = {'symbol': symbol}

            # Find the position after "ago" and extract numbers
            ago_pos = line.find(' ago ')
            if ago_pos > 0:
                remainder = line[ago_pos + 5:].strip()
                tokens = remainder.split()

                if tokens:
                    # First token should be quantity (number with decimals)
                    try:
                        qty = float(tokens[0].replace(',', ''))
                        if 0 < qty < 1000000:  # Sanity check
                            holding['shares'] = qty
                    except (ValueError, TypeError):
                        pass

                    # Find dollar amounts in remainder
                    dollar_amounts = re.findall(r'\$[\d,]+\.?\d*', remainder)
                    if dollar_amounts:
                        try:
                            # First dollar amount is usually the unit price
                            price_str = dollar_amounts[0].replace('$', '').replace(',', '')
                            holding['price'] = float(price_str)
                        except (ValueError, TypeError):
                            pass

            holdings.append(holding)

        return holdings if holdings else None

    def _parse_table(self, table: List[List[str]]) -> List[Dict]:
        """Parse table and extract holdings from complex brokerage formats."""
        import re

        holdings = []

        if not table or len(table) < 2:
            return holdings

        # Try to identify header row - scan first few rows to find it
        header = None
        header_row_idx = 0
        symbol_col = None

        for idx, potential_header in enumerate(table[:min(3, len(table))]):
            header_lower = [str(h).lower() for h in potential_header]

            # Look for portfolio columns
            test_symbol_col = self._find_column(header_lower, ['symbol', 'ticker', 'cusip', 'security'])
            if test_symbol_col is not None:
                header = potential_header
                header_row_idx = idx
                symbol_col = test_symbol_col
                break

        if symbol_col is None:
            return holdings

        # Look for other important columns based on the header
        header_lower = [str(h).lower() for h in header]
        shares_col = self._find_column(header_lower, ['shares', 'quantity', 'qty', 'units'])
        price_col = self._find_column(header_lower, ['price', 'market value', 'value', 'mkt'])

        # Extract rows (skip all rows up to and including the header)
        for row_idx, row in enumerate(table[header_row_idx + 1:]):
            if not row or len(row) <= symbol_col:
                continue

            cell_content = str(row[symbol_col]).strip()
            if not cell_content or cell_content == 'None' or cell_content.startswith('Total'):
                continue

            # Parse multi-line cell content (Yahoo Finance format)
            # Example: "AAPL\nApple Inc.\n+$256.62\n1.77% $11,765.56 $46,269.86\n+0.56%"
            lines = cell_content.split('\n')

            # Try to extract symbol from first line
            symbol = lines[0].strip() if lines else None
            if not symbol or symbol.lower() == 'none':
                continue

            # Extract just the ticker symbol (before any space or special char)
            symbol_match = re.match(r'^([A-Z]{1,5})', symbol)
            if symbol_match:
                symbol = symbol_match.group(1)
            else:
                continue

            # Filter by symbol length (most real tickers are 1-5 characters)
            if len(symbol) > 5 or len(symbol) < 1:
                continue

            # Filter out obvious non-ticker symbols (bonds, descriptions, etc)
            if any(word in symbol.lower() for word in ['total', 'cash', 'summary', 'balance', 'deposit', 'spread', 'sweep']):
                continue

            holding = {'symbol': symbol}

            # Try to extract dollar values from multi-line content
            all_content = cell_content.replace('\n', ' ')

            # Extract market value (usually largest dollar amount)
            dollar_amounts = re.findall(r'\$[\d,]+\.?\d*', all_content)
            if dollar_amounts:
                # Last dollar amount is often market value
                try:
                    holding['price'] = float(dollar_amounts[-1].replace('$', '').replace(',', ''))
                except (ValueError, TypeError):
                    pass

            # Extract shares/quantity if available in symbol column
            if shares_col is not None and len(row) > shares_col:
                shares_content = str(row[shares_col]).strip()
                if shares_content and shares_content != 'None' and '%' not in shares_content:
                    try:
                        holding['shares'] = float(shares_content.replace(',', ''))
                    except (ValueError, TypeError):
                        pass

            # Try to find percentage (exposure) in the content
            percentages = re.findall(r'([\d.]+)%', all_content)
            if percentages:
                # First percentage is usually exposure/allocation %
                try:
                    holding['exposure'] = float(percentages[0])
                except (ValueError, TypeError):
                    pass

            # Also check other columns for additional data
            for col_idx in range(len(row)):
                if col_idx == symbol_col:
                    continue
                col_content = str(row[col_idx]).strip() if col_idx < len(row) else ''

                if col_content and col_content != 'None' and col_content != '':
                    # Look for dollar amounts in other columns
                    if '$' in col_content:
                        amounts = re.findall(r'\$[\d,]+\.?\d*', col_content)
                        if amounts and 'price' not in holding:
                            try:
                                holding['price'] = float(amounts[-1].replace('$', '').replace(',', ''))
                            except (ValueError, TypeError):
                                pass

                    # Look for percentages in other columns
                    if '%' in col_content and 'exposure' not in holding:
                        pcts = re.findall(r'([\d.]+)%', col_content)
                        if pcts:
                            try:
                                holding['exposure'] = float(pcts[0])
                            except (ValueError, TypeError):
                                pass

            holdings.append(holding)

        return holdings

    def _parse_dataframe(self, df) -> List[Dict]:
        """Parse Polars DataFrame and extract holdings."""
        import polars as pl

        holdings = []
        cols_lower = [str(c).lower() for c in df.columns]

        symbol_col = self._find_column(cols_lower, ['symbol', 'ticker', 'cusip', 'security'])
        if symbol_col is None:
            return holdings

        symbol_col_name = df.columns[symbol_col]

        for row in df.iter_rows(named=True):
            symbol = str(row[symbol_col_name]).strip() if symbol_col_name in row else None

            if not symbol or symbol.startswith('Total') or symbol.lower() == 'nan':
                continue

            holding = {'symbol': symbol}

            # Try to find shares column
            for col_name in df.columns:
                col_lower = str(col_name).lower()
                if any(x in col_lower for x in ['shares', 'quantity', 'qty']):
                    try:
                        val = row.get(col_name)
                        if val and str(val).lower() != 'nan':
                            holding['shares'] = float(str(val).replace(',', ''))
                    except (ValueError, TypeError):
                        pass

            # Try to find price/value column
            for col_name in df.columns:
                col_lower = str(col_name).lower()
                if any(x in col_lower for x in ['price', 'value', 'market']):
                    try:
                        val = row.get(col_name)
                        if val and str(val).lower() != 'nan':
                            holding['price'] = float(str(val).replace('$', '').replace(',', ''))
                    except (ValueError, TypeError):
                        pass

            holdings.append(holding)

        return holdings

    def _find_column(self, headers: List[str], keywords: List[str]) -> Optional[int]:
        """Find column index by keywords."""
        for i, header in enumerate(headers):
            for keyword in keywords:
                if keyword in header:
                    return i
        return None

    def _check_for_truncation(self, result: Dict) -> Dict:
        """Check if PDF content appears truncated (Schwab, etc)."""
        if result.get('status') != 'success':
            return result

        holdings = result.get('holdings', [])

        # Check if results look suspiciously incomplete
        # Schwab shows "Showing X of Y" when truncated
        if len(holdings) < 50 and len(holdings) > 10:
            # Could be truncated - add warning
            result['warning'] = (
                'Note: This PDF export may be truncated. '
                'Consider using CSV export from your broker for complete data.'
            )

        return result

    def extract(self) -> Dict:
        """Extract using best available strategy."""
        # Handle text files (e.g., Schwab Summary.txt)
        if self.is_text_file:
            update("Detected text file format")
            result = self.extract_from_schwab_text()
            if result:
                return {
                    'tool': 'schwab_text_extraction',
                    'status': 'success',
                    'holdings': result,
                    'count': len(result)
                }
            else:
                return {
                    'tool': 'schwab_text_extraction',
                    'status': 'failed',
                    'error': 'Could not parse text file'
                }

        update(f"Available extraction tools: {', '.join(s[0] for s in self.strategies)}")

        for tool, info in self.strategies:
            update(f"Trying {tool} ({info['speed']}, {info['accuracy']} accuracy)...")

            if tool == 'pdfplumber':
                result = self.extract_with_pdfplumber()
                if result:
                    res = {
                        'tool': tool,
                        'status': 'success',
                        'holdings': result,
                        'count': len(result)
                    }
                    return self._check_for_truncation(res)

            elif tool == 'tabula':
                result = self.extract_with_tabula()
                if result:
                    return {
                        'tool': tool,
                        'status': 'success',
                        'holdings': result,
                        'count': len(result)
                    }

            elif tool == 'camelot':
                result = self.extract_with_camelot()
                if result:
                    return {
                        'tool': tool,
                        'status': 'success',
                        'holdings': result,
                        'count': len(result)
                    }

        # Fallback: extract raw text and try to parse it
        text = self.extract_text_only()
        if text:
            # Try to parse the raw text for holdings
            text_holdings = self._parse_text_for_holdings(text)
            if text_holdings:
                return {
                    'tool': 'text_extraction',
                    'status': 'success',
                    'holdings': text_holdings,
                    'count': len(text_holdings),
                    'note': 'Extracted from raw text (table detection failed)'
                }
            else:
                return {
                    'tool': 'text_extraction',
                    'status': 'partial',
                    'text': text,
                    'note': 'Extracted raw text. Manual CSV parsing required.'
                }

        return {
            'tool': None,
            'status': 'failed',
            'error': 'All extraction strategies failed',
            'recommendation': 'Create CSV manually or try alternative PDF tools'
        }


def main():
    """Extract holdings from PDF."""
    if len(sys.argv) < 2:
        print("Usage: python3 extract_pdf.py <pdf_file> [output_csv]")
        sys.exit(1)

    pdf_path = Path(sys.argv[1])
    if not pdf_path.exists():
        print(f"Error: {pdf_path} not found")
        sys.exit(1)

    output_csv = sys.argv[2] if len(sys.argv) > 2 else str(pdf_path).replace('.pdf', '_extracted.csv')

    phase(Phase.EXTRACT_PDF, f"Extracting holdings from {pdf_path.name}...")

    extractor = PDFExtractor(pdf_path, timeout=30)
    result = extractor.extract()

    print(json.dumps(result, separators=(',',':'), default=str))

    if result['status'] == 'success':
        import csv
        # Determine all possible fieldnames from the holdings
        all_fields = {'symbol', 'shares', 'price', 'exposure', 'asset_type', 'market_value', 'cusip', 'par_value', 'coupon_rate', 'maturity_date', 'price_percent'}
        for holding in result['holdings']:
            all_fields.update(holding.keys())
        fieldnames = sorted(list(all_fields))

        with open(output_csv, 'w') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames, restval='')
            writer.writeheader()
            for holding in result['holdings']:
                # Default asset_type to equity if not already set
                if 'asset_type' not in holding:
                    holding['asset_type'] = 'equity'
                writer.writerow(holding)
        print(f"\n✅ Extracted {result['count']} holdings to {output_csv}")
    elif result['status'] == 'partial':
        print(f"\n⚠️  Raw text extracted. Manually parse and create CSV.")
    else:
        print(f"\n❌ Extraction failed: {result.get('error')}")
        print(f"💡 Recommendation: {result.get('recommendation')}")


if __name__ == "__main__":
    main()
