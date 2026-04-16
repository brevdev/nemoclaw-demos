#!/usr/bin/env python3
"""
Multi-provider financial data abstraction for InvestorClaw.

Supported providers:
  finnhub    - Finnhub.io: quotes, historical candles, company news, analyst ratings
  yfinance   - Yahoo Finance (unofficial): batch quotes, historical, news, analyst
  newsapi    - NewsAPI.org: news headlines only (no price data)
  massive    - Massive (polygon.io-compatible): quotes, historical, news

Provider priority is resolved at runtime from INVESTORCLAW_PRICE_PROVIDER env var
or passed explicitly to PriceProvider(primary=...).

All methods return plain dicts / lists of dicts — no pandas, no external types.
"""

import os
import time
import logging
import requests
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ─── .env loader (no external dependency) ────────────────────────────────────

def _load_env(env_file: Optional[str] = None) -> None:
    """Load .env from skill directory if not already in environment."""
    if env_file is None:
        env_file = str(Path(__file__).parent.parent / ".env")
    path = Path(env_file)
    if not path.exists():
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, val = line.partition('=')
            key = key.strip()
            val = val.strip().strip('"').strip("'")
            if key and val and key not in os.environ:
                os.environ[key] = val

_load_env()

# ─── Rate limiter ─────────────────────────────────────────────────────────────

class _RateLimiter:
    def __init__(self, calls_per_minute: int):
        self._interval = 60.0 / max(calls_per_minute, 1)
        self._last = 0.0

    def wait(self) -> None:
        elapsed = time.monotonic() - self._last
        if elapsed < self._interval:
            time.sleep(self._interval - elapsed)
        self._last = time.monotonic()


# ─── Provider implementations ─────────────────────────────────────────────────

class FinnhubProvider:
    """
    Finnhub.io REST API provider.
    Free tier: 60 calls/minute.
    Docs: https://finnhub.io/docs/api
    """
    BASE = "https://finnhub.io/api/v1"
    NAME = "finnhub"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("FINNHUB_KEY") or os.getenv("FINNHUB_API_KEY")
        if not self.api_key:
            raise ValueError("FINNHUB_KEY not set")
        self._rl = _RateLimiter(55)  # stay under 60/min limit
        self._session = requests.Session()
        self._session.headers["X-Finnhub-Token"] = self.api_key

    def _get(self, path: str, params: dict = None, timeout: int = 10) -> Optional[dict]:
        self._rl.wait()
        try:
            r = self._session.get(f"{self.BASE}{path}", params=params or {}, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"Finnhub {path}: {e}")
            return None

    def get_quote(self, symbol: str) -> Optional[Dict]:
        """Current quote. Returns dict with price, change, pct_change, high, low, open, prev_close."""
        data = self._get("/quote", {"symbol": symbol})
        if not data or data.get("c", 0) == 0:
            return None
        return {
            "symbol":     symbol,
            "price":      data["c"],
            "change":     data["d"],
            "pct_change": data["dp"],
            "high":       data["h"],
            "low":        data["l"],
            "open":       data["o"],
            "prev_close": data["pc"],
            "provider":   self.NAME,
        }

    def get_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """Batch quotes — Finnhub has no batch endpoint, calls sequentially with rate limiting."""
        results = {}
        for sym in symbols:
            q = self.get_quote(sym)
            if q:
                results[sym] = q
        return results

    def get_history(self, symbol: str, days: int = 365) -> List[Dict]:
        """
        Daily OHLCV candles for the past N days.
        NOTE: Finnhub /stock/candle requires a Premium plan (returns 403 on free tier).
        This method will return [] on free tier — Alpha Vantage or yfinance are preferred
        for historical data via the PriceProvider routing logic.
        """
        to_ts   = int(datetime.now().timestamp())
        from_ts = int((datetime.now() - timedelta(days=days)).timestamp())
        data = self._get("/stock/candle", {
            "symbol":     symbol,
            "resolution": "D",
            "from":       from_ts,
            "to":         to_ts,
        })
        if not data or data.get("s") != "ok":
            return []
        try:
            return [
                {
                    "date":   datetime.fromtimestamp(t).strftime("%Y-%m-%d"),
                    "open":   o, "high": h, "low": l, "close": c, "volume": v,
                    "symbol": symbol, "provider": self.NAME,
                }
                for t, o, h, l, c, v in zip(
                    data["t"], data["o"], data["h"], data["l"], data["c"], data["v"]
                )
            ]
        except (KeyError, TypeError):
            return []

    def get_news(self, symbols: List[str], days: int = 7) -> List[Dict]:
        """Company news for a list of symbols over the past N days."""
        to_date   = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        articles = []
        for sym in symbols:
            data = self._get("/company-news", {
                "symbol": sym, "from": from_date, "to": to_date
            })
            if not data:
                continue
            for item in data[:5]:  # cap at 5 per symbol
                articles.append({
                    "symbol":   sym,
                    "headline": item.get("headline", ""),
                    "summary":  item.get("summary", ""),
                    "source":   item.get("source", ""),
                    "url":      item.get("url", ""),
                    "datetime": datetime.fromtimestamp(item.get("datetime", 0)).strftime("%Y-%m-%d %H:%M"),
                    "provider": self.NAME,
                })
        return articles

    def get_analyst_ratings(self, symbols: List[str]) -> Dict[str, Dict]:
        """Latest analyst consensus recommendation for each symbol."""
        results = {}
        for sym in symbols:
            data = self._get("/stock/recommendation", {"symbol": sym})
            if not data or not isinstance(data, list) or len(data) == 0:
                continue
            latest = data[0]
            total = sum([
                latest.get("strongBuy", 0), latest.get("buy", 0),
                latest.get("hold", 0), latest.get("sell", 0),
                latest.get("strongSell", 0),
            ])
            results[sym] = {
                "symbol":      sym,
                "period":      latest.get("period", ""),
                "strong_buy":  latest.get("strongBuy", 0),
                "buy":         latest.get("buy", 0),
                "hold":        latest.get("hold", 0),
                "sell":        latest.get("sell", 0),
                "strong_sell": latest.get("strongSell", 0),
                "total":       total,
                "provider":    self.NAME,
            }
        return results


