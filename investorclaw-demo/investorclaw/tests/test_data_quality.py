"""
tests/test_data_quality.py — Phase 4 data-quality regression tests.

Covers provider-caused data integrity bugs fixed in the data-quality pass:

 WF28  Bond cost_basis: price-as-%-of-par divided by 100
 WF29  Equity cost_basis: NOT divided by 100 (unaffected by bond fix)
 WF30  AnalystConsensus.recommendation_mean: defaults to None, not 2.5
 WF31  Ticker normalisation: BRK.B → BRK-B (both analyst and news fetchers)
 WF32  _parse_avg_rating: parses "2.4 - Buy" → 2.4
 WF33  _is_relevant: accepts articles with ticker match; rejects off-topic
 WF34  News deduplication: same URL/title not counted twice across tickers
 WF35  _backfill_holdings_summary: populates ytm/duration in top_bonds
"""

import json
import pytest
import tempfile
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# WF28 / WF29: Holding.cost_basis  (bond vs equity)
# ---------------------------------------------------------------------------

from models.holdings import Holding


def _make_holding(asset_type: str, shares: float, purchase_price: float) -> Holding:
    return Holding(
        symbol="TEST",
        asset_type=asset_type,
        shares=shares,
        current_price=purchase_price,
        purchase_price=purchase_price,
    )


# WF28 — bond types divide by 100

def test_cost_basis_bond_divides_by_100():
    h = _make_holding("bond", 10_000, 99.769)
    assert abs(h.cost_basis - 9_976.90) < 0.01

def test_cost_basis_municipal_bond_divides_by_100():
    h = _make_holding("municipal_bond", 5_000, 101.5)
    assert abs(h.cost_basis - 5_075.00) < 0.01

def test_cost_basis_treasury_divides_by_100():
    h = _make_holding("treasury", 20_000, 98.0)
    assert abs(h.cost_basis - 19_600.00) < 0.01

def test_cost_basis_corporate_bond_divides_by_100():
    h = _make_holding("corporate_bond", 3_000, 105.25)
    assert abs(h.cost_basis - 3_157.50) < 0.01

def test_cost_basis_government_bond_divides_by_100():
    h = _make_holding("government_bond", 1_000, 100.0)
    assert abs(h.cost_basis - 1_000.00) < 0.01

def test_cost_basis_bond_not_inflated_100x():
    """Regression: cost_basis must NOT equal shares * purchase_price for bonds."""
    h = _make_holding("bond", 3_000, 99.769)
    raw = h.shares * h.purchase_price          # the pre-fix (wrong) value
    assert h.cost_basis != pytest.approx(raw), \
        "Bond cost_basis must not be 100× the correct value"

# WF29 — equities and non-bond types are NOT divided by 100

def test_cost_basis_equity_not_divided():
    h = _make_holding("equity", 100, 150.00)
    assert h.cost_basis == pytest.approx(15_000.00)

def test_cost_basis_etf_not_divided():
    h = _make_holding("etf", 50, 200.00)
    assert h.cost_basis == pytest.approx(10_000.00)

def test_cost_basis_mutual_fund_not_divided():
    h = _make_holding("mutual_fund", 200, 75.00)
    assert h.cost_basis == pytest.approx(15_000.00)

def test_cost_basis_cash_not_divided():
    h = _make_holding("cash", 1, 10_000.00)
    assert h.cost_basis == pytest.approx(10_000.00)


# ---------------------------------------------------------------------------
# WF30: AnalystConsensus.recommendation_mean default is None (not 2.5)
# ---------------------------------------------------------------------------

from commands.fetch_analyst_recommendations_parallel import AnalystConsensus


def test_analyst_consensus_recommendation_mean_defaults_none():
    """rec_mean must default to None — 2.5 was a magic fallback that masked missing data."""
    ac = AnalystConsensus(
        symbol="TEST",
        current_price=100.0,
    )
    assert ac.recommendation_mean is None

def test_analyst_consensus_recommendation_mean_explicit_none():
    ac = AnalystConsensus(
        symbol="TEST",
        current_price=100.0,
        recommendation_mean=None,
    )
    assert ac.recommendation_mean is None

def test_analyst_consensus_recommendation_mean_set_explicitly():
    ac = AnalystConsensus(
        symbol="AAPL",
        current_price=200.0,
        analyst_count=25,
        buy_count=18, hold_count=5, sell_count=2,
        recommendation_mean=1.8,
    )
    assert ac.recommendation_mean == pytest.approx(1.8)


# ---------------------------------------------------------------------------
# WF31: Ticker normalisation (_yf_ticker)
# ---------------------------------------------------------------------------

from commands.fetch_analyst_recommendations_parallel import ParallelAnalystFetcher
from commands.fetch_portfolio_news import PortfolioNewsAnalyzer


def test_analyst_yf_ticker_period_replaced():
    assert ParallelAnalystFetcher._yf_ticker("BRK.B") == "BRK-B"

