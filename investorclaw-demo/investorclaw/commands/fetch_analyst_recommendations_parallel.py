#!/usr/bin/env python3
"""
Parallel analyst recommendations fetcher with progressive tier-based loading.

Features:
- 3-tier progressive loading (immediate top 10, parallel background, enrichment)
- Parallel fetching with ThreadPoolExecutor (network-bound I/O optimization)
- Real-time progress monitoring and notifications
- Exponential backoff retry logic with configurable limits
- Guardrails validation (optional)

Note: API calls to yfinance are network-bound, not compute-bound. ThreadPoolExecutor
with 4-8 workers provides optimal parallelism without GPU acceleration overhead.
"""

import yfinance as yf
import polars as pl
import json
import os
import subprocess
import time
import logging
import uuid
from dataclasses import dataclass, asdict, field
from typing import Dict, List, Optional, Tuple, Callable
from datetime import datetime
from pathlib import Path
import concurrent.futures
import sys
from pathlib import Path as _Path

# sys.path guard: ensures relative imports resolve when this script is invoked
# directly (e.g. for testing) rather than via the investorclaw.py entry point.
# Regression tag: import_path_regression
_SCRIPTS_DIR = _Path(__file__).resolve().parent
_SKILL_DIR = _SCRIPTS_DIR.parent
for _p in (str(_SKILL_DIR), str(_SCRIPTS_DIR)):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from rendering.compact_serializers import serialize_analyst_compact

# Phase 9: Mode and feature enforcement
try:
    from config.feature_manager import FeatureManager, FeatureNotAvailableError
    from config.config_loader import get_deployment_mode
    from config.deployment_modes import DeploymentMode, Feature
    from config.guardrail_enforcer import GuardrailEnforcer
    _features_available = True
except ImportError as e:
    _features_available = False

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - [%(name)s] %(message)s'
)
logger = logging.getLogger(__name__)


# ============================================================================
# DATA MODELS
# ============================================================================

@dataclass
class AnalystConsensus:
    """Aggregated analyst recommendations"""
    symbol: str
    current_price: float
    consensus_recommendation: Optional[str] = None

    buy_count: int = 0
    hold_count: int = 0
    sell_count: int = 0
    total_recommendations: int = 0

    target_price_mean: Optional[float] = None
    target_price_high: Optional[float] = None
    target_price_low: Optional[float] = None
    target_price_current: Optional[float] = None

    recommendation_change_30d: str = "neutral"
    upgrades_30d: int = 0
    downgrades_30d: int = 0

    data_source: str = "Yahoo Finance"
    data_timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    analyst_count: int = 0
    recommendation_mean: Optional[float] = None  # 1.0-5.0 scale; None = no data (not a "Hold")
    fetch_time_ms: int = 0


@dataclass
class FetchMetrics:
    """Track fetching performance"""
    tier: str
    symbols_requested: int
    symbols_successful: int
    symbols_failed: int
    total_time_ms: float
    avg_time_per_symbol_ms: float
    errors: List[Tuple[str, str]] = field(default_factory=list)
    compute_target: str = "cpu"


@dataclass
class FetchNotification:
    """Progress notification for UI/logging"""
    event_type: str  # 'tier_started', 'tier_progress', 'tier_complete', 'error'
    tier: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    progress_pct: int = 0
    message: str = ""
    data: Dict = field(default_factory=dict)


# ============================================================================
# CALLBACK HANDLER FOR PROGRESS NOTIFICATIONS
# ============================================================================

class NotificationHandler:
    """Handle progress notifications (can be overridden for custom UI)"""

    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or Path.home() / "portfolio_reports"
        self.output_dir.mkdir(exist_ok=True)
        # Notifications are internal pipeline state — write to .raw/ not agent-readable dir
        _raw = self.output_dir / ".raw"
        _raw.mkdir(exist_ok=True)
        self.notification_file = _raw / "analyst_fetch_notifications.jsonl"
        self.notifications = []

    def notify(self, notification: FetchNotification):
        """Handle a notification"""
        self.notifications.append(notification)

        # Log
        if notification.event_type == 'tier_started':
            logger.info(f"📊 {notification.message}")
        elif notification.event_type == 'tier_progress':
            logger.debug(f"  [{notification.progress_pct}%] {notification.message}")
        elif notification.event_type == 'tier_complete':
            logger.info(f"✅ {notification.message}")
        elif notification.event_type == 'error':
            logger.warning(f"⚠️  {notification.message}")

        # Save to file
        with open(self.notification_file, 'a') as f:
            f.write(json.dumps(asdict(notification), default=str) + '\n')

    def get_notifications(self, event_type: str = None) -> List[FetchNotification]:
        """Get notifications, optionally filtered by type"""
        if event_type:
            return [n for n in self.notifications if n.event_type == event_type]
        return self.notifications