class YFinanceProvider:
    """
    Yahoo Finance via yfinance (unofficial, no API key).
    Fastest for batch quote downloads but rate-limited and non-deterministic.
    """
    NAME = "yfinance"

    def __init__(self):
        import yfinance as yf
        self._yf = yf

    @staticmethod
    def _yf_symbol(sym: str) -> str:
        """Convert broker symbols to yfinance format (BRK.B → BRK-B)."""
        return sym.replace(".", "-")

    def get_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """Batch quote download — one HTTP call for all symbols."""
        if not symbols:
            return {}
        # Build yf_symbol → original symbol reverse map
        yf_syms = [self._yf_symbol(s) for s in symbols]
        reverse = {self._yf_symbol(s): s for s in symbols}
        try:
            data = self._yf.download(
                yf_syms if len(yf_syms) > 1 else yf_syms[0],
                period="1d", progress=False, auto_adjust=True,
            )
            results = {}
            if data.empty:
                return {}

            if len(yf_syms) == 1:
                yf_sym = yf_syms[0]
                orig   = reverse[yf_sym]
                row = data.iloc[-1]
                close_val = row.get("Close", row.get("close", 0))
                if hasattr(close_val, "iloc"):
                    close_val = close_val.iloc[0] if len(close_val) > 0 else 0
                results[orig] = {
                    "symbol":   orig,
                    "price":    float(close_val),
                    "provider": self.NAME,
                }
            else:
                close = data["Close"] if "Close" in data.columns else data["close"]
                for yf_sym in yf_syms:
                    orig = reverse[yf_sym]
                    if yf_sym in close.columns and not close[yf_sym].isna().all():
                        price = float(close[yf_sym].dropna().iloc[-1])
                        results[orig] = {"symbol": orig, "price": price, "provider": self.NAME}
            return results
        except Exception as e:
            logger.warning(f"yfinance batch quotes: {e}")
            return {}

    def get_quote(self, symbol: str) -> Optional[Dict]:
        r = self.get_quotes([symbol])
        return r.get(symbol)

    def get_history(self, symbol: str, days: int = 365) -> List[Dict]:
        """Historical daily OHLCV."""
        try:
            t = self._yf.Ticker(self._yf_symbol(symbol))
            period = "1y" if days <= 365 else "2y"
            hist = t.history(period=period)
            if hist.empty:
                return []
            hist = hist.reset_index()
            return [
                {
                    "date":   str(row["Date"])[:10],
                    "open":   float(row["Open"]),
                    "high":   float(row["High"]),
                    "low":    float(row["Low"]),
                    "close":  float(row["Close"]),
                    "volume": int(row["Volume"]),
                    "symbol": symbol,
                    "provider": self.NAME,
                }
                for _, row in hist.iterrows()
            ]
        except Exception as e:
            logger.warning(f"yfinance history {symbol}: {e}")
            return []

    def get_news(self, symbols: List[str], days: int = 7) -> List[Dict]:
        """News via yfinance Ticker.news."""
        articles = []
        for sym in symbols:
            try:
                t = self._yf.Ticker(self._yf_symbol(sym))
                for item in (t.news or [])[:5]:
                    articles.append({
                        "symbol":   sym,
                        "headline": item.get("title", ""),
                        "summary":  item.get("summary", ""),
                        "source":   item.get("publisher", ""),
                        "url":      item.get("link", ""),
                        "datetime": datetime.fromtimestamp(
                            item.get("providerPublishTime", 0)
                        ).strftime("%Y-%m-%d %H:%M"),
                        "provider": self.NAME,
                    })
            except Exception as e:
                logger.warning(f"yfinance news {sym}: {e}")
        return articles

    def get_analyst_ratings(self, symbols: List[str]) -> Dict[str, Dict]:
        results = {}
        for sym in symbols:
            try:
                t = self._yf.Ticker(self._yf_symbol(sym))
                rec = t.recommendations
                if rec is None or rec.empty:
                    continue
                latest = rec.iloc[-1]
                results[sym] = {
                    "symbol":    sym,
                    "period":    str(rec.index[-1])[:10],
                    "consensus": str(latest.get("To Grade", latest.get("Action", ""))),
                    "firm":      str(latest.get("Firm", "")),
                    "provider":  self.NAME,
                }
            except Exception as e:
                logger.warning(f"yfinance analyst {sym}: {e}")
        return results


