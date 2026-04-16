#!/usr/bin/env python3
"""
Compact stdout serializers for InvestorClaw analysis outputs.

These functions reduce LLM context token consumption by emitting a slim dict
instead of the full enriched payload.  They are used exclusively for *stdout*
emission — full JSON artifacts are always written to disk separately.

Usage:
    from rendering.compact_serializers import serialize_analyst_compact, serialize_news_compact
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _truncate(text: Optional[Any], limit: int) -> str:
    """Return *text* as a string truncated to *limit* characters, or '' if None."""
    if not text:
        return ''
    s = str(text)
    return s[:limit] if len(s) > limit else s


def _strip_none(d: dict) -> dict:
    """Remove keys whose value is None (shallow)."""
    return {k: v for k, v in d.items() if v is not None}


def _top_n(lst: Optional[List], n: int) -> List:
    """Return first *n* items from lst, or [] if lst is None/empty."""
    if not lst:
        return []
    return lst[:n]


# ---------------------------------------------------------------------------
# Analyst compact serializer
# ---------------------------------------------------------------------------

# Fields retained for enriched (non-heuristic consultation) records.
# Matches ENRICHED_KEEP_FIELDS formerly defined in fetch_analyst_recommendations_parallel.py.
_ENRICHED_KEEP_FIELDS = frozenset({
    'symbol', 'consensus', 'analyst_count', 'recommendation_mean',
    'current_price', 'sentiment_label', 'sentiment_score',
    'synthesis', 'key_insights', 'risk_assessment',
    'recommendation_strength', 'consultation', 'fingerprint', 'quote',
})


def _compact_analyst_record(rec: dict, *, truncate_text: int) -> dict:
    """Per-record compaction for analyst stdout.

    Enriched (non-heuristic consultation present):
      - Strip list/dict fields not in _ENRICHED_KEEP_FIELDS.
      - Truncate text fields (synthesis, risk_assessment) to *truncate_text* chars.
      - Truncate each item in key_insights list.

    Base (no consultation, or heuristic):
      - Keep all scalar fields; strip list/dict fields.
    """
    consult = rec.get('consultation', {})
    is_enriched = bool(consult) and (
        isinstance(consult, dict) and not consult.get('is_heuristic', True)
    )

    if is_enriched:
        compact = {
            k: v for k, v in rec.items()
            if k in _ENRICHED_KEEP_FIELDS or not isinstance(v, (list, dict))
        }
        for text_key in ('synthesis', 'risk_assessment'):
            if compact.get(text_key):
                compact[text_key] = _truncate(compact[text_key], truncate_text)
        ki = compact.get('key_insights')
        if ki:
            if isinstance(ki, list):
                compact['key_insights'] = [_truncate(s, truncate_text) for s in ki[:5]]
            else:
                compact['key_insights'] = _truncate(ki, truncate_text)
        # Truncated quote passthrough — fingerprint + attribution + on-disk ref.
        # Full synthesis text is already in rec['synthesis'] (truncated above).
        # quote_path is the canonical text artifact for verbatim citation audit.
        # synthesis_instruction is a machine-readable directive to the operational
        # LLM: cite the synthesis text verbatim and include the fingerprint.
        q = rec.get('quote')
        if q and isinstance(q, dict):
            fp_val = q.get('fingerprint', '')
            attr_val = q.get('attribution', '')
            entry = _strip_none({
                'fingerprint': fp_val,
                'attribution': attr_val,
                'verbatim_required': True,
                'quote_path': q.get('quote_path'),
                'card_path': q.get('card_path'),
            })
            if fp_val:
                entry['synthesis_instruction'] = (
                    f"Cite the synthesis text above verbatim (attribution: {attr_val}). "
                    f"Include fingerprint {fp_val} when referencing this source."
                )
            compact['quote'] = entry
        compact['synthesis_basis'] = 'enriched'
        return compact

    # Base: keep scalars only
    base = {k: v for k, v in rec.items() if not isinstance(v, (list, dict))}
    # Determine synthesis_basis
    if rec.get('analyst_count', 0) == 0 and not rec.get('current_price'):
        base['synthesis_basis'] = 'failed'
    else:
        base['synthesis_basis'] = 'structured'
    return base


def _build_enrichment_status(analyst_payload: dict, reports_dir: Optional[Path] = None) -> dict:
    """Build enrichment_status block from payload counts + optional live progress file."""
    recommendations = analyst_payload.get('recommendations', {})
    enriched_count = sum(
        1 for rec in recommendations.values()
        if isinstance(rec.get('consultation'), dict) and not rec['consultation'].get('is_heuristic', True)
    )
    total_equity = len(recommendations)
    enriched_pct = round(enriched_count / total_equity * 100, 1) if total_equity else 0.0

    in_progress = False
    session_fingerprint = "0000000000000000"
    bonds_covered = False

    if reports_dir is not None:
        try:
            from services.consultation_policy import get_enrichment_status
            live = get_enrichment_status(reports_dir)
            in_progress = live.get("in_progress", False)
            session_fingerprint = live.get("session_fingerprint", session_fingerprint)
            bonds_covered = live.get("bonds_covered", False)
            fp_short = session_fingerprint[:8]
            display = live.get("display", f"✅ Enrichment: {enriched_count}/{total_equity} · {enriched_pct}%")
        except Exception:
            fp_short = session_fingerprint[:8]
            display = f"✅ Enrichment: {enriched_count}/{total_equity} · {enriched_pct}% · {fp_short}"
    else:
        fp_short = session_fingerprint[:8]
        if in_progress:
            display = f"⏳ Enrichment: {enriched_count}/{total_equity} · {enriched_pct}% · {fp_short} · updating"
        else:
            display = f"✅ Enrichment: {enriched_count}/{total_equity} · {enriched_pct}% · {fp_short}"

    return {
        "enriched_count": enriched_count,
        "total_equity": total_equity,
        "enriched_pct": enriched_pct,
        "in_progress": in_progress,
        "session_fingerprint": session_fingerprint,
        "bonds_covered": bonds_covered,
        "display": display,
    }


def serialize_analyst_compact(
    analyst_payload: dict,
    reports_dir: Optional[Path] = None,
    *,
    max_symbols: int = 25,
    truncate_text: int = 300,
) -> dict:
    """Return a compact analyst dict for stdout (LLM context).

    Full enriched data is written to disk by the caller — do not read it.

    Args:
        analyst_payload:  Dict with a 'recommendations' key (symbol → rec dict).
        reports_dir:      Optional path to portfolio_reports/ for live enrichment status.
        max_symbols:      Maximum number of symbols to include.
        truncate_text:    Character limit for text fields (synthesis, risk_assessment, etc.).

    Returns:
        Slim dict suitable for ``json.dumps(…, separators=(',',':'))`` → stdout.
    """
    recommendations: dict = analyst_payload.get('recommendations', {})
    symbols_items = list(recommendations.items())[:max_symbols]

    compact_recs = {
        symbol: _compact_analyst_record(rec, truncate_text=truncate_text)
        for symbol, rec in symbols_items
    }

    out: dict = {
        '_note': (
            'Compact analyst summary for LLM context. '
            'Full data is in analyst_data.json — do NOT read that file.'
        ),
        'disclaimer': analyst_payload.get(
            'disclaimer', 'EDUCATIONAL ANALYSIS - NOT INVESTMENT ADVICE'
        ),
        'timestamp': analyst_payload.get('timestamp', ''),
        'total_symbols': analyst_payload.get('total_symbols', len(recommendations)),
        'recommendations': compact_recs,
        'output_file': analyst_payload.get('output_file', ''),
        'enrichment_status': _build_enrichment_status(analyst_payload, reports_dir),
    }

    if analyst_payload.get('consultation_model'):
        out['consultation_model'] = analyst_payload['consultation_model']

    return _strip_none(out)


# ---------------------------------------------------------------------------
# News compact serializer
# ---------------------------------------------------------------------------

def serialize_news_compact(
    news_payload: dict,
    *,
    top_positive: int = 5,
    top_negative: int = 5,
    max_symbol_digest: int = 20,
    summary_limit: int = 300,
) -> dict:
    """Return a compact news dict for stdout (LLM context).

    Args:
        news_payload:       compact_report dict from PortfolioNewsAnalyzer.fetch_all_news().
                            Caller should inject 'output_file' into this dict before passing.
        top_positive:       Max positive movers to include.
        top_negative:       Max negative movers to include.
        max_symbol_digest:  Max symbols in the per-symbol digest section.
        summary_limit:      Character limit for article summaries.

    Returns:
        Slim dict suitable for ``json.dumps(…, separators=(',',':'))`` → stdout.
    """
    _summary = news_payload.get('portfolio_impact_summary', {})
    _breakdown = news_payload.get('sentiment_breakdown', {})
    _narr = news_payload.get('portfolio_narrative') or {}
    _themes = news_payload.get('macro_themes') or {}

    posture = (
        (_narr.get('overall_posture', 'neutral') or 'neutral')
        .replace('_', ' ')
        .title()
    )

    compact_themes = [
        {
            'theme': t.get('theme', ''),
            'direction': t.get('direction', ''),
            'weight_pct': round(t.get('portfolio_weight_pct', 0), 1),
            'symbols': _top_n(t.get('affected_symbols', []), 5),
        }
        for t in _top_n(_themes.get('themes'), 5)
    ]

    compact_positive = [
        {
            'symbol': i.get('symbol', ''),
            'title': _truncate(i.get('title', ''), 80),
            'url': i.get('url') or i.get('link', ''),
            'summary': _truncate(i.get('summary') or '', summary_limit),
            'impact': round(i.get('portfolio_impact', 0), 2),
        }
        for i in _top_n(news_payload.get('top_positive_movers'), top_positive)
    ]

    compact_negative = [
        {
            'symbol': i.get('symbol', ''),
            'title': _truncate(i.get('title', ''), 80),
            'url': i.get('url') or i.get('link', ''),
            'summary': _truncate(i.get('summary') or '', summary_limit),
            'impact': round(i.get('portfolio_impact', 0), 2),
        }
        for i in _top_n(news_payload.get('top_negative_movers'), top_negative)
    ]

    compact_digest = [
        {
            'symbol': e.get('symbol', ''),
            'weight_pct': round(e.get('weight_pct', 0), 2),
            'articles': e.get('article_count', 0),
            'sentiment': e.get('sentiment', 'neutral'),
            # compact_report uses 'top_story'; guard against legacy 'top_story_title'
            'top_story': _truncate(
                e.get('top_story') or e.get('top_story_title') or '', 80
            ),
        }
        for e in _top_n(news_payload.get('symbol_digest'), max_symbol_digest)
    ]

    return {
        '_note': (
            'Compact news summary for LLM. '
            'Full article data is at output_file — do NOT read that file.'
        ),
        'disclaimer': 'EDUCATIONAL ANALYSIS - NOT INVESTMENT ADVICE',
        'symbols_fetched': news_payload.get('symbols_fetched', 0),
        'total_items': news_payload.get('total_news_items', 0),
        'posture': posture,
        'impact_summary': {
            'net_impact': round(_summary.get('net_impact', 0), 2),
            'impact_pct': round(_summary.get('impact_pct', 0), 2),
            'positive': _breakdown.get('positive_news_count', 0),
            'negative': _breakdown.get('negative_news_count', 0),
            'neutral': _breakdown.get('neutral_news_count', 0),
        },
        'narrative': _narr.get('narrative', ''),
        'key_tailwinds': _top_n(_narr.get('key_tailwinds'), 3),
        'key_risks': _top_n(_narr.get('key_risks'), 3),
        'macro_themes': compact_themes,
        'top_positive': compact_positive,
        'top_negative': compact_negative,
        'symbol_digest': compact_digest,
        'output_file': news_payload.get('output_file', ''),
    }


# ---------------------------------------------------------------------------
# Holdings compact serializer
# ---------------------------------------------------------------------------

def serialize_holdings_compact(
    equity_data: dict,
    bond_data: dict,
    cash_data: dict,
    margin_data: dict,
    total_value: float,
    cdm_summary: dict,
    output_file: str,
    *,
    top_equity: int = 25,
    top_bonds: int = 5,
) -> dict:
    """Return a compact holdings dict for stdout (LLM context, ~8-15KB vs 290KB full CDM).

    Args:
        equity_data:   Dict of {symbol: Holding} for equity positions.
        bond_data:     Dict of {symbol: Holding} for bond positions.
        cash_data:     Dict of {symbol: Holding} for cash positions.
        margin_data:   Dict of {symbol: Holding} for margin positions.
        total_value:   Total portfolio value (all asset classes combined).
        cdm_summary:   CDM portfolio summary dict (camelCase keys from PortfolioCDM).
        output_file:   Path string for the full raw holdings.json artifact.
        top_equity:    How many top equity positions to include (default 25).
        top_bonds:     How many top bond positions to include (default 5).

    Returns:
        Slim dict suitable for ``json.dumps(…, separators=(',',':'))`` → stdout.
        Also written to ``holdings_summary.json`` by the caller.
    """
    from datetime import date as _date

    def _attr(obj, key, default=None):
        """Duck-typed attribute/key getter — works on both dataclass objects and dicts."""
        if isinstance(obj, dict):
            return obj.get(key, default)
        return getattr(obj, key, default)

    equity_value = sum(_attr(h, 'value', 0) for h in equity_data.values())
    bond_value   = sum(_attr(h, 'value', 0) for h in bond_data.values())
    cash_value   = sum(_attr(h, 'value', 0) for h in cash_data.values())
    margin_value = sum(_attr(h, 'value', 0) for h in margin_data.values())
    net_value    = total_value - abs(margin_value)

    # Equity positions sorted by market value descending
    eq_sorted = sorted(equity_data.values(), key=lambda h: _attr(h, 'value', 0), reverse=True)

    compact_equity = []
    for h in eq_sorted[:top_equity]:
        val = _attr(h, 'value', 0)
        weight_pct = round(val / total_value * 100, 2) if total_value else 0
        gl_raw = _attr(h, 'unrealized_gain_loss_pct', 0) or 0
        # Some Holding objects store this as a decimal fraction (0.05 = 5%);
        # normalise to percentage points.
        gl_pct = round(gl_raw * 100, 2) if abs(gl_raw) < 1.5 else round(gl_raw, 2)
        compact_equity.append({
            'symbol':     _attr(h, 'symbol', ''),
            'sector':     _attr(h, 'sector') or 'Unknown',
            'value':      round(val, 2),
            'weight_pct': weight_pct,
            'gl_pct':     gl_pct,
            'type':       _attr(h, 'security_type') or 'equity',
        })

    # Sector weights (equity only)
    sector_totals: dict = {}
    for h in equity_data.values():
        sec = _attr(h, 'sector') or 'Unknown'
        sector_totals[sec] = sector_totals.get(sec, 0.0) + _attr(h, 'value', 0)
    sector_weights = {
        sec: round(val / equity_value * 100, 1)
        for sec, val in sorted(sector_totals.items(), key=lambda x: x[1], reverse=True)
    } if equity_value else {}

    # Top bonds by value
    bd_sorted = sorted(bond_data.values(), key=lambda h: _attr(h, 'value', 0), reverse=True)
    compact_bonds = []
    for h in bd_sorted[:top_bonds]:
        val = _attr(h, 'value', 0)
        mat = _attr(h, 'maturity_date')
        compact_bonds.append({
            'name':       _attr(h, 'bond_name') or _attr(h, 'symbol') or 'Unknown',
            'cusip':      _attr(h, 'cusip') or '',
            'value':      round(val, 2),
            'weight_pct': round(val / total_value * 100, 2) if total_value else 0,
            'coupon':     _attr(h, 'coupon_rate'),
            'maturity':   str(mat) if mat else None,
        })

    return {
        'disclaimer':           'EDUCATIONAL ANALYSIS - NOT INVESTMENT ADVICE',
        'is_investment_advice': False,
        'as_of':                str(_date.today()),
        'summary': {
            'total_value':        round(total_value, 2),
            'net_value':          round(net_value, 2),
            'equity_value':       round(equity_value, 2),
            'bond_value':         round(bond_value, 2),
            'cash_value':         round(cash_value, 2),
            'margin_value':       round(margin_value, 2),
            'equity_pct':         round(equity_value / total_value * 100, 1) if total_value else 0,
            'bond_pct':           round(bond_value / total_value * 100, 1) if total_value else 0,
            'cash_pct':           round(cash_value / total_value * 100, 1) if total_value else 0,
            'position_count': {
                'equity': len(equity_data),
                'bond':   len(bond_data),
                'cash':   len(cash_data),
            },
            'unrealized_gl':     round(cdm_summary.get('totalUnrealizedGainLoss', 0) or 0, 2),
            'unrealized_gl_pct': round(cdm_summary.get('totalUnrealizedGainLossPct', 0) or 0, 2),
        },
        'top_equity':               compact_equity,
        'sector_weights':           sector_weights,
        'top_bonds':                compact_bonds,
        'remaining_equity_count':   max(0, len(equity_data) - top_equity),
        'output_file':              output_file,
    }
