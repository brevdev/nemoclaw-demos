"""
Tests for rendering/compact_serializers.py.

Covers:
- _truncate, _strip_none, _top_n helpers
- serialize_analyst_compact — base and enriched records, max_symbols, truncation
- serialize_news_compact   — empty, minimal, and full payloads
"""

import pytest
from rendering.compact_serializers import (
    _truncate,
    _strip_none,
    _top_n,
    serialize_analyst_compact,
    serialize_news_compact,
)


# ---------------------------------------------------------------------------
# Helper: _truncate
# ---------------------------------------------------------------------------

def test_truncate_short_string_unchanged():
    assert _truncate("hello", 10) == "hello"

def test_truncate_exact_limit_unchanged():
    assert _truncate("hello", 5) == "hello"

def test_truncate_long_string_cut():
    assert _truncate("abcdef", 4) == "abcd"

def test_truncate_none_returns_empty():
    assert _truncate(None, 50) == ""

def test_truncate_empty_string_returns_empty():
    assert _truncate("", 50) == ""

def test_truncate_non_string_coerced():
    assert _truncate(12345, 3) == "123"


# ---------------------------------------------------------------------------
# Helper: _strip_none
# ---------------------------------------------------------------------------

def test_strip_none_removes_none_values():
    result = _strip_none({"a": 1, "b": None, "c": "x"})
    assert "b" not in result
    assert result == {"a": 1, "c": "x"}

def test_strip_none_keeps_falsy_non_none():
    result = _strip_none({"a": 0, "b": "", "c": False, "d": None})
    assert "d" not in result
    assert "a" in result
    assert "b" in result
    assert "c" in result

def test_strip_none_empty_dict():
    assert _strip_none({}) == {}


# ---------------------------------------------------------------------------
# Helper: _top_n
# ---------------------------------------------------------------------------

def test_top_n_returns_first_n():
    assert _top_n([1, 2, 3, 4, 5], 3) == [1, 2, 3]

def test_top_n_fewer_items_than_n():
    assert _top_n([1, 2], 10) == [1, 2]

def test_top_n_empty_list():
    assert _top_n([], 5) == []

def test_top_n_none_returns_empty():
    assert _top_n(None, 5) == []

def test_top_n_zero_returns_empty():
    assert _top_n([1, 2, 3], 0) == []


# ---------------------------------------------------------------------------
# serialize_analyst_compact — structure
# ---------------------------------------------------------------------------

def _base_payload(n=3):
    """Build a minimal analyst payload with n base (non-enriched) symbols."""
    recs = {}
    for i in range(n):
        sym = f"SYM{i}"
        recs[sym] = {
            "symbol": sym,
            "consensus": "buy",
            "analyst_count": 10 + i,
            "recommendation_mean": 2.0 + i * 0.1,
            "current_price": 100.0 + i,
            "buy_count": 8,
            "hold_count": 2,
            "sell_count": 0,
            "target_price_mean": 120.0,
            "data_source": "Yahoo Finance",
        }
    return {
        "disclaimer": "EDUCATIONAL ANALYSIS",
        "timestamp": "2026-04-08T00:00:00",
        "total_symbols": n,
        "output_file": "/tmp/analyst.json",
        "recommendations": recs,
    }


def test_analyst_compact_has_required_keys():
    result = serialize_analyst_compact(_base_payload())
    for key in ("_note", "disclaimer", "timestamp", "total_symbols", "recommendations", "output_file"):
        assert key in result, f"Missing key: {key}"


def test_analyst_compact_no_consultation_model_when_absent():
    result = serialize_analyst_compact(_base_payload())
    assert "consultation_model" not in result


def test_analyst_compact_includes_consultation_model_when_present():
    payload = _base_payload()
    payload["consultation_model"] = "gemma4:26b"
    result = serialize_analyst_compact(payload)
    assert result["consultation_model"] == "gemma4:26b"


def test_analyst_compact_base_strips_lists_and_dicts():
    payload = _base_payload(1)
    sym = "SYM0"
    payload["recommendations"][sym]["big_list"] = list(range(100))
    payload["recommendations"][sym]["nested"] = {"a": 1}
    result = serialize_analyst_compact(payload)
    rec = result["recommendations"][sym]
    assert "big_list" not in rec
    assert "nested" not in rec


def test_analyst_compact_base_keeps_scalars():
    result = serialize_analyst_compact(_base_payload(1))
    rec = result["recommendations"]["SYM0"]
    assert rec["analyst_count"] == 10
    assert rec["consensus"] == "buy"


def test_analyst_compact_max_symbols_respected():
    payload = _base_payload(10)
    result = serialize_analyst_compact(payload, max_symbols=3)
    assert len(result["recommendations"]) == 3


def test_analyst_compact_max_symbols_default_25():
    payload = _base_payload(30)
    result = serialize_analyst_compact(payload)
    assert len(result["recommendations"]) == 25