class NewsAPIProvider:
    """
    NewsAPI.org — news headlines and sentiment only.
    Free tier: 100 requests/day. No price data.
    """
    BASE = "https://newsapi.org/v2"
    NAME = "newsapi"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("NEWSAPI_KEY")
        if not self.api_key:
            raise ValueError("NEWSAPI_KEY not set")
        self._rl = _RateLimiter(30)  # conservative: 30/min

    def _get(self, path: str, params: dict = None) -> Optional[dict]:
        self._rl.wait()
        try:
            params = params or {}
            params["apiKey"] = self.api_key
            r = requests.get(f"{self.BASE}{path}", params=params, timeout=10)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"NewsAPI {path}: {e}")
            return None

    def get_news(self, symbols: List[str], days: int = 7) -> List[Dict]:
        """News headlines for a list of ticker symbols."""
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        articles = []
        # Query in batches of 5 symbols to minimise API calls
        for i in range(0, len(symbols), 5):
            batch = symbols[i:i + 5]
            q = " OR ".join(batch)
            data = self._get("/everything", {
                "q":          q,
                "from":       from_date,
                "sortBy":     "publishedAt",
                "language":   "en",
                "pageSize":   20,
            })
            if not data or data.get("status") != "ok":
                continue
            for item in data.get("articles", []):
                # Try to associate article with a symbol
                title = (item.get("title") or "").upper()
                matched = next((s for s in batch if s in title), batch[0])
                articles.append({
                    "symbol":   matched,
                    "headline": item.get("title", ""),
                    "summary":  item.get("description", ""),
                    "source":   item.get("source", {}).get("name", ""),
                    "url":      item.get("url", ""),
                    "datetime": (item.get("publishedAt") or "")[:16].replace("T", " "),
                    "provider": self.NAME,
                })
        return articles

    # NewsAPI does not provide price data
    def get_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        raise NotImplementedError("NewsAPI does not provide price data")

    def get_history(self, symbol: str, days: int = 365) -> List[Dict]:
        raise NotImplementedError("NewsAPI does not provide price data")

    def get_analyst_ratings(self, symbols: List[str]) -> Dict[str, Dict]:
        raise NotImplementedError("NewsAPI does not provide analyst ratings")


