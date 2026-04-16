#!/usr/bin/env python3
"""
Fetch portfolio-aware news directly from Yahoo Finance.
Analyzes news for all holdings and correlates to portfolio impact.
"""
import yfinance as yf
import polars as pl
import sys
import json
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass, asdict
from pathlib import Path
from rendering.disclaimer_wrapper import DisclaimerWrapper
from rendering.compact_serializers import serialize_news_compact

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
class NewsItem:
    """News article with sentiment and portfolio impact"""
    symbol: str
    title: str
    summary: str
    source: str
    link: str
    publish_date: str
    sentiment: str  # 'positive', 'negative', 'neutral'
    confidence: float  # 0-1
    portfolio_impact: float  # $ impact
    impact_pct: float  # % impact on holding

class PortfolioNewsAnalyzer:
    """Fetch and analyze news for portfolio holdings"""

    # Sentiment keywords for simple classification
    POSITIVE_KEYWORDS = [
        'beat', 'beats', 'surge', 'surges', 'gain', 'gains', 'profit', 'profits',
        'growth', 'grows', 'success', 'strong', 'strength', 'record', 'records',
        'rise', 'rises', 'rising', 'rally', 'rallies', 'upgrade', 'upgrades',
        'outperform', 'outperforms', 'bullish', 'partnership', 'partnerships',
        'acquisition', 'acquires', 'deal', 'deals', 'expansion', 'expands',
        'launch', 'launches', 'innovation', 'innovates', 'earnings', 'revenue',
        'revenues', 'margin', 'margins', 'exceeds', 'exceed', 'tops', 'topped',
        'boosts', 'boost', 'advances', 'advance', 'jumps', 'jump', 'climbs',
        'highest', 'soars', 'soar', 'wins', 'win', 'awarded', 'approved',
        'positive', 'optimistic', 'raised guidance', 'raises guidance', 'dividend',
        'buyback', 'buy back', 'stock split', 'profitable', 'narrowed loss',
    ]

    NEGATIVE_KEYWORDS = [
        'drop', 'drops', 'decline', 'declines', 'declining', 'loss', 'losses',
        'fall', 'falls', 'falling', 'crash', 'crashes', 'weakness', 'weak',
        'downgrade', 'downgrades', 'underperform', 'underperforms', 'bearish',
        'default', 'defaults', 'bankruptcy', 'bankrupt', 'scandal', 'scandals',
        'investigation', 'investigate', 'lawsuit', 'lawsuits', 'recall', 'recalls',
        'warning', 'warns', 'miss', 'misses', 'missed', 'cut guidance',
        'cuts guidance', 'restructuring', 'restructure', 'layoff', 'layoffs',
        'lays off', 'charges', 'writedown', 'write-down', 'impairment',
        'disappoints', 'disappointing', 'disappoints', 'plunges', 'plunge',
        'slumps', 'slump', 'tumbles', 'tumble', 'sinks', 'sink', 'loses',
        'concern', 'concerns', 'risk', 'risks', 'penalty', 'fine', 'fined',
        'fraud', 'probe', 'subpoena', 'negative', 'pessimistic', 'shortfall',
        'below expectations', 'missed estimates', 'wider loss',
    ]

    def __init__(self):
        self.portfolio_holdings = {}
        self.all_news = {}
        self.errors = []
        self._company_names: Dict[str, str] = {}  # ticker → short name cache

    @staticmethod
    def _yf_ticker(symbol: str) -> str:
        """Normalise broker symbol to yfinance format (BRK.B → BRK-B)."""
        return symbol.replace(".", "-")

    def _company_name(self, symbol: str) -> str:
        """Return the company short name for *symbol*, lazy-loaded from yfinance."""
        if symbol not in self._company_names:
            try:
                info = yf.Ticker(self._yf_ticker(symbol)).info
                self._company_names[symbol] = (
                    info.get("shortName") or info.get("longName") or ""
                )
            except Exception:
                self._company_names[symbol] = ""
        return self._company_names[symbol]

    def _is_relevant(self, symbol: str, company_name: str, title: str, summary: str) -> bool:
        """Return True only if the article is actually about *symbol*.

        yfinance.Ticker.news returns loosely-related market articles — e.g. an
        AMD query may return a Nvidia article because both trade in the same
        sector.  We keep an article only when the ticker symbol or a distinctive
        token from the company name appears in the headline or summary text.
        """
        import re
        text = f"{title} {summary}".lower()

        # First meaningful word(s) of the company name (checked before ticker for all lengths)
        name_match = False
        if company_name:
            # Drop legal-entity suffixes that appear in many names
            _SUFFIXES = re.compile(
                r"\b(inc|corp|ltd|llc|co|plc|group|holdings|technologies|technology"
                r"|systems|services|solutions|financial|capital|management|partners"
                r"|international|global|enterprises|industries|resources)\b\.?",
                re.I,
            )
            cleaned = _SUFFIXES.sub("", company_name).strip()
            tokens = [t for t in cleaned.split() if len(t) > 3]
            if tokens and tokens[0].lower() in text:
                name_match = True

        if name_match:
            return True

        # Short / single-letter tickers (e.g. "A" for Agilent) have very high
        # false-positive rates with bare-word matching; require the company-name
        # match above.
        if len(symbol) <= 2:
            return False

        # Ticker symbol as a word (case-insensitive) — only for 3+ char symbols
        if re.search(r"\b" + re.escape(symbol.lower()) + r"\b", text):
            return True

        return False

    def load_holdings(self, holdings_file: str) -> None:
        """Load portfolio holdings from JSON"""
        try:
            from pathlib import Path
            from config.schema import normalize_portfolio
            path = Path(holdings_file).expanduser()

            with open(path, 'r') as f:
                data = json.load(f)

            # Normalize CDM/FINOS format to canonical portfolio schema first
            data = normalize_portfolio(data)

            # Support both schemas; handle wrapper 'data' key
            if 'data' in data:
                data = data['data']   # unwrap disclaimer wrapper

            if 'holdings' in data:
                holdings = data.get('holdings', [])
            elif 'portfolio' in data:
                # Convert portfolio schema to holdings list
                holdings = []
                portfolio = data['portfolio']
                for asset_type, assets in portfolio.items():
                    if isinstance(assets, dict):
                        for symbol, asset_data in assets.items():
                            entry = {'symbol': symbol, 'asset_type': asset_type}
                            if isinstance(asset_data, dict):
                                entry.update(asset_data)
                            holdings.append(entry)
            else:
                holdings = []

            for holding in holdings:
                symbol = holding.get('symbol', '').strip()
                current_price = holding.get('current_price', 0)
                value = holding.get('value', 0)
                asset_type = holding.get('asset_type', 'equity')

                if symbol and current_price > 0:
                    self.portfolio_holdings[symbol] = {
                        'current_price': current_price,
                        'value': value,
                        'asset_type': asset_type,
                        'shares': holding.get('shares', 1)
                    }

            logger.info(f"Loaded {len(self.portfolio_holdings)} holdings")

        except Exception as e:
            logger.error(f"Error loading holdings: {e}")
            raise

    def simple_sentiment(self, text: str) -> Tuple[str, float]:
        """
        Simple sentiment analysis based on keywords.
        Returns: (sentiment, confidence)
        """
        if not text:
            return 'neutral', 0.0

        text_lower = text.lower()

        # Count keyword occurrences with word boundaries for better matching
        positive_count = 0
        negative_count = 0

        for kw in self.POSITIVE_KEYWORDS:
            # Count occurrences (can have multiple per text)
            positive_count += text_lower.count(kw)

        for kw in self.NEGATIVE_KEYWORDS:
            negative_count += text_lower.count(kw)

        total = positive_count + negative_count

        if total == 0:
            return 'neutral', 0.3  # Low confidence neutral

        if positive_count > negative_count:
            # Scale confidence: more keywords = higher confidence
            confidence = min(1.0, positive_count / max(10, total))
            return 'positive', confidence
        elif negative_count > positive_count:
            confidence = min(1.0, negative_count / max(10, total))
            return 'negative', confidence
        else:
            return 'neutral', 0.5

    @staticmethod
    def _articles_for_weight(weight_pct: float) -> int:
        """Return how many articles to fetch based on portfolio weight.

        Returns article count based on portfolio weight.
        More articles for larger positions improve sentiment quality.
        """
        if weight_pct >= 5.0:
            return 20
        elif weight_pct >= 2.0:
            return 15
        elif weight_pct >= 0.5:
            return 10
        else:
            return 5

    def fetch_symbol_news(self, symbol: str, max_articles: int = 10) -> List[Dict]:
        """Fetch news for a single symbol from Yahoo Finance.

        Only articles that actually mention the company (by ticker or name) are
        kept — yfinance returns loosely-correlated market news that may be
        primarily about different companies.
        """
        try:
            logger.info(f"Fetching news for {symbol} (max {max_articles} articles)")
            company_name = self._company_name(symbol)
            ticker = yf.Ticker(self._yf_ticker(symbol))

            # Get news from yfinance
            news = ticker.news

            if not news:
                logger.warning(f"No news found for {symbol}")
                return []

            processed_news = []

            for item in news[:max_articles * 3]:  # over-fetch to compensate for filtering
                try:
                    # Modern yfinance: {'id': ..., 'content': {'title': ..., ...}}
                    # Legacy yfinance: {'title': ..., 'summary': ..., ...} at top level
                    _content = item.get('content', {})
                    if isinstance(_content, dict) and _content:
                        title   = _content.get('title', '') or item.get('title', '')
                        summary = (_content.get('summary', '')
                                   or _content.get('description', '')
                                   or item.get('summary', ''))
                        source  = (_content.get('provider', {}).get('displayName', '')
                                   or item.get('source', 'Unknown'))
                        link    = (_content.get('canonicalUrl', {}).get('url', '')
                                   or _content.get('clickThroughUrl', {}).get('url', '')
                                   or item.get('link', ''))
                        pub_raw = _content.get('pubDate', '') or _content.get('displayTime', '')
                        if pub_raw:
                            pub_date = pub_raw[:19]  # ISO 8601 truncated to seconds
                        else:
                            pub_date = datetime.now().isoformat()
                    else:
                        title    = item.get('title', '')
                        summary  = item.get('summary', '')
                        source   = item.get('source', 'Unknown')
                        link     = item.get('link', '')
                        ts       = item.get('providerPublishTime', 0)
                        pub_date = (datetime.fromtimestamp(ts).isoformat()
                                    if ts else datetime.now().isoformat())

                    # Skip articles not relevant to this ticker
                    if not self._is_relevant(symbol, company_name, title, summary):
                        logger.debug(f"Skipping off-topic article for {symbol}: {title[:60]}")
                        continue

                    # Analyze sentiment from title + summary
                    combined_text = f"{title} {summary}"
                    sentiment, confidence = self.simple_sentiment(combined_text)

                    holding_value = self.portfolio_holdings[symbol]['value']
                    impact_multiplier = {
                        'positive':  0.015,
                        'negative': -0.025,
                        'neutral':   0.0,
                    }
                    impact_pct      = impact_multiplier.get(sentiment, 0.0) * confidence
                    portfolio_impact = holding_value * impact_pct

                    processed_news.append({
                        'symbol':           symbol,
                        'title':            title,
                        'summary':          summary,
                        'source':           source,
                        'link':             link,
                        'publish_date':     pub_date,
                        'sentiment':        sentiment,
                        'confidence':       float(confidence),
                        'portfolio_impact': float(portfolio_impact),
                        'impact_pct':       float(impact_pct * 100),
                    })

                    if len(processed_news) >= max_articles:
                        break

                except Exception as e:
                    logger.warning(f"Error processing news item for {symbol}: {e}")
                    continue

            logger.info(
                f"{symbol}: {len(processed_news)} relevant articles "
                f"(company: '{company_name}')"
            )
            return processed_news

        except Exception as e:
            logger.error(f"Error fetching news for {symbol}: {e}")
            self.errors.append(f"Failed to fetch news for {symbol}: {e}")
            return []

    def fetch_all_news(self, holdings_file: str, output_file: str = None,
                       top_n: int = 30, cache_file: str = None) -> Dict:
        """Fetch news for top N holdings by portfolio weight.

        Only the top_n holdings (by $ value) are fetched.  Full article data
        is written to cache_file (separate from the agent-facing output) so
        on-demand per-symbol lookups work without re-fetching.  The agent-facing
        output (output_file / return value) is a compact digest — ~3K tokens
        instead of 300K+ for the full all_news array.
        """

        # Phase 9: Check feature availability
        if _features_available:
            try:
                mode_str = get_deployment_mode()
                mode = DeploymentMode(mode_str)
                fm = FeatureManager(mode)
                fm.require_feature(Feature.NEWS_SENTIMENT)  # Core feature, all modes
                logger.info(f"News sentiment analysis enabled for {mode_str} mode")
            except FeatureNotAvailableError as e:
                logger.error(f"News sentiment not available: {e}")
                raise

        self.load_holdings(holdings_file)

        total_holdings = len(self.portfolio_holdings)

        # Rank by portfolio value; fetch only the top_n
        ranked = sorted(
            self.portfolio_holdings.items(),
            key=lambda kv: kv[1]['value'],
            reverse=True
        )
        fetch_symbols = [sym for sym, _ in ranked[:top_n]]
        skipped_symbols = [sym for sym, _ in ranked[top_n:]]

        total_value = sum(h['value'] for h in self.portfolio_holdings.values()) or 1.0

        logger.info(
            f"Fetching news for top {len(fetch_symbols)} of {total_holdings} holdings "
            f"({len(skipped_symbols)} skipped — available on-demand)"
        )

        all_news_items = []
        positive_news = []
        negative_news = []
        per_symbol_cache: Dict[str, List[Dict]] = {}
        # Deduplication: track (url, normalised_title) across all symbols so the
        # same article (often a broad market piece) isn't counted multiple times.
        _seen_urls:   set = set()
        _seen_titles: set = set()

        for symbol in fetch_symbols:
            holding_val = self.portfolio_holdings[symbol]['value']
            weight_pct  = holding_val / total_value * 100
            max_art = self._articles_for_weight(weight_pct)
            raw_items = self.fetch_symbol_news(symbol, max_articles=max_art)

            deduped: List[Dict] = []
            for item in raw_items:
                url   = (item.get('link') or '').strip()
                title_key = item.get('title', '').lower().strip()[:120]
                if url and url in _seen_urls:
                    logger.debug(f"Dedup (url): skipping duplicate article for {symbol}: {title_key[:60]}")
                    continue
                if title_key and title_key in _seen_titles:
                    logger.debug(f"Dedup (title): skipping duplicate article for {symbol}: {title_key[:60]}")
                    continue
                if url:
                    _seen_urls.add(url)
                if title_key:
                    _seen_titles.add(title_key)
                deduped.append(item)

            per_symbol_cache[symbol] = deduped
            all_news_items.extend(deduped)

            for item in deduped:
                if item['sentiment'] == 'positive':
                    positive_news.append(item)
                elif item['sentiment'] == 'negative':
                    negative_news.append(item)

        # Sort by portfolio impact (absolute value)
        sorted_by_impact = sorted(
            all_news_items,
            key=lambda x: abs(x['portfolio_impact']),
            reverse=True
        )

        # Portfolio-level impact totals
        total_positive_impact = sum(i['portfolio_impact'] for i in positive_news)
        total_negative_impact = sum(i['portfolio_impact'] for i in negative_news)
        net_impact = total_positive_impact + total_negative_impact

        # Top movers (title + truncated summary only — keeps tokens low)
        def _compact_item(item: Dict) -> Dict:
            return {
                'symbol': item['symbol'],
                'title': item['title'],
                'url': item.get('link', ''),
                'summary': (item.get('summary') or '')[:300],
                'sentiment': item['sentiment'],
                'confidence': item['confidence'],
                'portfolio_impact': item['portfolio_impact'],
                'impact_pct': item['impact_pct'],
                'publish_date': item['publish_date'],
            }

        top_positive = [_compact_item(i) for i in
                        sorted(positive_news, key=lambda x: x['portfolio_impact'], reverse=True)[:5]]
        top_negative = [_compact_item(i) for i in
                        sorted(negative_news, key=lambda x: x['portfolio_impact'])[:5]]

        # Per-symbol digest: one row per fetched symbol — no full article text
        symbol_digest = []
        for symbol in fetch_symbols:
            items = per_symbol_cache.get(symbol, [])
            holding_val = self.portfolio_holdings[symbol]['value']
            if not items:
                continue
            top = sorted(items, key=lambda x: abs(x['portfolio_impact']), reverse=True)
            top_item = top[0] if top else {}
            pos = sum(1 for i in items if i['sentiment'] == 'positive')
            neg = sum(1 for i in items if i['sentiment'] == 'negative')
            overall    = 'positive' if pos > neg else ('negative' if neg > pos else 'neutral')
            confidence = max((i.get('confidence', 0.5) for i in items), default=0.5)
            article_digest = ''
            symbol_digest.append({
                'symbol':         symbol,
                'weight_pct':     round(holding_val / total_value * 100, 2),
                'article_count':  len(items),
                'sentiment':      overall,
                'confidence':     round(confidence, 2),
                'positive_count': pos,
                'negative_count': neg,
                'top_story':      top_item.get('title', ''),
                'digest':         article_digest,
            })

        # Rule-based macro theme extraction from news titles/summaries.
        # Groups news items by keyword-matched themes across fetched symbols.
        _THEME_KEYWORDS: Dict[str, list] = {
            'AI & Technology Investment': [
                'artificial intelligence', ' ai ', 'chip', 'semiconductor', 'gpu',
                'data center', 'machine learning', 'cloud computing', 'nvidia', 'microsoft',
            ],
            'Trade Policy & Tariffs': [
                'tariff', 'trade war', 'trade deal', 'import duty', 'china trade',
                'sanction', 'trade policy', 'export restriction', 'customs',
            ],
            'Interest Rates & Monetary Policy': [
                'federal reserve', 'fed rate', 'interest rate', 'fomc', 'inflation',
                'rate cut', 'rate hike', 'cpi', 'monetary policy', 'treasury yield',
            ],
            'Corporate Earnings': [
                'earnings', 'quarterly results', 'revenue beat', ' eps ', 'profit',
                'guidance', 'beat expectations', 'missed estimates', 'q1', 'q2', 'q3', 'q4',
            ],
            'Energy & Infrastructure': [
                'oil price', ' oil ', 'energy', 'renewable', 'natural gas', 'lng',
                'clean energy', 'power grid', 'infrastructure', 'utility',
            ],
        }
        _theme_buckets: Dict[str, Dict] = {}
        for _sym in fetch_symbols:
            _items = per_symbol_cache.get(_sym, [])
            _hval = self.portfolio_holdings[_sym]['value']
            _wpct = _hval / total_value * 100
            for _item in _items:
                _text = (_item.get('title', '') + ' ' + (_item.get('summary') or '')).lower()
                for _tname, _keywords in _THEME_KEYWORDS.items():
                    if any(_kw in _text for _kw in _keywords):
                        if _tname not in _theme_buckets:
                            _theme_buckets[_tname] = {'syms': set(), 'pos': set(), 'neg': set()}
                        _theme_buckets[_tname]['syms'].add(_sym)
                        if _item['sentiment'] == 'positive':
                            _theme_buckets[_tname]['pos'].add(_sym)
                        elif _item['sentiment'] == 'negative':
                            _theme_buckets[_tname]['neg'].add(_sym)
        _theme_list = []
        for _tname, _tdata in _theme_buckets.items():
            _n_pos = len(_tdata['pos'])
            _n_neg = len(_tdata['neg'])
            _direction = 'bullish' if _n_pos > _n_neg else ('bearish' if _n_neg > _n_pos else 'neutral')
            _agg_wt = sum(
                self.portfolio_holdings[s]['value'] / total_value * 100
                for s in _tdata['syms'] if s in self.portfolio_holdings
            )
            _theme_list.append({
                'theme': _tname,
                'direction': _direction,
                'portfolio_weight_pct': round(_agg_wt, 1),
                'affected_symbols': sorted(_tdata['syms']),
            })
        _theme_list.sort(key=lambda x: x['portfolio_weight_pct'], reverse=True)
        macro_themes = {'themes': _theme_list} if _theme_list else {'themes': []}

        # Rule-based narrative — always populated so EOD report never has empty narrative.
        # When LLM consultation is enabled, a richer synthesis overwrites this.
        _pos_count = len(positive_news)
        _neg_count = len(negative_news)
        _total     = len(all_news_items)
        _n_syms    = len(fetch_symbols)
        _posture   = (
            'broadly positive' if _pos_count > _neg_count * 2
            else 'broadly negative' if _neg_count > _pos_count * 2
            else 'mixed'
        )
        # Top positive symbols by story count
        _pos_syms = sorted(
            {i['symbol'] for i in positive_news},
            key=lambda s: sum(1 for n in positive_news if n['symbol'] == s),
            reverse=True
        )[:3]
        # Top negative symbols
        _neg_syms = sorted(
            {i['symbol'] for i in negative_news},
            key=lambda s: sum(1 for n in negative_news if n['symbol'] == s),
            reverse=True
        )[:2]

        _narr_parts = [
            f"News sentiment across {_n_syms} covered symbols is {_posture} "
            f"({_pos_count} positive, {_neg_count} negative, "
            f"{_total - _pos_count - _neg_count} neutral across {_total} items)."
        ]
        if _pos_syms:
            _narr_parts.append(f"Positive coverage led by {', '.join(_pos_syms)}.")
        if _neg_syms:
            _narr_parts.append(f"Negative signals noted for {', '.join(_neg_syms)}.")
        if not _neg_syms and not _pos_syms:
            _narr_parts.append("No material single-name signals detected.")

        _tailwinds = [
            i['title'] for i in
            sorted(positive_news, key=lambda x: x['portfolio_impact'], reverse=True)[:3]
        ]
        _risks = [
            i['title'] for i in
            sorted(negative_news, key=lambda x: x['portfolio_impact'])[:3]
        ]

        portfolio_narrative = {
            'overall_posture': ('positive' if _pos_count > _neg_count else
                                'negative' if _neg_count > _pos_count else 'neutral'),
            'narrative': ' '.join(_narr_parts),
            'key_tailwinds': _tailwinds,
            'key_risks': _risks,
        }

        compact_report = {
            'timestamp': datetime.now().isoformat(),
            'symbols_fetched': len(fetch_symbols),
            'symbols_skipped': len(skipped_symbols),
            'skipped_available_on_demand': True,
            'total_news_items': len(all_news_items),
            'portfolio_impact_summary': {
                'net_impact': float(net_impact),
                'positive_impact': float(total_positive_impact),
                'negative_impact': float(total_negative_impact),
                'impact_pct': float(net_impact / total_value * 100),
            },
            'sentiment_breakdown': {
                'positive_news_count': len(positive_news),
                'negative_news_count': len(negative_news),
                'neutral_news_count': len(all_news_items) - len(positive_news) - len(negative_news),
            },
            'top_positive_movers': top_positive,
            'top_negative_movers': top_negative,
            'symbol_digest': symbol_digest,
            'macro_themes':        macro_themes,
            'portfolio_narrative': portfolio_narrative,
            # NOTE: full article text is NOT included here — see cache file
            'errors': self.errors if self.errors else None,
        }

        # Write full article cache (agent never loads this directly)
        if cache_file:
            cache_data = {
                'timestamp': compact_report['timestamp'],
                'symbols': list(per_symbol_cache.keys()),
                'skipped_symbols': skipped_symbols,
                'all_news': sorted_by_impact,
                'per_symbol': per_symbol_cache,
            }
            from pathlib import Path
            Path(cache_file).parent.mkdir(parents=True, exist_ok=True)
            with open(cache_file, 'w') as f:
                json.dump(cache_data, f, indent=2, default=str)
            logger.info(f"Full news cache saved to {cache_file}")

        # Phase 9: Apply guardrails based on deployment mode
        if _features_available:
            try:
                mode_str = get_deployment_mode()
                mode = DeploymentMode(mode_str)
                enforcer = GuardrailEnforcer(mode)

                # Apply appropriate disclaimer based on mode
                news_text = json.dumps(compact_report, indent=2, default=str)
                enforcer.add_professional_disclaimer(news_text)
                logger.info(f"Applied {mode_str} guardrails and disclaimers")
            except Exception as e:
                logger.warning(f"Could not apply mode-specific guardrails: {e}")

        if output_file:
            compact_for_file = dict(compact_report)
            compact_for_file['output_file'] = output_file
            with open(output_file, 'w') as f:
                json.dump(serialize_news_compact(compact_for_file), f, indent=2, default=str)
            logger.info(f"Compact news digest saved to {output_file}")

        return compact_report

    def fetch_symbol_news_detail(self, symbol: str, cache_file: str) -> Optional[List[Dict]]:
        """Return full article list for a single symbol from the news cache.

        Used for on-demand per-symbol lookups without re-fetching everything.
        Returns None if symbol not in cache (caller should re-fetch).
        """
        from pathlib import Path
        path = Path(cache_file).expanduser()
        if not path.exists():
            return None
        try:
            with open(path) as f:
                cache = json.load(f)
            per_symbol = cache.get('per_symbol', {})
            if symbol in per_symbol:
                return per_symbol[symbol]
            # Symbol was in skipped_symbols — not in cache
            if symbol in cache.get('skipped_symbols', []):
                logger.info(f"{symbol} was skipped at fetch time — fetching now")
                # Load holdings to get portfolio context for impact calculation
                return None  # Caller must do a live fetch
            return None
        except Exception as e:
            logger.error(f"Error reading cache: {e}")
            return None