def test_analyst_compact_total_symbols_reflects_original():
    payload = _base_payload(30)
    result = serialize_analyst_compact(payload)
    assert result["total_symbols"] == 30


# ---------------------------------------------------------------------------
# serialize_analyst_compact — enriched records
# ---------------------------------------------------------------------------

def _enriched_rec(symbol="AAPL"):
    return {
        "symbol": symbol,
        "consensus": "strong_buy",
        "analyst_count": 32,
        "recommendation_mean": 1.5,
        "current_price": 195.0,
        "sentiment_label": "positive",
        "sentiment_score": 0.87,
        "recommendation_strength": "strong",
        "synthesis": "Bullish outlook driven by AI services expansion. " * 20,
        "key_insights": ["Strong iPhone cycle", "Services margin expansion", "AI pipeline"],
        "risk_assessment": "Trade tension risks remain. " * 10,
        "consultation": {"is_heuristic": False, "provider": "ollama", "model": "gemma4:26b"},
        # These should be stripped (list, not in ENRICHED_KEEP_FIELDS):
        "raw_targets": [100, 110, 120, 130],
        "history_list": [{"date": "2026-01-01", "rec": "buy"}],
    }


def _enriched_payload():
    sym = "AAPL"
    return {
        "disclaimer": "EDUCATIONAL ANALYSIS",
        "timestamp": "2026-04-08T00:00:00",
        "total_symbols": 1,
        "consultation_model": "gemma4:26b",
        "output_file": "/tmp/analyst_enriched.json",
        "recommendations": {sym: _enriched_rec(sym)},
    }


def test_analyst_compact_enriched_strips_unlisted_arrays():
    result = serialize_analyst_compact(_enriched_payload())
    rec = result["recommendations"]["AAPL"]
    assert "raw_targets" not in rec
    assert "history_list" not in rec


def test_analyst_compact_enriched_keeps_enriched_fields():
    result = serialize_analyst_compact(_enriched_payload())
    rec = result["recommendations"]["AAPL"]
    for field in ("synthesis", "key_insights", "risk_assessment", "consultation",
                  "recommendation_strength", "sentiment_label", "sentiment_score"):
        assert field in rec, f"Enriched field missing: {field}"


def test_analyst_compact_enriched_truncates_synthesis():
    result = serialize_analyst_compact(_enriched_payload(), truncate_text=50)
    rec = result["recommendations"]["AAPL"]
    assert len(rec["synthesis"]) <= 50


def test_analyst_compact_enriched_truncates_risk_assessment():
    result = serialize_analyst_compact(_enriched_payload(), truncate_text=50)
    rec = result["recommendations"]["AAPL"]
    assert len(rec["risk_assessment"]) <= 50


def test_analyst_compact_enriched_truncates_key_insights_items():
    result = serialize_analyst_compact(_enriched_payload(), truncate_text=10)
    rec = result["recommendations"]["AAPL"]
    for item in rec["key_insights"]:
        assert len(item) <= 10


def test_analyst_compact_heuristic_consultation_not_enriched():
    """Records with is_heuristic=True use base mode: lists stripped, scalars kept."""
    payload = _enriched_payload()
    payload["recommendations"]["AAPL"]["consultation"]["is_heuristic"] = True
    result = serialize_analyst_compact(payload)
    rec = result["recommendations"]["AAPL"]
    # Base mode: list fields stripped
    assert "raw_targets" not in rec
    assert "history_list" not in rec
    assert "key_insights" not in rec   # key_insights is a list
    # Scalar fields (synthesis, risk_assessment) are kept in base mode
    assert "synthesis" in rec
    assert "risk_assessment" in rec


# ---------------------------------------------------------------------------
# serialize_news_compact — structure
# ---------------------------------------------------------------------------

def _news_payload():
    return {
        "symbols_fetched": 25,
        "total_news_items": 147,
        "portfolio_impact_summary": {
            "net_impact": -1234.56,
            "positive_impact": 500.0,
            "negative_impact": -1734.56,
            "impact_pct": -0.82,
        },
        "sentiment_breakdown": {
            "positive_news_count": 40,
            "negative_news_count": 80,
            "neutral_news_count": 27,
        },
        "portfolio_narrative": {
            "overall_posture": "cautious_bearish",
            "narrative": "Portfolio faces headwinds from rate uncertainty.",
            "key_tailwinds": ["AI demand strong", "Services margins expanding"],
            "key_risks": ["Tariff risk", "Fed rate path", "China slowdown"],
        },
        "macro_themes": {
            "themes": [
                {"theme": "AI Infrastructure", "direction": "bullish",
                 "portfolio_weight_pct": 18.5, "affected_symbols": ["NVDA", "MSFT"]},
                {"theme": "Rate Sensitivity", "direction": "bearish",
                 "portfolio_weight_pct": 12.0, "affected_symbols": ["TLT", "AGG"]},
            ]
        },
        "top_positive_movers": [
            {"symbol": "NVDA", "title": "NVDA beats estimates",
             "summary": "Strong quarter." * 30, "portfolio_impact": 950.0,
             "sentiment": "positive", "confidence": 0.9, "impact_pct": 0.6,
             "publish_date": "2026-04-07"},
        ],
        "top_negative_movers": [
            {"symbol": "AAPL", "title": "AAPL faces tariff headwinds",
             "summary": "Analysts cut targets." * 20, "portfolio_impact": -1200.0,
             "sentiment": "negative", "confidence": 0.85, "impact_pct": -0.8,
             "publish_date": "2026-04-07"},
        ],
        "symbol_digest": [
            {"symbol": "NVDA", "weight_pct": 5.2, "article_count": 8,
             "sentiment": "positive", "confidence": 0.88,
             "top_story": "NVDA Blackwell shipments accelerate"},
            {"symbol": "AAPL", "weight_pct": 4.9, "article_count": 5,
             "sentiment": "negative", "confidence": 0.82,
             "top_story": "AAPL faces supply chain pressures"},
        ],
        "output_file": "/tmp/portfolio_news.json",
    }