# ============================================================================
# PARALLEL ANALYST FETCHER
# ============================================================================

class ParallelAnalystFetcher:
    """
    Fetch analyst recommendations with progressive tier-based loading.

    Tier 1: Top 10 holdings by value (immediate sequential fetch)
    Tier 2: Remaining holdings (parallel ThreadPoolExecutor)
    Tier 3: Enrichment/synthesis (optional LLM enrichment)
    """

    TIER1_SIZE = 10
    TIER2_CHUNK_SIZE = 10
    TIER2_RETRY_MAX = 3
    TIER2_RETRY_BACKOFF = 2.0
    REQUEST_TIMEOUT = 10

    def __init__(self, output_dir: Path = None):
        self.output_dir = output_dir or Path.home() / "portfolio_reports"
        self.output_dir.mkdir(exist_ok=True)

        self.recommendations: Dict[str, AnalystConsensus] = {}
        self.errors: List[Tuple[str, str]] = []
        self.metrics: List[FetchMetrics] = []

        # Notifications
        self.notification_handler = NotificationHandler(self.output_dir)

        # Executor config: Simple ThreadPoolExecutor for network-bound I/O
        # API calls to yfinance are network-bound (~100ms/call), not compute-bound
        # ThreadPoolExecutor with 4-8 workers provides optimal parallelism
        self.executor_type = 'ThreadPoolExecutor'
        self.max_workers = 5  # Balance between parallelism and rate-limit friendliness
        self.compute_target = 'network_bound_io'  # Not CPU-bound, not GPU-bound

        logger.info(f"🚀 Initialized ParallelAnalystFetcher")
        logger.info(f"   Executor: {self.executor_type} ({self.max_workers} workers)")
        logger.info(f"   Workload: Network-bound I/O (API calls to yfinance)")

    @staticmethod
    def _yf_ticker(symbol: str) -> str:
        """Normalise broker symbol to yfinance format (BRK.B → BRK-B)."""
        return symbol.replace(".", "-")

    @staticmethod
    def _parse_avg_rating(avg_rating: str) -> Optional[float]:
        """Parse yfinance averageAnalystRating (e.g. '2.4 - Buy') into a numeric mean."""
        import re
        if not avg_rating:
            return None
        m = re.match(r"^\s*([0-9]+(?:\.[0-9]+)?)", str(avg_rating))
        return float(m.group(1)) if m else None

    def _fetch_consensus(self, symbol: str) -> Optional[Tuple[str, AnalystConsensus, float]]:
        """Fetch single symbol (with timing)"""
        start = time.time()
        try:
            # Normalise broker symbols: BRK.B → BRK-B (yfinance uses hyphens, not periods)
            ticker = yf.Ticker(self._yf_ticker(symbol))
            info = ticker.info

            current_price = info.get('currentPrice') or info.get('regularMarketPrice')
            if current_price is None:
                logger.debug(f"No price for {symbol}")
                return (symbol, None, (time.time() - start) * 1000)

            analyst_count = info.get('numberOfAnalystOpinions', 0)
            rec_key = info.get('recommendationKey', '').lower()

            # recommendationMean is absent for some tickers; try averageAnalystRating fallback
            # (yfinance returns strings like "2.4 - Buy" for certain ticker categories)
            rec_mean = info.get('recommendationMean')
            if rec_mean is None:
                rec_mean = self._parse_avg_rating(info.get('averageAnalystRating'))

            # Estimate distribution
            buy_count = hold_count = sell_count = 0
            if analyst_count > 0 and rec_mean is not None:
                if rec_mean < 2.0:
                    buy_count = int(analyst_count * 0.60)
                    hold_count = int(analyst_count * 0.30)
                    sell_count = analyst_count - buy_count - hold_count
                elif rec_mean < 2.5:
                    buy_count = int(analyst_count * 0.50)
                    hold_count = int(analyst_count * 0.40)
                    sell_count = analyst_count - buy_count - hold_count
                elif rec_mean < 3.5:
                    buy_count = int(analyst_count * 0.20)
                    hold_count = int(analyst_count * 0.60)
                    sell_count = analyst_count - buy_count - hold_count
                else:
                    buy_count = int(analyst_count * 0.10)
                    hold_count = int(analyst_count * 0.30)
                    sell_count = analyst_count - buy_count - hold_count

            # Consensus recommendation — prefer rec_key (explicit label) then rec_mean
            consensus_rec = None
            if rec_key in ("buy", "strong_buy"):
                consensus_rec = "Strong Buy" if rec_key == "strong_buy" else "Buy"
            elif rec_key == "hold":
                consensus_rec = "Hold"
            elif rec_key in ("sell", "underperform", "strong_sell"):
                consensus_rec = "Sell"
            elif rec_mean is not None:
                if rec_mean < 2.0:
                    consensus_rec = "Strong Buy"
                elif rec_mean < 2.5:
                    consensus_rec = "Buy"
                elif rec_mean < 3.5:
                    consensus_rec = "Hold"
                else:
                    consensus_rec = "Sell"

            target_price = info.get('targetMeanPrice')
            target_high = info.get('targetHighPrice')
            target_low = info.get('targetLowPrice')

            fetch_time = (time.time() - start) * 1000

            consensus = AnalystConsensus(
                symbol=symbol,
                current_price=float(current_price),
                consensus_recommendation=consensus_rec,
                buy_count=buy_count,
                hold_count=hold_count,
                sell_count=sell_count,
                total_recommendations=analyst_count,
                target_price_mean=target_price,
                target_price_high=target_high,
                target_price_low=target_low,
                target_price_current=float(current_price),
                analyst_count=analyst_count,
                recommendation_mean=float(rec_mean) if rec_mean is not None else None,
                data_timestamp=datetime.now().isoformat(),
                fetch_time_ms=int(fetch_time)
            )

            return (symbol, consensus, fetch_time)

        except Exception as e:
            fetch_time = (time.time() - start) * 1000
            error_msg = f"Failed to fetch {symbol}: {str(e)}"
            logger.debug(error_msg)
            self.errors.append((symbol, error_msg))
            return (symbol, None, fetch_time)

    def _fetch_with_retry(self, symbol: str, retry_count: int = 0) -> Optional[Tuple[str, AnalystConsensus, float]]:
        """Fetch with exponential backoff"""
        result = self._fetch_consensus(symbol)
        symbol_result, consensus, fetch_time = result

        if consensus is None and retry_count < self.TIER2_RETRY_MAX:
            wait_time = self.TIER2_RETRY_BACKOFF ** retry_count
            logger.debug(f"Retrying {symbol} in {wait_time:.1f}s (attempt {retry_count + 1})")
            time.sleep(wait_time)
            return self._fetch_with_retry(symbol, retry_count + 1)

        return result

    def fetch_tier1_immediate(self, symbols_weighted: List[Tuple[str, float]]) -> Tuple[Dict[str, AnalystConsensus], FetchMetrics]:
        """TIER 1: Fetch top N symbols immediately"""
        tier1_symbols = [s[0] for s in symbols_weighted[:self.TIER1_SIZE]]

        # Notify
        self.notification_handler.notify(FetchNotification(
            event_type='tier_started',
            tier='tier1',
            message=f"Fetching top {len(tier1_symbols)} holdings immediately"
        ))

        logger.info(f"📊 TIER 1: Fetching top {len(tier1_symbols)} holdings immediately")

        start = time.time()
        results = {}
        successful = 0
        failed = 0

        for i, symbol in enumerate(tier1_symbols, 1):
            symbol_result, consensus, fetch_time = self._fetch_consensus(symbol)
            if consensus:
                results[symbol] = consensus
                successful += 1
                logger.debug(f"✓ [{i}/{len(tier1_symbols)}] {symbol} - {fetch_time:.0f}ms")
            else:
                failed += 1
                logger.debug(f"✗ [{i}/{len(tier1_symbols)}] {symbol}")

            # Progress notification
            progress_pct = int((i / len(tier1_symbols)) * 100)
            self.notification_handler.notify(FetchNotification(
                event_type='tier_progress',
                tier='tier1',
                progress_pct=progress_pct,
                message=f"{i}/{len(tier1_symbols)} symbols"
            ))

        total_time = (time.time() - start) * 1000

        metrics = FetchMetrics(
            tier="1_immediate",
            symbols_requested=len(tier1_symbols),
            symbols_successful=successful,
            symbols_failed=failed,
            total_time_ms=total_time,
            avg_time_per_symbol_ms=total_time / len(tier1_symbols) if tier1_symbols else 0,
            compute_target=self.compute_target
        )

        # Notify completion
        self.notification_handler.notify(FetchNotification(
            event_type='tier_complete',
            tier='tier1',
            message=f"TIER 1 Complete: {successful}/{len(tier1_symbols)} in {total_time/1000:.1f}s"
        ))

        logger.info(f"✅ TIER 1 Complete: {successful}/{len(tier1_symbols)} in {total_time/1000:.1f}s")

        logger.info(f"Tier 1 complete: {successful}/{len(tier1_symbols)} symbols, fetching remaining {len(symbols_weighted) - len(tier1_symbols)} in background")

        self.metrics.append(metrics)
        self.recommendations.update(results)
        return results, metrics

    def fetch_tier2_background(self, symbols_weighted: List[Tuple[str, float]]) -> Tuple[Dict[str, AnalystConsensus], FetchMetrics]:
        """TIER 2: Fetch remaining symbols in parallel"""
        tier2_symbols = [s[0] for s in symbols_weighted[self.TIER1_SIZE:]]

        if not tier2_symbols:
            logger.info("📊 TIER 2: No remaining symbols")
            return {}, FetchMetrics(
                tier="2_background",
                symbols_requested=0,
                symbols_successful=0,
                symbols_failed=0,
                total_time_ms=0,
                avg_time_per_symbol_ms=0,
                compute_target=self.compute_target
            )

        # Notify
        self.notification_handler.notify(FetchNotification(
            event_type='tier_started',
            tier='tier2',
            message=f"Fetching {len(tier2_symbols)} remaining holdings (parallel, {self.executor_type})"
        ))

        logger.info(f"📊 TIER 2: Fetching {len(tier2_symbols)} holdings with {self.max_workers} {self.executor_type} workers")

        start = time.time()
        results = {}
        successful = 0
        failed = 0
        completed = 0

        # Use ThreadPoolExecutor for I/O-bound fetching
        with concurrent.futures.ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(self._fetch_with_retry, symbol): symbol
                for symbol in tier2_symbols
            }

            for future in concurrent.futures.as_completed(futures):
                completed += 1
                symbol = futures[future]
                try:
                    symbol_result, consensus, fetch_time = future.result(timeout=self.REQUEST_TIMEOUT * 2)
                    if consensus:
                        results[symbol] = consensus
                        successful += 1
                        logger.debug(f"✓ [{completed}/{len(tier2_symbols)}] {symbol} - {fetch_time:.0f}ms")
                    else:
                        failed += 1
                        logger.debug(f"✗ [{completed}/{len(tier2_symbols)}] {symbol}")
                except Exception as e:
                    failed += 1
                    logger.warning(f"Error fetching {symbol}: {e}")
                    self.errors.append((symbol, str(e)))

                # Progress notification every 10 symbols
                if completed % 10 == 0 or completed == len(tier2_symbols):
                    progress_pct = int((completed / len(tier2_symbols)) * 100)
                    self.notification_handler.notify(FetchNotification(
                        event_type='tier_progress',
                        tier='tier2',
                        progress_pct=progress_pct,
                        message=f"{completed}/{len(tier2_symbols)} symbols"
                    ))

        total_time = (time.time() - start) * 1000

        metrics = FetchMetrics(
            tier="2_background",
            symbols_requested=len(tier2_symbols),
            symbols_successful=successful,
            symbols_failed=failed,
            total_time_ms=total_time,
            avg_time_per_symbol_ms=total_time / len(tier2_symbols) if tier2_symbols else 0,
            compute_target=self.compute_target
        )

        # Notify completion
        self.notification_handler.notify(FetchNotification(
            event_type='tier_complete',
            tier='tier2',
            message=f"TIER 2 Complete: {successful}/{len(tier2_symbols)} in {total_time/1000:.1f}s (~{total_time/len(tier2_symbols)/1000:.2f}s/symbol)"
        ))

        logger.info(f"✅ TIER 2 Complete: {successful}/{len(tier2_symbols)} in {total_time/1000:.1f}s")

        self.metrics.append(metrics)
        self.recommendations.update(results)
        return results, metrics

    def save_tier_results(self, tier: str, results: Dict[str, AnalystConsensus], metrics: FetchMetrics):
        """Save tier results"""
        results_json = {
            symbol: {
                **asdict(consensus),
                'data_timestamp': consensus.data_timestamp
            }
            for symbol, consensus in results.items()
        }

        # Raw tier files go to .raw/ — not for direct LLM reads
        raw_dir = self.output_dir / ".raw"
        raw_dir.mkdir(parents=True, exist_ok=True)
        output_file = raw_dir / f"analyst_recommendations_{tier}.json"

        with open(output_file, 'w') as f:
            json.dump({
                '_note': (
                    f"DOWNSTREAM SCRIPTS ONLY — Do NOT read this file for LLM analysis. "
                    f"This is raw {tier} analyst data for internal pipeline use. "
                    f"Read analyst_recommendations_summary.json (compact) instead."
                ),
                'tier': tier,
                'timestamp': datetime.now().isoformat(),
                'metrics': asdict(metrics),
                'compute_target': self.compute_target,
                'recommendations': results_json,
            }, f, indent=2, default=str)

        logger.info(f"💾 Saved {tier} results to {output_file}")

    def generate_summary_report(self, output_file: str = None) -> Dict:
        """Generate summary report"""

        # Phase 9: Check feature availability
        if _features_available:
            try:
                mode_str = get_deployment_mode()
                mode = DeploymentMode(mode_str)
                fm = FeatureManager(mode)
                fm.require_feature(Feature.ANALYST_RATINGS)  # Core feature, all modes
                logger.info(f"Analyst ratings enabled for {mode_str} mode")
            except FeatureNotAvailableError as e:
                logger.error(f"Analyst ratings not available: {e}")
                raise

        output_file = output_file or str(self.output_dir / "analyst_recommendations_summary.json")

        total_requested = sum(m.symbols_requested for m in self.metrics)
        total_successful = sum(m.symbols_successful for m in self.metrics)
        total_failed = sum(m.symbols_failed for m in self.metrics)
        total_time = sum(m.total_time_ms for m in self.metrics)

        report = {
            'timestamp': datetime.now().isoformat(),
            'fetch_config': {
                'executor_type': self.executor_type,
                'max_workers': self.max_workers,
                'compute_target': self.compute_target,
            },
            'summary': {
                'total_symbols': total_requested,
                'successful': total_successful,
                'failed': total_failed,
                'success_rate': f"{(total_successful/total_requested*100):.1f}%" if total_requested > 0 else "N/A",
                'total_time_seconds': round(total_time / 1000, 1),
                'avg_time_per_symbol_ms': round(total_time / total_requested, 0) if total_requested > 0 else 0,
            },
            'by_tier': [asdict(m) for m in self.metrics],
            'recommendations_count': len(self.recommendations),
            'analyst_coverage': {
                'no_coverage': len([r for r in self.recommendations.values() if r.analyst_count == 0]),
                'light_coverage': len([r for r in self.recommendations.values() if 1 <= r.analyst_count < 5]),
                'moderate_coverage': len([r for r in self.recommendations.values() if 5 <= r.analyst_count < 15]),
                'strong_coverage': len([r for r in self.recommendations.values() if r.analyst_count >= 15]),
            }
        }

        # Phase 9: Apply guardrails based on deployment mode
        if _features_available:
            try:
                mode_str = get_deployment_mode()
                mode = DeploymentMode(mode_str)
                enforcer = GuardrailEnforcer(mode)

                # Apply appropriate disclaimer based on mode
                analyst_text = json.dumps(report, indent=2, default=str)
                enforcer.add_professional_disclaimer(analyst_text)
                logger.info(f"Applied {mode_str} guardrails and disclaimers")
            except Exception as e:
                logger.warning(f"Could not apply mode-specific guardrails: {e}")

        with open(output_file, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        logger.info(f"📋 Summary report saved to {output_file}")
        return report

    def print_summary_report(self, verbose: bool = False):
        """Print compact (default) or full (--verbose) summary to console."""
        if not self.metrics:
            logger.warning("No metrics available")
            return

        total_requested = sum(m.symbols_requested for m in self.metrics)
        total_successful = sum(m.symbols_successful for m in self.metrics)
        total_time = sum(m.total_time_ms for m in self.metrics)
        avg_analysts = (sum(r.analyst_count for r in self.recommendations.values()) /
                        len(self.recommendations) if self.recommendations else 0)

        pct = (total_successful / total_requested * 100) if total_requested else 0
        print(f"Analyst data: {total_successful}/{total_requested} symbols "
              f"({pct:.1f}%) in {total_time/1000:.1f}s | "
              f"avg {avg_analysts:.1f} analysts/symbol")

        if verbose:
            print(f"  Executor: {self.executor_type} ({self.max_workers} workers)")
            for metric in self.metrics:
                print(f"  {metric.tier}: {metric.symbols_successful}/{metric.symbols_requested} "
                      f"in {metric.total_time_ms/1000:.1f}s")


def fetch_analyst_for_holdings(holdings_file: str, verbose: bool = False) -> Dict[str, AnalystConsensus]:
    """
    Convenience function: Load holdings, fetch with parallel progressive loading.
    """
    # Load holdings
    with open(Path(holdings_file).expanduser(), 'r') as f:
        holdings_data = json.load(f)

    # Unwrap disclaimer wrapper (DisclaimerWrapper nests payload under 'data' key)
    if 'data' in holdings_data and isinstance(holdings_data['data'], dict):
        holdings_data = holdings_data['data']

    # Extract symbols with portfolio weights
    symbols_weighted = []

    if 'portfolio' in holdings_data:
        portfolio = holdings_data['portfolio']

        # CDM format: portfolio.portfolioState.positions[].asset.securityName / .marketValue
        portfolio_state = portfolio.get('portfolioState', {})
        cdm_positions = portfolio_state.get('positions', [])
        if cdm_positions:
            EQUITY_TYPES = {'equity', 'etf', 'fund', 'mutual fund', 'stock'}
            for pos in cdm_positions:
                asset = pos.get('asset', {})
                sec_type = asset.get('securityType', '').lower()
                symbol = asset.get('securityName', '').strip()
                value = pos.get('marketValue', 0) or 0
                if symbol and sec_type in EQUITY_TYPES:
                    symbols_weighted.append((symbol, float(value)))
        else:
            # Legacy flat format: portfolio.equity.{symbol: {value: ...}}
            for asset_type, assets in portfolio.items():
                if asset_type not in ('equity',):
                    continue
                if isinstance(assets, dict):
                    for symbol, asset_data in assets.items():
                        if isinstance(asset_data, dict):
                            value = asset_data.get('value', 0)
                            symbols_weighted.append((symbol, value))

    symbols_weighted.sort(key=lambda x: x[1], reverse=True)

    logger.info(f"📂 Loaded {len(symbols_weighted)} holdings from {holdings_file}")

    # Resolve dated output directory (same as other commands)
    try:
        from config.path_resolver import get_reports_dir as _get_reports_dir
        _fetcher_output_dir = _get_reports_dir()
    except Exception:
        _fetcher_output_dir = Path(os.environ.get("INVESTOR_CLAW_REPORTS_DIR", str(Path.home() / "portfolio_reports")))

    # Fetch with parallel progressive loading
    fetcher = ParallelAnalystFetcher(output_dir=_fetcher_output_dir)

    # Tier 1: Immediate
    tier1_results, tier1_metrics = fetcher.fetch_tier1_immediate(symbols_weighted)
    fetcher.save_tier_results("tier1_immediate", tier1_results, tier1_metrics)

    # Tier 2: Parallel background
    tier2_results, tier2_metrics = fetcher.fetch_tier2_background(symbols_weighted)
    fetcher.save_tier_results("tier2_background", tier2_results, tier2_metrics)

    # Summary
    fetcher.generate_summary_report()
    fetcher.print_summary_report(verbose=verbose)

    return fetcher.recommendations


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 fetch_analyst_recommendations_parallel.py <holdings.json> [--tier3]")
        print("       --tier3: Enable Tier 3 LLM enrichment (requires Ollama)")
        sys.exit(1)

    holdings_file = sys.argv[1]
    enable_tier3 = "--tier3" in sys.argv
    verbose = True
    # --tier3-limit N: cap enrichment to N symbols (useful for testing)
    tier3_limit: Optional[int] = None
    if "--tier3-limit" in sys.argv:
        _idx = sys.argv.index("--tier3-limit")
        if _idx + 1 < len(sys.argv):
            try:
                tier3_limit = int(sys.argv[_idx + 1])
            except ValueError:
                pass

    recommendations = fetch_analyst_for_holdings(holdings_file, verbose=verbose)

    print(f"Analyst data: {len(recommendations)} symbols — see analyst_data.json for full detail")

    # Resolve output paths — use dated subdirectory (same as other commands)
    try:
        from config.path_resolver import get_reports_dir as _get_reports_dir
        _reports_dir = _get_reports_dir()
    except Exception:
        _reports_dir = Path(os.environ.get("INVESTOR_CLAW_REPORTS_DIR", str(Path.home() / "portfolio_reports")))
    _raw_dir = _reports_dir / ".raw"
    _raw_dir.mkdir(parents=True, exist_ok=True)
    # sys.argv[2] is the output_file injected by command_builders (.raw/analyst_data.json)
    _raw_data_file = Path(sys.argv[2]) if len(sys.argv) > 2 and not sys.argv[2].startswith("--") else (_raw_dir / "analyst_data.json")

    analyst_payload: dict = {
        'disclaimer': 'EDUCATIONAL ANALYSIS - NOT INVESTMENT ADVICE',
        'timestamp': datetime.now().isoformat(),
        'total_symbols': len(recommendations),
        'output_file': str(_reports_dir / "analyst_recommendations_summary.json"),
        'recommendations': {
            symbol: {
                'symbol': rec.symbol,
                'consensus': rec.consensus_recommendation or (
                    'No Coverage' if rec.analyst_count == 0 else 'Unknown'
                ),
                'analyst_count': rec.analyst_count,
                'recommendation_mean': rec.recommendation_mean if rec.recommendation_mean is not None else 0.0,
                'current_price': rec.current_price,
                'buy_count': rec.buy_count,
                'hold_count': rec.hold_count,
                'sell_count': rec.sell_count,
                'target_price_mean': rec.target_price_mean if rec.target_price_mean is not None else 0.0,
                'data_source': rec.data_source,
            }
            for symbol, rec in recommendations.items()
        }
    }

    # Optional Tier 3: LLM enrichment
    enriched = None
    _consultation_model = None
    if enable_tier3:
        print("\n--- Tier 3: consultation enrichment ---")
        print("Enriching recommendations via consultation model...")

        try:
            from tier3_enrichment import Tier3Enricher

            enricher = Tier3Enricher()
            if not enricher.client.is_available():
                print("Consultation unavailable — check INVESTORCLAW_CONSULTATION_ENDPOINT")
                print(f"  endpoint: {enricher.client.endpoint}")
                print(f"  model: {enricher.client.model}")
            else:
                enriched = enricher.enrich_batch(recommendations, limit=tier3_limit)
                _consultation_model = enricher.client.model
                suffix = f" (limit={tier3_limit})" if tier3_limit else ""
                print(f"Enriched {len(enriched)} recommendations via {_consultation_model}{suffix}")

                # Save enriched results (include full attribution per symbol)
                enriched_output = {
                    'tier': 'tier3_enrichment',
                    'consultation_model': _consultation_model,
                    'consultation_endpoint': enricher.client.endpoint,
                    'timestamp': datetime.now().isoformat(),
                    'total_enriched': len(enriched),
                    'enriched_recommendations': {
                        symbol: {
                            'consensus': rec.consensus,
                            'analyst_count': rec.analyst_count,
                            'sentiment': rec.sentiment_label,
                            'sentiment_score': rec.sentiment_score,
                            'recommendation_strength': rec.recommendation_strength,
                            'synthesis': rec.synthesis,
                            'key_insights': rec.key_insights,
                            'risk_assessment': rec.risk_assessment,
                            'consultation': rec.consultation,
                            'fingerprint': getattr(rec, 'fingerprint', ''),
                            'quote': getattr(rec, 'quote', None),
                        }
                        for symbol, rec in enriched.items()
                    }
                }

                # tier3 enriched goes to .raw/ — it is a full enrichment artifact, not compact
                _raw_dir.mkdir(parents=True, exist_ok=True)
                enriched_file = _raw_dir / "analyst_recommendations_tier3_enriched.json"
                with open(enriched_file, 'w') as f:
                    json.dump(enriched_output, f, indent=2, default=str)

                print(f"Report: {enriched_file}")

                # Write enrichment_progress.json with fingerprint chain
                try:
                    from services.consultation_policy import update_session_fingerprint, is_consultation_enabled
                    _enriched_syms = list(enriched.keys())
                    _chain = ["0000000000000000"]
                    for _sym in _enriched_syms:
                        _synth = getattr(enriched[_sym], 'synthesis', '')
                        _chain.append(update_session_fingerprint(_chain[-1], _sym, _synth))
                    _progress = {
                        "version": 1,
                        "run_id": str(uuid.uuid4()),
                        "model": _consultation_model,
                        "started_at": datetime.now().isoformat(),
                        "last_updated": datetime.now().isoformat(),
                        "total_symbols": len(recommendations),
                        "enriched_count": len(_enriched_syms),
                        "enriched_symbols": _enriched_syms,
                        "failed_symbols": [],
                        "in_progress": False,
                        "background_pid": None,
                        "session_fingerprint": _chain[-1],
                        "fingerprint_chain": _chain,
                        "estimated_remaining_s": 0,
                        "bonds_covered": False,
                    }
                    _prog_file = _raw_dir / "enrichment_progress.json"
                    _tmp = _prog_file.with_suffix(".tmp")
                    with open(_tmp, 'w') as _f:
                        json.dump(_progress, _f, indent=2, default=str)
                    os.rename(_tmp, _prog_file)

                    # Spawn background_enricher for remaining symbols
                    _bg_path = Path(__file__).resolve().parent.parent / "workers" / "background_enricher.py"
                    _remaining = len(recommendations) - len(_enriched_syms)
                    if _bg_path.exists() and _remaining > 0 and is_consultation_enabled():
                        _bg = subprocess.Popen(
                            [sys.executable, str(_bg_path),
                             str(_raw_dir),
                             str(_raw_dir / "analyst_data.json"),
                             str(_prog_file)],
                            start_new_session=True,
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                        )
                        _progress["in_progress"] = True
                        _progress["background_pid"] = _bg.pid
                        _progress["estimated_remaining_s"] = _remaining * 24
                        _tmp2 = _prog_file.with_suffix(".tmp")
                        with open(_tmp2, 'w') as _f:
                            json.dump(_progress, _f, indent=2, default=str)
                        os.rename(_tmp2, _prog_file)
                        print(f"Background enricher spawned (PID {_bg.pid}): {_remaining} symbols remaining")
                except Exception as _bg_err:
                    logger.warning("Could not write enrichment_progress.json: %s", _bg_err)

        except ImportError as e:
            print(f"Tier 3 enrichment import failed: {e}")

    # Write full analyst payload to .raw/analyst_data.json for lookup utility and
    # background_enricher — must be written BEFORE tier3 upgrade so all symbols
    # (not just the enriched subset) are available for background processing.
    with open(_raw_data_file, 'w') as _f:
        full_payload = {
            '_note': ('DOWNSTREAM SCRIPTS / LOOKUP ONLY — Do NOT read this file for LLM analysis. '
                      'Use analyst_recommendations_summary.json or /portfolio lookup --symbol TICKER.'),
            **analyst_payload,
        }
        json.dump(full_payload, _f, indent=2, default=str)

    # Upgrade stdout payload to enriched data when tier3 ran successfully
    if enriched is not None:
        analyst_payload['consultation_model'] = _consultation_model
        analyst_payload['recommendations'] = {
            symbol: {
                'symbol': symbol,
                'consensus': rec.consensus,
                'analyst_count': rec.analyst_count,
                'current_price': getattr(rec, 'current_price', None),
                'sentiment_label': rec.sentiment_label,
                'sentiment_score': rec.sentiment_score,
                'recommendation_strength': rec.recommendation_strength,
                'synthesis': rec.synthesis,
                'key_insights': rec.key_insights,
                'risk_assessment': rec.risk_assessment,
                'consultation': rec.consultation,
                'fingerprint': getattr(rec, 'fingerprint', ''),
                'quote': getattr(rec, 'quote', None),
            }
            for symbol, rec in enriched.items()
        }

    # Emit compact JSON to stdout for LLM context
    print(json.dumps(serialize_analyst_compact(analyst_payload, _reports_dir), separators=(',', ':'), default=str))