if __name__ == '__main__':
    import argparse
    from pathlib import Path

    parser = argparse.ArgumentParser(description='Fetch portfolio news')
    parser.add_argument('holdings_file', help='Path to holdings.json')
    parser.add_argument('output_file', nargs='?', help='Path for compact digest output (default: portfolio_news.json alongside holdings)')
    parser.add_argument('--symbol', '-s', help='On-demand: fetch full articles for this symbol only')
    parser.add_argument('--top-n', type=int, default=None,
                        help='Fetch news for top N holdings by value. '
                             'If omitted, the adaptive planner chooses automatically.')
    parser.add_argument('--model', '-m', default=None,
                        help='Model ID for adaptive planning (default: OPENCLAW_MODEL env)')
    parser.add_argument('--cache', help='Path for full article cache (default: portfolio_news_cache.json alongside output)')
    parser.add_argument('--verbose', '-v', action='store_true',
                        help='Print narrative, macro themes, and top movers (default: compact summary only)')
    args = parser.parse_args()

    holdings_path = Path(args.holdings_file).expanduser()
    reports_dir = holdings_path.parent

    output_file = args.output_file or str(reports_dir / 'portfolio_news.json')
    cache_file = args.cache or str(reports_dir / 'portfolio_news_cache.json')

    # Auto-plan: if --top-n not given, run the adaptive planner
    top_n = args.top_n
    if top_n is None:
        try:
            from news_fetch_planner import NewsFetchPlanner
            plan = NewsFetchPlanner.make_plan_from_holdings_file(
                str(holdings_path), model_id=args.model
            )
            top_n = plan.recommended_top_n
            logger.info(
                f"Adaptive plan: top_n={top_n}, coverage={plan.coverage_pct}%, "
                f"~{plan.estimated_news_tokens:,} tokens — {plan.reason}"
            )
            # Save plan alongside digest for agent visibility
            plan_file = str(reports_dir / 'portfolio_news_plan.json')
            with open(plan_file, 'w') as _pf:
                json.dump(plan.to_dict(), _pf, indent=2)
        except Exception as e:
            logger.warning(f"Adaptive planner unavailable ({e}), using default top_n=30")
            top_n = 30

    analyzer = PortfolioNewsAnalyzer()

    # On-demand single-symbol mode
    if args.symbol:
        symbol = args.symbol.upper()
        items = analyzer.fetch_symbol_news_detail(symbol, cache_file)
        if items is None:
            # Not in cache — live fetch (load holdings for impact calculation)
            analyzer.load_holdings(str(holdings_path))
            if symbol not in analyzer.portfolio_holdings:
                print(f"⚠️  {symbol} not found in portfolio holdings.")
                sys.exit(1)
            items = analyzer.fetch_symbol_news(symbol)
        print(f"\n{'='*60}")
        print(f"NEWS FOR {symbol} ({len(items)} articles)")
        print('='*60)
        for item in items:
            print(f"\n📰 {item['title']}")
            if item.get('summary'):
                print(f"   {item['summary'][:300]}")
            print(f"   Sentiment: {item['sentiment']} ({item['confidence']:.0%}) | "
                  f"Impact: ${item['portfolio_impact']:+,.0f}")
        sys.exit(0)

    report = analyzer.fetch_all_news(
        str(holdings_path),
        output_file=output_file,
        top_n=top_n,
        cache_file=cache_file,
    )

    # Emit compact JSON to stdout for LLM (full digest is in portfolio_news.json — do not read it)
    report['output_file'] = output_file or ""
    print(json.dumps(serialize_news_compact(report), separators=(',', ':'), default=str))

    if args.verbose:
        # Narrative
        if narr:
            print(f"\nPortfolio Posture: {posture}")
            print(f"  {narr.get('narrative', '')}")
            for tw in narr.get('key_tailwinds', []):
                print(f"  + {tw}")
            for risk in narr.get('key_risks', []):
                print(f"  - {risk}")

        # Macro themes
        themes_data = report.get('macro_themes')
        if themes_data and themes_data.get('themes'):
            print("\nMACRO THEMES")
            for t in themes_data['themes']:
                arrow = "^" if t['direction'] == 'bullish' else ("v" if t['direction'] == 'bearish' else "-")
                syms = ", ".join(t['affected_symbols'][:6])
                print(f"  {arrow} {t['theme']} ({t['portfolio_weight_pct']:.1f}%) — {syms}")

        # Top movers
        print("\nTOP POSITIVE NEWS")
        for item in report['top_positive_movers'][:3]:
            print(f"  {item['symbol']}: {item['title'][:70]} | +${item['portfolio_impact']:,.0f}")
        print("TOP NEGATIVE NEWS")
        for item in report['top_negative_movers'][:3]:
            print(f"  {item['symbol']}: {item['title'][:70]} | ${item['portfolio_impact']:,.0f}")