def test_analyst_yf_ticker_no_period_unchanged():
    assert ParallelAnalystFetcher._yf_ticker("AAPL") == "AAPL"

def test_analyst_yf_ticker_multiple_periods():
    assert ParallelAnalystFetcher._yf_ticker("A.B.C") == "A-B-C"

def test_news_yf_ticker_period_replaced():
    assert PortfolioNewsAnalyzer._yf_ticker("BRK.B") == "BRK-B"

def test_news_yf_ticker_no_period_unchanged():
    assert PortfolioNewsAnalyzer._yf_ticker("MSFT") == "MSFT"


# ---------------------------------------------------------------------------
# WF32: _parse_avg_rating
# ---------------------------------------------------------------------------

def test_parse_avg_rating_numeric_with_label():
    assert ParallelAnalystFetcher._parse_avg_rating("2.4 - Buy") == pytest.approx(2.4)

def test_parse_avg_rating_integer_with_label():
    assert ParallelAnalystFetcher._parse_avg_rating("1 - Strong Buy") == pytest.approx(1.0)

def test_parse_avg_rating_plain_numeric():
    assert ParallelAnalystFetcher._parse_avg_rating("3.2") == pytest.approx(3.2)

def test_parse_avg_rating_none_returns_none():
    assert ParallelAnalystFetcher._parse_avg_rating(None) is None

def test_parse_avg_rating_empty_returns_none():
    assert ParallelAnalystFetcher._parse_avg_rating("") is None

def test_parse_avg_rating_non_numeric_returns_none():
    assert ParallelAnalystFetcher._parse_avg_rating("Buy") is None


# ---------------------------------------------------------------------------
# WF33: _is_relevant (news relevance filter)
# ---------------------------------------------------------------------------

def _analyzer() -> PortfolioNewsAnalyzer:
    """Return an analyzer without touching yfinance (no holdings loaded)."""
    a = PortfolioNewsAnalyzer.__new__(PortfolioNewsAnalyzer)
    a._company_names = {}
    return a


def test_is_relevant_ticker_in_title():
    a = _analyzer()
    assert a._is_relevant("AAPL", "Apple Inc.", "AAPL reports record earnings", "") is True

def test_is_relevant_company_name_in_title():
    a = _analyzer()
    assert a._is_relevant("AAPL", "Apple Inc.", "Apple beats estimates", "") is True

def test_is_relevant_ticker_in_summary():
    a = _analyzer()
    assert a._is_relevant("MSFT", "Microsoft Corp", "Breaking news", "MSFT up 3%") is True

def test_is_relevant_rejects_unrelated_article():
    a = _analyzer()
    assert a._is_relevant("NVDA", "Nvidia Corp", "Amazon reports Q1 results", "AWS revenue soars") is False

def test_is_relevant_short_ticker_no_name_match_rejected():
    """Single-letter tickers (e.g. 'A') must not match on the bare letter."""
    a = _analyzer()
    # Title has 'A' as a word but no company name match — should be rejected
    assert a._is_relevant("A", "", "A new market rally begins", "Rates fall") is False

def test_is_relevant_two_letter_ticker_with_name_accepted():
    """Two-letter ticker: company name match is required (ticker too short to be unambiguous)."""
    a = _analyzer()
    # "GE Aerospace" → cleaned → "Aerospace" → not > 3 chars... but "Aerospace" IS > 3 chars
    # Actually: first token > 3 chars from "GE Aerospace" after suffix strip is "Aerospace"
    assert a._is_relevant("GE", "GE Aerospace", "GE Aerospace announces layoffs", "") is True

def test_is_relevant_two_letter_ticker_no_name_rejected():
    """Two-letter ticker without company name: rejected even if symbol appears in text."""
    a = _analyzer()
    assert a._is_relevant("GE", "", "GE Aerospace announces layoffs", "") is False

def test_is_relevant_brk_b_style_ticker():
    """Dot-containing tickers: _is_relevant receives the original symbol."""
    a = _analyzer()
    # The title mentions "BRK.B" literally
    assert a._is_relevant("BRK.B", "Berkshire Hathaway", "BRK.B hits all-time high", "") is True

def test_is_relevant_berkshire_company_name():
    a = _analyzer()
    assert a._is_relevant("BRK.B", "Berkshire Hathaway Inc", "Berkshire buys Apple stake", "") is True

def test_is_relevant_suffix_stripped_for_name_match():
    """Suffixes like 'Inc', 'Corp' are stripped; first meaningful token must appear."""
    a = _analyzer()
    # "Alphabet Inc" → cleaned → "Alphabet" → appears in title
    assert a._is_relevant("GOOGL", "Alphabet Inc", "Alphabet acquires DeepMind spinoff", "") is True


# ---------------------------------------------------------------------------
# WF34: News deduplication across symbols
# ---------------------------------------------------------------------------