class MassiveProvider:
    """
    Massive (polygon.io-compatible) market data provider.
    Starter plan: real-time quotes, full OHLCV history, news.
    Docs: https://polygon.io/docs/stocks
    """
    BASE = "https://api.polygon.io"
    NAME = "massive"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("MASSIVE_API_KEY") or os.getenv("POLYGON_API_KEY")
        if not self.api_key:
            raise ValueError("MASSIVE_API_KEY / POLYGON_API_KEY not set")
        self._rl = _RateLimiter(100)  # Starter+ plan; free tier was 5/min

    def _get(self, path: str, params: dict = None) -> Optional[dict]:
        self._rl.wait()
        try:
            params = params or {}
            params["apiKey"] = self.api_key
            r = requests.get(f"{self.BASE}{path}", params=params, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            logger.warning(f"Polygon {path}: {e}")
            return None

    def get_quote(self, symbol: str) -> Optional[Dict]:
        """Previous-day close (free tier)."""
        data = self._get(f"/v2/aggs/ticker/{symbol}/prev")
        if not data or not data.get("results"):
            return None
        r = data["results"][0]
        return {
            "symbol":   symbol,
            "price":    r["c"],
            "open":     r["o"],
            "high":     r["h"],
            "low":      r["l"],
            "volume":   r["v"],
            "date":     datetime.fromtimestamp(r["t"] / 1000).strftime("%Y-%m-%d"),
            "provider": self.NAME,
        }

    def get_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Batch quotes via snapshot endpoint (Starter+ plan) or prev-day individual calls.
        Starter+ plan uses batch snapshot; free tier snapshot returns 403 → individual fallback.
        """
        # Try batch snapshot (requires paid plan)
        joined = ",".join(symbols)
        data = self._get(
            "/v2/snapshot/locale/us/markets/stocks/tickers",
            {"tickers": joined},
        )
        if data and data.get("tickers"):
            results = {}
            for t in data["tickers"]:
                day = t.get("day", {})
                results[t["ticker"]] = {
                    "symbol":   t["ticker"],
                    "price":    day.get("c") or t.get("lastTrade", {}).get("p", 0),
                    "open":     day.get("o", 0),
                    "high":     day.get("h", 0),
                    "low":      day.get("l", 0),
                    "volume":   day.get("v", 0),
                    "provider": self.NAME,
                }
            return results
        # Free-tier fallback: sequential individual prev-day calls (5/min rate-limited)
        logger.info(f"Polygon batch snapshot unavailable; falling back to individual prev-day for {len(symbols)} symbols")
        results = {}
        for sym in symbols:
            q = self.get_quote(sym)
            if q:
                results[sym] = q
        return results

    def get_history(self, symbol: str, days: int = 365) -> List[Dict]:
        """Daily OHLCV aggregates."""
        to_date   = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        data = self._get(
            f"/v2/aggs/ticker/{symbol}/range/1/day/{from_date}/{to_date}",
            {"limit": days, "sort": "asc"},
        )
        if not data or not data.get("results"):
            return []
        return [
            {
                "date":   datetime.fromtimestamp(r["t"] / 1000).strftime("%Y-%m-%d"),
                "open":   r["o"], "high": r["h"], "low": r["l"],
                "close":  r["c"], "volume": r["v"],
                "symbol": symbol, "provider": self.NAME,
            }
            for r in data["results"]
        ]

    def get_news(self, symbols: List[str], days: int = 7) -> List[Dict]:
        """Polygon news API."""
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        articles = []
        for sym in symbols:
            data = self._get("/v2/reference/news", {
                "ticker": sym, "published_utc.gte": from_date, "limit": 5
            })
            if not data or not data.get("results"):
                continue
            for item in data["results"]:
                articles.append({
                    "symbol":   sym,
                    "headline": item.get("title", ""),
                    "summary":  item.get("description", ""),
                    "source":   item.get("publisher", {}).get("name", ""),
                    "url":      item.get("article_url", ""),
                    "datetime": (item.get("published_utc") or "")[:16].replace("T", " "),
                    "provider": self.NAME,
                })
        return articles

    def get_analyst_ratings(self, symbols: List[str]) -> Dict[str, Dict]:
        raise NotImplementedError("Massive/Polygon does not provide analyst recommendations — use Finnhub or yfinance")


class AlphaVantageProvider:
    """
    Alpha Vantage REST API provider.
    Free tier: 25 requests/day (500/day with free key registration).
    Docs: https://www.alphavantage.co/documentation/
    """
    BASE = "https://www.alphavantage.co/query"
    NAME = "alpha_vantage"

    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("ALPHA_VANTAGE_KEY")
        if not self.api_key:
            raise ValueError("ALPHA_VANTAGE_KEY not set")
        # Free tier: 5 calls/minute, 500/day
        self._rl = _RateLimiter(4)
        self._session = requests.Session()

    def _get(self, params: dict, timeout: int = 15) -> Optional[dict]:
        self._rl.wait()
        try:
            params["apikey"] = self.api_key
            r = self._session.get(self.BASE, params=params, timeout=timeout)
            r.raise_for_status()
            data = r.json()
            # AV returns {"Information": "..."} on rate-limit or bad key
            if "Information" in data or "Note" in data:
                msg = data.get("Information") or data.get("Note", "")
                logger.warning(f"AlphaVantage API message: {msg[:120]}")
                return None
            return data
        except Exception as e:
            logger.warning(f"AlphaVantage: {e}")
            return None

    def get_quote(self, symbol: str) -> Optional[Dict]:
        """Global Quote endpoint — current price."""
        data = self._get({"function": "GLOBAL_QUOTE", "symbol": symbol})
        if not data:
            return None
        q = data.get("Global Quote", {})
        price_str = q.get("05. price", "0")
        try:
            price = float(price_str)
        except ValueError:
            return None
        if price == 0:
            return None
        return {
            "symbol":     symbol,
            "price":      price,
            "change":     float(q.get("09. change", 0) or 0),
            "pct_change": float((q.get("10. change percent", "0%") or "0%").replace("%", "") or 0),
            "high":       float(q.get("03. high", 0) or 0),
            "low":        float(q.get("04. low", 0) or 0),
            "open":       float(q.get("02. open", 0) or 0),
            "prev_close": float(q.get("08. previous close", 0) or 0),
            "volume":     int(q.get("06. volume", 0) or 0),
            "provider":   self.NAME,
        }

    def get_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """Sequential quotes (no batch endpoint on free tier)."""
        results = {}
        for sym in symbols:
            q = self.get_quote(sym)
            if q:
                results[sym] = q
        return results

    def get_history(self, symbol: str, days: int = 365) -> List[Dict]:
        """Daily adjusted time series."""
        output_size = "full" if days > 100 else "compact"
        data = self._get({
            "function":    "TIME_SERIES_DAILY_ADJUSTED",
            "symbol":      symbol,
            "outputsize":  output_size,
        })
        if not data:
            return []
        ts = data.get("Time Series (Daily)", {})
        cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        results = []
        for date_str in sorted(ts.keys(), reverse=True):
            if date_str < cutoff:
                break
            row = ts[date_str]
            results.append({
                "date":   date_str,
                "open":   float(row.get("1. open", 0) or 0),
                "high":   float(row.get("2. high", 0) or 0),
                "low":    float(row.get("3. low", 0) or 0),
                "close":  float(row.get("5. adjusted close", row.get("4. close", 0)) or 0),
                "volume": int(row.get("6. volume", 0) or 0),
                "symbol": symbol,
                "provider": self.NAME,
            })
        return results

    def get_news(self, symbols: List[str], days: int = 7) -> List[Dict]:
        """News sentiment endpoint (requires paid plan for most content)."""
        tickers = ",".join(symbols[:5])
        data = self._get({
            "function": "NEWS_SENTIMENT",
            "tickers":  tickers,
            "limit":    20,
        })
        if not data or "feed" not in data:
            return []
        articles = []
        for item in data["feed"]:
            ticker_sentiment = item.get("ticker_sentiment", [{}])
            sym = ticker_sentiment[0].get("ticker", symbols[0]) if ticker_sentiment else symbols[0]
            articles.append({
                "symbol":   sym,
                "headline": item.get("title", ""),
                "summary":  item.get("summary", ""),
                "source":   item.get("source", ""),
                "url":      item.get("url", ""),
                "datetime": (item.get("time_published") or "")[:16].replace("T", " "),
                "provider": self.NAME,
            })
        return articles

    def get_analyst_ratings(self, symbols: List[str]) -> Dict[str, Dict]:
        """Earnings estimates used as proxy for analyst coverage."""
        results = {}
        for sym in symbols:
            data = self._get({"function": "EARNINGS", "symbol": sym})
            if not data or "annualEarnings" not in data:
                continue
            annual = data["annualEarnings"]
            if not annual:
                continue
            # AV free tier doesn't provide buy/sell ratings; note coverage
            results[sym] = {
                "symbol":    sym,
                "period":    annual[0].get("fiscalDateEnding", ""),
                "consensus": "covered",
                "provider":  self.NAME,
            }
        return results


# Backwards-compat alias
PolygonProvider = MassiveProvider

# ─── Unified PriceProvider facade ─────────────────────────────────────────────

PROVIDER_CLASSES = {
    "finnhub":       FinnhubProvider,
    "yfinance":      YFinanceProvider,
    "newsapi":       NewsAPIProvider,
    "massive":       MassiveProvider,
    "polygon":       MassiveProvider,  # backwards-compat alias
    "alpha_vantage": AlphaVantageProvider,
}


def _build_provider(name: str):
    cls = PROVIDER_CLASSES.get(name)
    if cls is None:
        raise ValueError(f"Unknown provider: {name!r}. Valid: {list(PROVIDER_CLASSES)}")
    try:
        return cls()
    except (ValueError, ImportError) as e:
        logger.warning(f"Cannot initialise {name}: {e}")
        return None


class PriceProvider:
    """
    Data-type-aware, quota-sharding financial data provider facade.

    Different operation types are routed to optimal providers:
      quotes     → yfinance (1 batch call, no quota) → Massive (1 batch call, Starter+)
                   → Finnhub (sequential, 60/min, no daily limit)
      history    → Alpha Vantage (adjusted close, 500/day) → Finnhub (candles, unlimited)
                   → yfinance
      news       → NewsAPI (broad, 100/day) + Finnhub (company-specific) — AGGREGATED
      analyst    → Finnhub (recommendations, unlimited) → yfinance

    For large portfolios, quotes are sharded across providers respecting daily quotas:
      INVESTORCLAW_QUOTA_ALPHAVANTAGE=500   (default, adjust if on paid plan)
      INVESTORCLAW_QUOTA_NEWSAPI=100

    Override routing via env vars:
      INVESTORCLAW_PRICE_PROVIDER=auto|finnhub|yfinance|massive|polygon|alpha_vantage
      INVESTORCLAW_FALLBACK_CHAIN=yfinance,massive  (comma-separated)
    """

    # Per-provider daily call budgets (free tier defaults)
    _DEFAULT_QUOTAS: Dict[str, int] = {
        "finnhub":       999_999,   # no daily limit; rate-limited at 60/min
        "yfinance":      999_999,   # no limit; batch-friendly
        "massive":       999_999,   # no explicit daily limit on Starter+
        "polygon":       999_999,   # backwards-compat alias
        "alpha_vantage": 500,       # 500/day with free key
        "newsapi":       100,       # 100/day free tier
    }

    # Preferred provider order per operation type (first available wins)
    _OP_ROUTING: Dict[str, List[str]] = {
        "quotes":   ["yfinance", "massive", "finnhub"],
        "history":  ["alpha_vantage", "finnhub", "yfinance"],
        "news":     ["newsapi", "finnhub"],         # both used; results aggregated
        "analyst":  ["finnhub", "yfinance"],
    }

    def __init__(
        self,
        primary: Optional[str] = None,
        fallback: Optional[List[str]] = None,
    ):
        # If INVESTORCLAW_PRICE_PROVIDER is set to a specific provider, override routing
        self._override = os.getenv("INVESTORCLAW_PRICE_PROVIDER", "auto")
        if self._override == "auto":
            self._override = None

        # Fallback chain (only used when override is set)
        self._fallback_names = [
            f.strip() for f in
            os.getenv("INVESTORCLAW_FALLBACK_CHAIN", "").split(",")
            if f.strip()
        ]
        if primary:
            self._override = primary
        if fallback:
            self._fallback_names = fallback

        # Build provider pool — only instantiate available ones
        self._pool: Dict[str, object] = {}
        for name in list(PROVIDER_CLASSES.keys()):
            p = _build_provider(name)
            if p is not None:
                self._pool[name] = p

        # Read per-provider quotas from env (allow override for paid plans)
        self._quotas = dict(self._DEFAULT_QUOTAS)
        for name in self._pool:
            env_key = f"INVESTORCLAW_QUOTA_{name.upper()}"
            env_val = os.getenv(env_key)
            if env_val and env_val.isdigit():
                self._quotas[name] = int(env_val)
        self._quota_used: Dict[str, int] = {k: 0 for k in self._quotas}

        available = list(self._pool.keys())
        logger.info(f"PriceProvider: available={available}, override={self._override or 'routing'}")

    def _providers_for_op(self, op_type: str) -> List:
        """Return ordered list of available provider instances for an operation type."""
        if self._override:
            ordered = [self._override] + self._fallback_names
        else:
            ordered = self._OP_ROUTING.get(op_type, ["yfinance"])
        result = []
        for name in ordered:
            p = self._pool.get(name)
            if p and self._quota_used.get(name, 0) < self._quotas.get(name, 0):
                result.append(p)
        return result

    def _use_quota(self, provider_name: str, calls: int = 1) -> None:
        self._quota_used[provider_name] = self._quota_used.get(provider_name, 0) + calls

    def _try_op(self, op_type: str, method: str, *args, **kwargs):
        """Try each provider in routing order; return first successful non-empty result."""
        for provider in self._providers_for_op(op_type):
            fn = getattr(provider, method, None)
            if fn is None:
                continue
            try:
                result = fn(*args, **kwargs)
                if result:
                    self._use_quota(provider.NAME)
                    return result
            except NotImplementedError:
                pass
            except Exception as e:
                logger.warning(f"{provider.NAME}.{method} failed: {e}")
        empty: Dict = {}
        return empty if method in ("get_quotes", "get_analyst_ratings") else []

    # ── Public API ────────────────────────────────────────────────────────────

    def get_quote(self, symbol: str) -> Optional[Dict]:
        """Current price for a single symbol. Routes to quotes providers."""
        result = self._try_op("quotes", "get_quote", symbol)
        return result if result else None

    def get_quotes(self, symbols: List[str]) -> Dict[str, Dict]:
        """
        Batch current prices for all symbols.
        For large portfolios, yfinance fetches all in one call.
        If quota is exhausted on primary, shards remaining symbols to next provider.
        """
        if not symbols:
            return {}

        # Defensive: strip None/empty values that can arrive from sparse portfolios
        remaining = [s for s in symbols if s is not None and str(s).strip()]
        results: Dict[str, Dict] = {}

        for provider in self._providers_for_op("quotes"):
            if not remaining:
                break
            fn = getattr(provider, "get_quotes", None)
            if fn is None:
                continue
            try:
                batch = fn(remaining)
                if batch:
                    results.update(batch)
                    self._use_quota(provider.NAME)
                    # Symbols not returned = missing from this provider
                    remaining = [s for s in remaining if s not in results]
            except NotImplementedError:
                pass
            except Exception as e:
                logger.warning(f"{provider.NAME}.get_quotes({len(remaining)} syms) failed: {e}")

        if remaining:
            logger.warning(f"get_quotes: no price data for {len(remaining)} symbols: "
                           f"{remaining[:5]}{'...' if len(remaining) > 5 else ''}")
        return results

    def get_history(self, symbol: str, days: int = 365) -> List[Dict]:
        """Daily OHLCV history. Routes to history-optimized providers (Alpha Vantage → Finnhub)."""
        return self._try_op("history", "get_history", symbol, days=days)

    def get_news(self, symbols: List[str], days: int = 7) -> List[Dict]:
        """
        News headlines. Aggregates from NewsAPI AND Finnhub for maximum coverage.
        Deduplicates by URL.
        """
        articles: List[Dict] = []
        seen_urls: set = set()
        for provider in self._providers_for_op("news"):
            fn = getattr(provider, "get_news", None)
            if fn is None:
                continue
            try:
                for a in fn(symbols, days=days):
                    url = a.get("url", "")
                    if url and url not in seen_urls:
                        seen_urls.add(url)
                        articles.append(a)
                self._use_quota(provider.NAME)
            except (NotImplementedError, Exception) as e:
                logger.warning(f"{provider.NAME}.get_news failed: {e}")
        return articles

    def get_analyst_ratings(self, symbols: List[str]) -> Dict[str, Dict]:
        """Analyst consensus. Routes to Finnhub first (has recommendations endpoint)."""
        return self._try_op("analyst", "get_analyst_ratings", symbols)

    def quota_status(self) -> Dict[str, Dict]:
        """Return quota used/remaining per provider (useful for diagnostics)."""
        return {
            name: {
                "used":      self._quota_used.get(name, 0),
                "limit":     self._quotas.get(name, 0),
                "remaining": self._quotas.get(name, 0) - self._quota_used.get(name, 0),
                "available": name in self._pool,
            }
            for name in self._DEFAULT_QUOTAS
        }

    @property
    def primary_name(self) -> str:
        """Name of the primary quote provider (for diagnostics)."""
        return (self._override or self._OP_ROUTING.get("quotes", ["yfinance"])[0])


# ─── Portfolio update priority engine ────────────────────────────────────────

class PortfolioUpdatePriority:
    """
    Tiers holdings by portfolio weight so high-impact positions get more
    frequent, higher-fidelity price updates while the tail is refreshed cheaply.

    Tier assignment (by cumulative portfolio weight):
      Tier 1 — Core      : Top N positions covering ~50% of portfolio value
                           → real-time provider (Finnhub), short TTL (15 min)
      Tier 2 — Major     : Next positions covering 50-80% of portfolio value
                           → batch provider (yfinance), medium TTL (30 min)
      Tier 3 — Standard  : Remaining (<20% coverage, many small positions)
                           → batch provider (yfinance), session TTL (60 min)

    Usage:
        import polars as pl
        from price_provider import PortfolioUpdatePriority, PriceProvider

        df = ...  # Polars DataFrame with 'symbol', 'market_value' columns

        priority = PortfolioUpdatePriority(df)
        print(priority.summary())

        provider = PriceProvider()
        # Refresh core positions with real-time quotes
        core_quotes = provider.get_quotes(priority.tier1_symbols)
        # Refresh the rest with batch
        batch_quotes = provider.get_quotes(priority.tier2_symbols + priority.tier3_symbols)
    """

    def __init__(
        self,
        portfolio_df,
        core_pct: float  = 0.50,
        major_pct: float = 0.80,
        symbol_col: str  = "symbol",
        value_col: str   = "market_value",
    ):
        """
        Args:
            portfolio_df : Polars DataFrame with symbol and market_value columns
            core_pct     : cumulative weight threshold for Tier 1 (default 50%)
            major_pct    : cumulative weight threshold for Tier 2 (default 80%)
            symbol_col   : name of the symbol column
            value_col    : name of the market value column
        """
        try:
            import polars as pl
        except ImportError:
            raise ImportError("polars is required for PortfolioUpdatePriority")

        self.core_pct  = core_pct
        self.major_pct = major_pct

        # Filter to equities with a valid symbol and positive value
        df = portfolio_df.filter(
            pl.col(symbol_col).is_not_null() &
            pl.col(value_col).is_not_null() &
            (pl.col(value_col) > 0)
        )

        if len(df) == 0:
            self.tier1_symbols: List[str] = []
            self.tier2_symbols: List[str] = []
            self.tier3_symbols: List[str] = []
            self._tiers: List[Dict] = []
            return

        total = df[value_col].sum()

        # Sort descending by value, compute weight and cumulative weight
        df = (
            df
            .sort(value_col, descending=True)
            .with_columns(
                (pl.col(value_col) / total).alias("weight_pct"),
            )
            .with_columns(
                pl.col("weight_pct").cum_sum().alias("cum_weight_pct"),
            )
        )

        def _assign_tier(cum_w: float) -> int:
            if cum_w <= core_pct:
                return 1
            if cum_w <= major_pct:
                return 2
            return 3

        # Assign tier per row — using Python-level iteration on the small metadata frame
        tiers   = [_assign_tier(float(cw)) for cw in df["cum_weight_pct"].to_list()]
        symbols = df[symbol_col].to_list()
        values  = df[value_col].to_list()
        weights = df["weight_pct"].to_list()

        self._tiers: List[Dict] = [
            {
                "symbol":      symbols[i],
                "market_value": float(values[i]),
                "weight_pct":  round(float(weights[i]) * 100, 2),
                "tier":        tiers[i],
            }
            for i in range(len(symbols))
        ]

        self.tier1_symbols = [r["symbol"] for r in self._tiers if r["tier"] == 1]
        self.tier2_symbols = [r["symbol"] for r in self._tiers if r["tier"] == 2]
        self.tier3_symbols = [r["symbol"] for r in self._tiers if r["tier"] == 3]

    # ── Recommended refresh configuration per tier ───────────────────────────

    @property
    def tier_config(self) -> Dict[int, Dict]:
        """
        Returns recommended refresh settings per tier.

        Provider assignments by operation:

          QUOTES (intraday prices):
            Tier 1 (Core)     → finnhub      : real-time, 60/min; one call per symbol
            Tier 2 (Major)    → yfinance     : batch, 1 call covers all symbols
            Tier 3 (Standard) → yfinance     : batch, 1 call covers all symbols
            EOD verification  → polygon      : prev-day, 5/min sequential (run once/day)

          HISTORY (performance analysis):
            All tiers         → alpha_vantage: adjusted close, 500/day, 5/min
                                               ideal for performance and backtesting

          NEWS & SENTIMENT:
            All tiers         → newsapi+finnhub (aggregated)
            Sentiment scoring → alpha_vantage (has sentiment_score field)

        Daily quota budget for full portfolio (217 symbols):
          finnhub      : Tier 1 × 15min refreshes × 8h = ~(t1×32) calls/day
          yfinance     : (Tier 2+3) × 2 batches/h × 8h = ~16 batch calls/day
          alpha_vantage: 217 history calls = 217 of your 500/day budget
          polygon      : 217 prev-day calls = 217 calls (1 per day run)
          newsapi      : ~22 batches (5 syms/call × 22 = 110 syms) = ~22 calls/day
        """
        return {
            1: {
                "label":            "Core (top ~50% value)",
                "ttl_minutes":      15,
                "quote_provider":   "finnhub",       # real-time
                "history_provider": "alpha_vantage", # adjusted close
                "news_providers":   ["newsapi", "finnhub"],
                "quota_calls_per_refresh": len(self.tier1_symbols),
                "symbols":          len(self.tier1_symbols),
            },
            2: {
                "label":            "Major (50-80% value)",
                "ttl_minutes":      30,
                "quote_provider":   "yfinance",      # batch
                "history_provider": "alpha_vantage",
                "news_providers":   ["newsapi", "finnhub"],
                "quota_calls_per_refresh": 1,
                "symbols":          len(self.tier2_symbols),
            },
            3: {
                "label":            "Standard (tail <20% value)",
                "ttl_minutes":      60,
                "quote_provider":   "yfinance",      # batch
                "history_provider": "alpha_vantage",
                "news_providers":   ["newsapi"],
                "quota_calls_per_refresh": 1,
                "symbols":          len(self.tier3_symbols),
            },
            0: {
                "label":            "EOD Verification (all positions, once/day)",
                "ttl_minutes":      1440,            # once per day
                "quote_provider":   "massive",       # prev-day cross-check
                "history_provider": None,
                "news_providers":   [],
                "quota_calls_per_refresh": len(self.tier1_symbols)
                                           + len(self.tier2_symbols)
                                           + len(self.tier3_symbols),
                "symbols":          len(self.tier1_symbols)
                                    + len(self.tier2_symbols)
                                    + len(self.tier3_symbols),
            },
        }

    def summary(self) -> str:
        """Human-readable summary of tier breakdown."""
        lines = ["Portfolio Update Priority Tiers", "-" * 40]
        tc = self.tier_config
        sym_map = {
            1: self.tier1_symbols, 2: self.tier2_symbols,
            3: self.tier3_symbols, 0: self.tier1_symbols + self.tier2_symbols + self.tier3_symbols,
        }
        for tier_id in [1, 2, 3, 0]:
            cfg  = tc[tier_id]
            syms = sym_map[tier_id]
            total_val = sum(r["market_value"] for r in self._tiers
                           if r["tier"] == tier_id or tier_id == 0)
            total_wt  = sum(r["weight_pct"]   for r in self._tiers
                           if r["tier"] == tier_id or tier_id == 0)
            qp  = cfg.get("quote_provider", "N/A")
            hp  = cfg.get("history_provider", "N/A")
            lines.append(
                f"\n  Tier {tier_id} [{cfg['label']}]\n"
                f"    Symbols        : {cfg['symbols']}  ({', '.join(syms[:5])}{'...' if len(syms) > 5 else ''})\n"
                f"    Portfolio %    : {total_wt:.1f}%\n"
                f"    Refresh TTL    : every {cfg['ttl_minutes']} min\n"
                f"    Quote provider : {qp}\n"
                f"    Hist provider  : {hp}\n"
                f"    Calls/refresh  : ~{cfg['quota_calls_per_refresh']}"
            )
        return "\n".join(lines)

    def get_refresh_batches(self) -> Dict[int, Dict]:
        """
        Returns {tier: {symbols, provider, ttl_minutes}} dict for the
        calling code to schedule refreshes.
        """
        return {
            1: {"symbols": self.tier1_symbols, **self.tier_config[1]},
            2: {"symbols": self.tier2_symbols, **self.tier_config[2]},
            3: {"symbols": self.tier3_symbols, **self.tier_config[3]},
        }