def test_news_compact_has_required_keys():
    result = serialize_news_compact(_news_payload())
    for key in ("_note", "disclaimer", "symbols_fetched", "total_items", "posture",
                "impact_summary", "narrative", "key_tailwinds", "key_risks",
                "macro_themes", "top_positive", "top_negative", "symbol_digest",
                "output_file"):
        assert key in result, f"Missing key: {key}"


def test_news_compact_posture_formatted():
    result = serialize_news_compact(_news_payload())
    # "cautious_bearish" → "Cautious Bearish"
    assert result["posture"] == "Cautious Bearish"


def test_news_compact_impact_summary_values():
    result = serialize_news_compact(_news_payload())
    s = result["impact_summary"]
    assert s["positive"] == 40
    assert s["negative"] == 80
    assert s["neutral"] == 27
    assert s["net_impact"] == -1234.56
    assert s["impact_pct"] == -0.82


def test_news_compact_key_tailwinds_capped_at_3():
    payload = _news_payload()
    payload["portfolio_narrative"]["key_tailwinds"] = ["a", "b", "c", "d", "e"]
    result = serialize_news_compact(payload)
    assert len(result["key_tailwinds"]) == 3


def test_news_compact_macro_themes_capped_at_5():
    payload = _news_payload()
    payload["macro_themes"]["themes"] = [
        {"theme": f"T{i}", "direction": "neutral",
         "portfolio_weight_pct": 1.0, "affected_symbols": []}
        for i in range(8)
    ]
    result = serialize_news_compact(payload)
    assert len(result["macro_themes"]) == 5


def test_news_compact_top_positive_capped():
    payload = _news_payload()
    payload["top_positive_movers"] = [
        {"symbol": f"S{i}", "title": "t", "summary": "s",
         "portfolio_impact": float(i), "sentiment": "positive",
         "confidence": 0.8, "impact_pct": 0.1, "publish_date": "2026-04-07"}
        for i in range(10)
    ]
    result = serialize_news_compact(payload, top_positive=3)
    assert len(result["top_positive"]) == 3


def test_news_compact_symbol_digest_capped():
    payload = _news_payload()
    payload["symbol_digest"] = [
        {"symbol": f"S{i}", "weight_pct": 1.0, "article_count": 3,
         "sentiment": "neutral", "top_story": "headline"}
        for i in range(30)
    ]
    result = serialize_news_compact(payload, max_symbol_digest=10)
    assert len(result["symbol_digest"]) == 10


def test_news_compact_summary_truncated():
    payload = _news_payload()
    result = serialize_news_compact(payload, summary_limit=20)
    for item in result["top_positive"] + result["top_negative"]:
        assert len(item["summary"]) <= 20


def test_news_compact_title_truncated_to_80():
    payload = _news_payload()
    payload["top_positive_movers"][0]["title"] = "x" * 200
    result = serialize_news_compact(payload)
    assert len(result["top_positive"][0]["title"]) <= 80


def test_news_compact_empty_payload():
    result = serialize_news_compact({})
    assert result["symbols_fetched"] == 0
    assert result["total_items"] == 0
    assert result["top_positive"] == []
    assert result["symbol_digest"] == []


def test_news_compact_top_story_fallback_to_top_story_title():
    """Guard for legacy 'top_story_title' key."""
    payload = _news_payload()
    payload["symbol_digest"][0].pop("top_story")
    payload["symbol_digest"][0]["top_story_title"] = "legacy headline"
    result = serialize_news_compact(payload)
    assert result["symbol_digest"][0]["top_story"] == "legacy headline"


def test_news_compact_output_file_preserved():
    payload = _news_payload()
    payload["output_file"] = "/custom/path.json"
    result = serialize_news_compact(payload)
    assert result["output_file"] == "/custom/path.json"