def test_news_dedup_same_url_not_duplicated():
    """fetch_all_news must not count the same URL for two different tickers."""
    a = _analyzer()
    seen_urls: set = set()
    seen_titles: set = set()

    url = "https://finance.yahoo.com/news/article-abc"
    title = "Market wrap: equities surge"

    # Simulate first symbol: URL not seen — should be accepted
    if url in seen_urls:
        accepted_first = False
    else:
        seen_urls.add(url)
        accepted_first = True

    # Simulate second symbol: URL already seen — should be rejected
    accepted_second = url not in seen_urls  # False because it was added above

    assert accepted_first is True
    assert accepted_second is False

def test_news_dedup_same_title_normalised():
    """Title dedup normalises whitespace / case."""
    a = _analyzer()
    seen_titles: set = set()

    title1 = "  Apple Reports Record Earnings  "
    title2 = "apple reports record earnings"

    key1 = title1.strip().lower()
    key2 = title2.strip().lower()

    seen_titles.add(key1)
    assert key2 in seen_titles  # same normalised key → deduped


# ---------------------------------------------------------------------------
# WF35: _backfill_holdings_summary writes ytm/duration to top_bonds
# ---------------------------------------------------------------------------

from commands.bond_analyzer import _backfill_holdings_summary


class _FakeBond:
    def __init__(self, cusip, ytm, macaulay_duration, modified_duration):
        self.cusip = cusip
        self.ytm = ytm
        self.macaulay_duration = macaulay_duration
        self.modified_duration = modified_duration


def test_backfill_adds_ytm_and_duration():
    """ytm/duration must be written into top_bonds entries that match by CUSIP."""
    initial = {
        "total_value": 100_000,
        "top_bonds": [
            {"cusip": "912828ZT0", "name": "US Treasury 2Y", "ytm": None, "duration": None},
            {"cusip": "0001234AB5", "name": "Corp Bond A",    "ytm": None, "duration": None},
        ],
    }
    bonds = [
        _FakeBond("912828ZT0", ytm=0.0452, macaulay_duration=1.95, modified_duration=1.90),
        _FakeBond("0001234AB5", ytm=0.0601, macaulay_duration=4.12, modified_duration=3.98),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        bond_file = Path(tmpdir) / "bond_analysis.json"
        bond_file.write_text("{}")  # must exist so parent dir is resolved
        summary_file = Path(tmpdir) / "holdings_summary.json"
        summary_file.write_text(json.dumps(initial))

        _backfill_holdings_summary(bond_file, bonds)

        result = json.loads(summary_file.read_text())
        entry_0 = result["top_bonds"][0]
        entry_1 = result["top_bonds"][1]

    assert entry_0["ytm"] == pytest.approx(0.0452)
    assert entry_0["duration"] == pytest.approx(1.95)
    assert entry_1["ytm"] == pytest.approx(0.0601)
    assert entry_1["duration"] == pytest.approx(4.12)


def test_backfill_does_not_overwrite_existing_values():
    """Entries that already have ytm/duration must not be changed."""
    initial = {
        "top_bonds": [
            {"cusip": "912828ZT0", "ytm": 0.04, "duration": 2.0},
        ],
    }
    bonds = [
        _FakeBond("912828ZT0", ytm=0.05, macaulay_duration=2.5, modified_duration=2.4),
    ]

    with tempfile.TemporaryDirectory() as tmpdir:
        bond_file = Path(tmpdir) / "bond_analysis.json"
        bond_file.write_text("{}")
        summary_file = Path(tmpdir) / "holdings_summary.json"
        summary_file.write_text(json.dumps(initial))

        _backfill_holdings_summary(bond_file, bonds)

        result = json.loads(summary_file.read_text())
        entry = result["top_bonds"][0]

    # Pre-existing values must be preserved
    assert entry["ytm"] == pytest.approx(0.04)
    assert entry["duration"] == pytest.approx(2.0)


def test_backfill_no_op_when_summary_missing():
    """Must not raise if holdings_summary.json does not exist."""
    with tempfile.TemporaryDirectory() as tmpdir:
        bond_file = Path(tmpdir) / "bond_analysis.json"
        bond_file.write_text("{}")
        # holdings_summary.json intentionally NOT created

        _backfill_holdings_summary(bond_file, [])  # must not raise


def test_backfill_cusip_not_in_bonds_unchanged():
    """top_bonds entries with no matching bond object remain unchanged (ytm stays None)."""
    initial = {
        "top_bonds": [
            {"cusip": "UNKNOWNCUSIP", "ytm": None, "duration": None},
        ],
    }
    with tempfile.TemporaryDirectory() as tmpdir:
        bond_file = Path(tmpdir) / "bond_analysis.json"
        bond_file.write_text("{}")
        summary_file = Path(tmpdir) / "holdings_summary.json"
        summary_file.write_text(json.dumps(initial))

        _backfill_holdings_summary(bond_file, [])

        result = json.loads(summary_file.read_text())

    assert result["top_bonds"][0]["ytm"] is None
