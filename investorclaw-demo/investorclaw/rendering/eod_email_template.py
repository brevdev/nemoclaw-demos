#!/usr/bin/env python3
"""
rendering/eod_email_template.py — End-of-Day Portfolio Report Email Renderer

Produces a self-contained HTML email with inline CSS + a <style> block for
mobile media queries.  Renders correctly in Gmail (desktop + mobile), iOS Mail,
Apple Mail, and Outlook Web.

Dark / high-contrast theme — WCAG AA on all text/background combinations.
Mobile-first layout: 2-column sections stack to single column on ≤ 600px.

`report_data` keys:
    date          str         "2026-04-11"
    holdings      dict        holdings_summary.json contents
    analyst       dict        analyst_recommendations_summary.json contents
    news          dict        portfolio_news.json contents
    bonds         dict | None bond_analysis.json contents (None if no bonds)
    performance   dict        performance.json contents
    fa_topics     list        output of fa_discussion.extract_fa_topics()
    run_duration_s float      total run time in seconds (0 if report-only mode)
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Palette — dark / high-contrast (GitHub Dark inspired, WCAG AA)
# ---------------------------------------------------------------------------

_C_BG             = "#0d1117"
_C_CARD           = "#161b22"
_C_HEADER_BG      = "#010409"
_C_HEADER_TEXT    = "#e6edf3"
_C_ACCENT         = "#58a6ff"
_C_POSITIVE       = "#3fb950"
_C_NEGATIVE       = "#f85149"
_C_NEUTRAL        = "#8b949e"
_C_HIGH           = "#f85149"
_C_MEDIUM         = "#d29922"
_C_LOW            = "#3fb950"
_C_BORDER         = "#30363d"
_C_LABEL          = "#8b949e"
_C_DISCLAIMER     = "#6e7681"

# Body text hierarchy
_C_TEXT_PRIMARY   = "#e6edf3"   # headings, values
_C_TEXT_BODY      = "#c9d1d9"   # narrative paragraphs
_C_TEXT_MUTED     = "#8b949e"   # labels, symbols, secondary

_FONT_STACK = "system-ui,-apple-system,BlinkMacSystemFont,'Segoe UI',Arial,sans-serif"


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

def _pct(v: float, decimals: int = 1) -> str:
    return f"{v:.{decimals}%}"


def _currency(v: float) -> str:
    if abs(v) >= 1_000_000:
        return f"${v/1_000_000:,.2f}M"
    return f"${v:,.0f}"


def _sign_color(v: float) -> str:
    if v > 0:
        return _C_POSITIVE
    if v < 0:
        return _C_NEGATIVE
    return _C_NEUTRAL


def _signed(v: float, decimals: int = 1) -> str:
    sign = "+" if v > 0 else ""
    return f"{sign}{v:.{decimals}%}"


def _priority_color(p: str) -> str:
    return {"high": _C_HIGH, "medium": _C_MEDIUM, "low": _C_LOW}.get(p, _C_NEUTRAL)


def _priority_label(p: str) -> str:
    return {"high": "HIGH", "medium": "MEDIUM", "low": "LOW"}.get(p, p.upper())


# ---------------------------------------------------------------------------
# HTML building blocks
# ---------------------------------------------------------------------------

def _h(tag: str, content: str, style: str = "", **attrs) -> str:
    attr_str = " ".join(f'{k}="{v}"' for k, v in attrs.items())
    s = f' style="{style}"' if style else ""
    return f"<{tag}{s} {attr_str}>{content}</{tag}>"


def _div(content: str, style: str = "") -> str:
    s = f' style="{style}"' if style else ""
    return f"<div{s}>{content}</div>"


def _td(content: str, style: str = "") -> str:
    base = f"padding:8px 12px;border-bottom:1px solid {_C_BORDER};vertical-align:top;color:{_C_TEXT_BODY};"
    return f'<td style="{base}{style}">{content}</td>'


def _th(content: str, style: str = "") -> str:
    base = (
        f"padding:8px 12px;background:{_C_HEADER_BG};color:{_C_TEXT_PRIMARY};"
        "font-weight:600;font-size:11px;text-transform:uppercase;letter-spacing:0.05em;"
        "text-align:left;"
    )
    return f'<th style="{base}{style}">{content}</th>'


def _table(rows: List[str], header: str = "") -> str:
    style = f"width:100%;border-collapse:collapse;font-size:13px;color:{_C_TEXT_BODY};"
    thead = f"<thead><tr>{header}</tr></thead>" if header else ""
    tbody = f"<tbody>{''.join(rows)}</tbody>"
    return f'<table style="{style}">{thead}{tbody}</table>'


def _section(title: str, content: str, icon: str = "") -> str:
    return f"""
<div style="margin-bottom:24px;">
  <div style="font-size:13px;font-weight:700;text-transform:uppercase;letter-spacing:0.08em;
              color:{_C_LABEL};margin-bottom:10px;padding-bottom:6px;
              border-bottom:2px solid {_C_BORDER};">{icon}{title}</div>
  {content}
</div>"""


def _card(content: str) -> str:
    return f"""
<div style="background:{_C_CARD};border-radius:8px;padding:20px;
            border:1px solid {_C_BORDER};
            box-shadow:0 2px 8px rgba(0,0,0,0.4);margin-bottom:20px;">
{content}
</div>"""


def _kpi_row(kpis: List[tuple]) -> str:
    """kpis: list of (label, value, color)"""
    cells = []
    for label, value, color in kpis:
        cells.append(f"""
<td style="padding:0 20px 0 0;text-align:left;white-space:nowrap;">
  <div style="font-size:11px;color:{_C_LABEL};text-transform:uppercase;
              letter-spacing:0.05em;margin-bottom:4px;">{label}</div>
  <div style="font-size:20px;font-weight:700;color:{color};">{value}</div>
</td>""")
    return f'<table style="border-collapse:collapse;"><tr>{"".join(cells)}</tr></table>'


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------

def _render_header(date: str, total_value: float) -> str:
    return f"""
<div class="hdr" style="background:{_C_HEADER_BG};padding:28px 32px;border-radius:8px 8px 0 0;">
  <div style="color:{_C_TEXT_PRIMARY};font-size:22px;font-weight:700;margin-bottom:4px;">
    InvestorClaw — End-of-Day Portfolio Report
  </div>
  <div style="color:{_C_NEUTRAL};font-size:13px;">
    {date} &nbsp;|&nbsp; Portfolio Value: {_currency(total_value)}
  </div>
  <div style="color:{_C_LABEL};font-size:11px;margin-top:8px;">
    &#9888; Informational analysis only — not investment advice.
    All data sourced from public market data providers. Consult a licensed advisor before acting.
  </div>
</div>"""


def _render_portfolio_summary(holdings: dict) -> str:
    raw = holdings.get("summary") or holdings.get("data", {}).get("summary", {})
    total   = float(raw.get("total_value", 0))
    net     = float(raw.get("net_value", total))
    equity  = float(raw.get("equity_value", 0))
    bonds   = float(raw.get("bond_value", 0))
    cash    = float(raw.get("cash_value", 0))
    margin  = float(raw.get("margin_value", 0))
    eq_pct  = float(raw.get("equity_pct", 0))
    bd_pct  = float(raw.get("bond_pct", 0))
    ca_pct  = float(raw.get("cash_pct", 0))
    ugl     = float(raw.get("unrealized_gl", 0))
    ugl_pct = float(raw.get("unrealized_gl_pct", 0)) / 100.0

    kpis = [
        ("Total Value", _currency(total), _C_ACCENT),
        ("Net Value", _currency(net), _C_ACCENT),
        ("Unrealized G/L", f"{_currency(ugl)} ({_signed(ugl_pct)})", _sign_color(ugl)),
    ]
    kpi_row = _kpi_row(kpis)

    alloc_rows = []
    for label, val, pct in [
        ("Equities", equity, eq_pct),
        ("Bonds", bonds, bd_pct),
        ("Cash", cash, ca_pct),
    ]:
        if val != 0:
            bar_w = max(2, int(pct * 1.5))
            alloc_rows.append(f"""
<tr>
  <td style="padding:4px 8px 4px 0;font-size:12px;color:{_C_LABEL};white-space:nowrap;width:70px;">{label}</td>
  <td class="bar-cell" style="padding:4px 8px;">
    <div style="background:{_C_BORDER};border-radius:3px;height:8px;width:150px;">
      <div style="background:{_C_ACCENT};border-radius:3px;height:8px;width:{bar_w}px;"></div>
    </div>
  </td>
  <td style="padding:4px 0 4px 8px;font-size:12px;font-weight:600;white-space:nowrap;color:{_C_TEXT_PRIMARY};">
    {_pct(pct/100)} &nbsp; {_currency(val)}
  </td>
</tr>""")

    if margin != 0:
        alloc_rows.append(f"""
<tr>
  <td style="padding:4px 8px 4px 0;font-size:12px;color:{_C_NEGATIVE};white-space:nowrap;">Margin</td>
  <td></td>
  <td style="padding:4px 0 4px 8px;font-size:12px;font-weight:600;color:{_C_NEGATIVE};">
    ({_currency(abs(margin))})
  </td>
</tr>""")

    alloc_table = f'<table style="border-collapse:collapse;margin-top:12px;">{"".join(alloc_rows)}</table>'

    return _card(kpi_row + alloc_table)


def _render_top_holdings(holdings: dict, analyst_data: Optional[dict]) -> str:
    top_equity: List[dict] = holdings.get("top_equity", [])
    if not top_equity:
        return ""

    recs = {}
    if analyst_data:
        recs = analyst_data.get("recommendations", {})

    header = (
        _th("Symbol") + _th("Sector") + _th("Value") + _th("Weight") +
        _th("Gain/Loss") + _th("Analyst Consensus")
    )
    rows = []
    for pos in top_equity[:10]:
        sym    = pos.get("symbol", "")
        sector = pos.get("sector", "—")
        value  = float(pos.get("value", 0))
        weight = float(pos.get("weight_pct", 0))
        gl_pct = float(pos.get("gl_pct", 0)) / 100.0

        rec       = recs.get(sym, {})
        consensus = rec.get("consensus", "—") if rec else "—"
        target    = float(rec.get("target_price_mean", 0) or 0) if rec else 0
        current   = float(rec.get("current_price", 0) or 0) if rec else 0

        upside_str = ""
        if target > 0 and current > 0:
            upside = (target - current) / current
            upside_str = (
                f'<div style="font-size:10px;color:{_sign_color(upside)};">'
                f'Target: ${target:.0f} ({_signed(upside, 0)})</div>'
            )

        consensus_lower = (consensus or "").lower()
        consensus_color = (
            _C_POSITIVE if consensus_lower in ("buy", "strong buy")
            else _C_NEGATIVE if consensus_lower in ("sell", "strong sell")
            else _C_NEUTRAL
        )

        rows.append(f"""<tr>
  {_td(f'<strong style="color:{_C_TEXT_PRIMARY};">{sym}</strong>')}
  {_td(sector, f'color:{_C_LABEL};font-size:12px;')}
  {_td(_currency(value))}
  {_td(f'{weight:.1f}%')}
  {_td(f'<span style="color:{_sign_color(gl_pct)};font-weight:600;">{_signed(gl_pct)}</span>')}
  {_td(f'<span style="color:{consensus_color};font-weight:600;">{consensus}</span>{upside_str}')}
</tr>""")

    return _section("Top Holdings", _card(_table(rows, header)))


def _render_analyst_summary(analyst: dict) -> str:
    cov = analyst.get("analyst_coverage", {})
    s   = analyst.get("summary", {})

    strong_pct = 0
    mod_pct    = 0
    total_sym  = int(s.get("total_symbols", 0))
    if total_sym > 0:
        strong_pct = int(cov.get("strong_coverage", 0)) / total_sym * 100
        mod_pct    = int(cov.get("moderate_coverage", 0)) / total_sym * 100

    kpis = [
        ("Symbols Analyzed", str(total_sym), _C_ACCENT),
        ("Strong Coverage", f"{int(cov.get('strong_coverage', 0))} ({strong_pct:.0f}%)", _C_POSITIVE),
        ("Moderate Coverage", f"{int(cov.get('moderate_coverage', 0))} ({mod_pct:.0f}%)", _C_ACCENT),
        ("No Coverage", str(int(cov.get("no_coverage", 0))), _C_NEUTRAL),
    ]
    return _section("Analyst Coverage", _card(_kpi_row(kpis)))


def _render_news_summary(news: dict) -> str:
    posture   = news.get("posture", "Neutral")
    narrative = news.get("narrative", "") or ""
    tailwinds: List[str] = news.get("key_tailwinds", []) or []
    risks: List[str]     = news.get("key_risks", []) or []
    top_pos: List[dict]  = news.get("top_positive", []) or []
    top_neg: List[dict]  = news.get("top_negative", []) or []

    # Build URL + symbol lookup from top_positive / top_negative so tailwinds
    # and risks can be rendered as clickable links.
    url_map: Dict[str, str] = {}
    sym_map: Dict[str, str] = {}
    for item in top_pos + top_neg:
        url = (item.get("url") or item.get("link") or "").strip()
        sym = item.get("symbol", "")
        t   = item.get("title", "")
        if t:
            url_map[t]      = url
            sym_map[t]      = sym
            # compact serializer truncates titles to 80 chars — index both forms
            url_map[t[:80]] = url
            sym_map[t[:80]] = sym

    posture_color = (
        _C_POSITIVE if posture.lower() in ("bullish", "positive")
        else _C_NEGATIVE if posture.lower() in ("bearish", "negative", "cautious")
        else _C_NEUTRAL
    )

    posture_badge = (
        f'<span style="display:inline-block;padding:3px 10px;border-radius:12px;'
        f'background:{posture_color}25;color:{posture_color};font-weight:700;'
        f'border:1px solid {posture_color}50;'
        f'font-size:12px;">{posture.upper()}</span>'
    )

    narrative_html = (
        f'<p style="font-size:13px;color:{_C_TEXT_BODY};margin:10px 0;line-height:1.6;">{narrative}</p>'
        if narrative else ""
    )

    def _news_item_card(item: dict, color: str) -> str:
        title = item.get("title", "")
        url   = (item.get("url") or item.get("link") or "").strip()
        title_html = (
            f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
            f'style="color:{_C_ACCENT};text-decoration:underline;">{title}</a>'
            if url else f'<span style="color:{_C_TEXT_BODY};">{title}</span>'
        )
        impact_val = item.get("impact", "")
        impact_html = (
            f'<div style="font-size:11px;color:{_C_LABEL};margin-top:2px;">'
            f'Portfolio impact: {_currency(float(impact_val))}</div>'
            if impact_val and impact_val != "" else ""
        )
        return (
            f'<div style="margin-bottom:8px;padding:8px 10px;border-radius:4px;'
            f'border-left:3px solid {color};background:{color}18;">'
            f'<div style="font-size:12px;font-weight:600;">'
            f'<span style="color:{_C_LABEL};">[{item.get("symbol","?")}]</span> '
            f'{title_html}</div>'
            f'{impact_html}'
            f'</div>'
        )

    def _linked_li(title: str, color: str) -> str:
        url = url_map.get(title) or url_map.get(title[:80]) or ""
        sym = sym_map.get(title) or sym_map.get(title[:80]) or ""
        sym_tag = (
            f'<span style="font-size:10px;font-weight:700;color:{_C_LABEL};">[{sym}]</span> '
            if sym else ""
        )
        link = (
            f'<a href="{url}" target="_blank" rel="noopener noreferrer" '
            f'style="color:{_C_ACCENT};text-decoration:underline;">{title}</a>'
            if url else f'<span style="color:{_C_TEXT_BODY};">{title}</span>'
        )
        return f'<li style="margin-bottom:6px;line-height:1.5;">{sym_tag}{link}</li>'

    pos_items = "".join(_news_item_card(i, _C_POSITIVE) for i in top_pos[:3])
    neg_items = "".join(_news_item_card(i, _C_NEGATIVE) for i in top_neg[:3])

    tails_html = ""
    if tailwinds:
        items = "".join(_linked_li(t, _C_POSITIVE) for t in tailwinds[:4])
        tails_html = (
            f'<div style="color:{_C_POSITIVE};font-weight:600;font-size:12px;'
            f'text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px;">&#8679; Tailwinds</div>'
            f'<ul style="margin:0 0 0 0;padding-left:18px;font-size:12px;">{items}</ul>'
        )

    risks_html = ""
    if risks:
        items = "".join(_linked_li(r, _C_NEGATIVE) for r in risks[:4])
        risks_html = (
            f'<div style="color:{_C_NEGATIVE};font-weight:600;font-size:12px;'
            f'text-transform:uppercase;letter-spacing:0.05em;margin-top:14px;margin-bottom:6px;">&#8681; Risks</div>'
            f'<ul style="margin:0 0 0 0;padding-left:18px;font-size:12px;">{items}</ul>'
        )

    two_col = f"""
<table style="width:100%;border-collapse:collapse;margin-top:14px;">
<tr>
  <td class="tw-l" style="width:50%;padding-right:12px;vertical-align:top;">
    <div style="font-size:11px;font-weight:600;color:{_C_POSITIVE};margin-bottom:6px;
                text-transform:uppercase;letter-spacing:0.05em;">Top Positive</div>
    {pos_items or f'<div style="color:{_C_NEUTRAL};font-size:12px;">No items</div>'}
  </td>
  <td class="tw-r" style="width:50%;padding-left:12px;vertical-align:top;
                           border-left:1px solid {_C_BORDER};">
    <div style="font-size:11px;font-weight:600;color:{_C_NEGATIVE};margin-bottom:6px;
                text-transform:uppercase;letter-spacing:0.05em;">Top Negative</div>
    {neg_items or f'<div style="color:{_C_NEUTRAL};font-size:12px;">No items</div>'}
  </td>
</tr>
</table>"""

    content = _card(
        f"<div style='margin-bottom:12px;'>{posture_badge}</div>"
        + narrative_html
        + tails_html
        + risks_html
        + two_col
    )
    return _section("Market &amp; Portfolio News", content)


def _render_bond_summary(bonds: Optional[dict]) -> str:
    if not bonds:
        return ""
    bd = bonds.get("data", {})
    ps = bd.get("portfolio_summary", {})

    total_val    = float(ps.get("total_value", 0))
    bond_count   = int(ps.get("bond_count", 0))
    avg_ytm      = float(ps.get("weighted_avg_ytm", 0) or 0)
    avg_duration = float(ps.get("weighted_avg_duration", 0) or 0)
    avg_coupon   = float(ps.get("weighted_avg_coupon", 0) or 0)
    dur_risk     = ps.get("duration_risk", "N/A")
    avg_credit   = ps.get("average_credit_quality", "N/A")
    tax_savings  = float(ps.get("total_annual_muni_tax_savings", 0) or 0)

    if not bond_count:
        return ""

    kpis = [
        ("Bonds", str(bond_count), _C_ACCENT),
        ("Total Value", _currency(total_val), _C_ACCENT),
        ("Avg YTM", f"{avg_ytm:.2f}%", _C_ACCENT),
        ("Avg Duration", f"{avg_duration:.1f}yr", _C_NEUTRAL),
        ("Avg Coupon", f"{avg_coupon:.2f}%", _C_NEUTRAL),
        ("Duration Risk", dur_risk, _C_HIGH if dur_risk.lower() == "high" else _C_NEUTRAL),
    ]
    kpi_row = _kpi_row(kpis)

    extras = []
    if avg_credit:
        extras.append(
            f'<span style="font-size:12px;color:{_C_LABEL};">Avg Credit: '
            f'<strong style="color:{_C_TEXT_PRIMARY};">{avg_credit}</strong></span>'
        )
    if tax_savings >= 500:
        extras.append(
            f'<span style="font-size:12px;color:{_C_POSITIVE};">'
            f'Est. Annual Muni Tax Savings: <strong>{_currency(tax_savings)}</strong></span>'
        )

    extras_html = (
        '<div style="margin-top:12px;">' +
        f' &nbsp;<span style="color:{_C_BORDER};">|</span>&nbsp; '.join(extras) +
        '</div>'
    ) if extras else ""

    ladder: dict = ps.get("maturity_ladder", {}) or {}
    ladder_rows = []
    for bucket, info in sorted(ladder.items()):
        cnt   = int(info.get("count", 0))
        pct   = float(info.get("pct", 0))
        bar_w = max(2, int(pct * 1.5))
        ladder_rows.append(f"""
<tr>
  <td style="padding:3px 8px 3px 0;font-size:12px;color:{_C_LABEL};white-space:nowrap;width:60px;">{bucket}</td>
  <td class="bar-cell" style="padding:3px 8px;">
    <div style="background:{_C_BORDER};border-radius:3px;height:6px;width:120px;">
      <div style="background:{_C_ACCENT};border-radius:3px;height:6px;width:{bar_w}px;"></div>
    </div>
  </td>
  <td style="padding:3px 0 3px 8px;font-size:12px;white-space:nowrap;color:{_C_TEXT_BODY};">{pct:.0f}% ({cnt})</td>
</tr>""")

    ladder_html = (
        f'<div style="margin-top:12px;font-size:11px;font-weight:600;color:{_C_LABEL};'
        f'text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px;">Maturity Ladder</div>'
        + f'<table style="border-collapse:collapse;">{"".join(ladder_rows)}</table>'
    ) if ladder_rows else ""

    return _section("Fixed Income", _card(kpi_row + extras_html + ladder_html))


def _render_performance_summary(performance: dict) -> str:
    pd_data  = performance.get("data", {})
    ps       = pd_data.get("portfolio_summary", {})
    w_vol    = float(ps.get("weighted_volatility", 0) or 0)
    w_sharpe = float(ps.get("weighted_sharpe", 0) or 0)
    period   = pd_data.get("period", "N/A")
    analyzed = int(pd_data.get("holdings_analyzed", 0))
    valid    = int(pd_data.get("holdings_valid", 0))

    sharpe_color = _C_POSITIVE if w_sharpe >= 1.0 else _C_MEDIUM if w_sharpe >= 0.5 else _C_NEGATIVE

    kpis = [
        ("Period Start", str(period), _C_ACCENT),
        ("Symbols Analyzed", f"{valid}/{analyzed}", _C_ACCENT),
        ("Portfolio Volatility", f"{w_vol:.0%} ann.", _C_HIGH if w_vol >= 0.40 else _C_NEUTRAL),
        ("Portfolio Sharpe", f"{w_sharpe:.2f}", sharpe_color),
    ]
    return _section("Performance Metrics", _card(_kpi_row(kpis)))


def _render_fa_topics(fa_topics: List[dict]) -> str:
    if not fa_topics:
        return ""

    items_html = []
    for topic in fa_topics:
        priority = topic.get("priority", "low")
        color    = _priority_color(priority)
        label    = _priority_label(priority)
        cat      = topic.get("category", "").upper()
        title    = topic.get("title", "")
        detail   = topic.get("detail", "")
        metric   = topic.get("metric")

        metric_badge = (
            f'<span style="float:right;font-size:10px;background:{color}25;color:{color};'
            f'padding:2px 8px;border-radius:10px;font-weight:600;border:1px solid {color}40;">'
            f'{metric}</span>'
        ) if metric else ""

        items_html.append(f"""
<div style="margin-bottom:12px;padding:12px 14px;border-radius:6px;
            border-left:4px solid {color};background:{color}12;">
  <div style="margin-bottom:5px;">
    {metric_badge}
    <span style="font-size:10px;font-weight:700;color:{color};text-transform:uppercase;
                 letter-spacing:0.06em;margin-right:6px;">[{label}] {cat}</span>
    <span style="font-size:13px;font-weight:600;color:{_C_TEXT_PRIMARY};">{title}</span>
  </div>
  <div style="font-size:12px;color:{_C_TEXT_BODY};line-height:1.6;">{detail}</div>
</div>""")

    return _section(
        f"FA Discussion Topics ({len(fa_topics)} Items)",
        _card("".join(items_html))
    )


def _render_disclaimer() -> str:
    return f"""
<div style="margin-top:24px;padding:16px;background:{_C_CARD};border-radius:6px;
            border:1px solid {_C_BORDER};">
  <div style="font-size:10px;color:{_C_DISCLAIMER};line-height:1.6;">
    <strong style="color:{_C_LABEL};">DISCLAIMER:</strong> This report is generated by InvestorClaw for
    informational and educational purposes only. It does NOT constitute investment advice, a recommendation
    to buy or sell any security, or a solicitation of any investment. All data is sourced from publicly
    available market data providers (Yahoo Finance, Finnhub, etc.) and may be delayed, incomplete, or
    inaccurate. Past performance is not indicative of future results. InvestorClaw is NOT a registered
    investment advisor. Consult a licensed financial professional before making any investment decisions.
    Market data as of market close on the report date.
  </div>
</div>"""


def _render_footer(run_duration_s: float) -> str:
    gen_note = "Generated by InvestorClaw"
    if run_duration_s > 0:
        gen_note += f" (analysis completed in {run_duration_s:.0f}s)"

    return f"""
<div style="text-align:center;padding:16px;color:{_C_DISCLAIMER};font-size:11px;">
  {gen_note}
</div>"""


# ---------------------------------------------------------------------------
# Mobile media-query stylesheet
# ---------------------------------------------------------------------------

_MOBILE_CSS = f"""
/* ── Mobile overrides (max-width: 600px) ─────────────────────────────── */
@media only screen and (max-width: 600px) {{
  /* Outer wrapper */
  .wrapper {{
    margin: 0 !important;
    width: 100% !important;
    max-width: 100% !important;
    border-radius: 0 !important;
  }}
  /* Header */
  .hdr {{
    padding: 20px 16px !important;
    border-radius: 0 !important;
  }}
  /* Inner content area */
  .inner-pad {{
    padding: 16px 12px !important;
  }}
  /* 2-column news layout → stack vertically */
  .tw-l, .tw-r {{
    display: block !important;
    width: 100% !important;
    box-sizing: border-box !important;
    padding-left: 0 !important;
    padding-right: 0 !important;
    border-left: none !important;
  }}
  .tw-l {{ padding-bottom: 16px !important; }}
  .tw-r {{ padding-top: 12px !important; border-top: 1px solid {_C_BORDER} !important; }}
  /* Hide visual bar charts on mobile to save width */
  .bar-cell {{ display: none !important; }}
  /* KPI cells: wrap on very small screens */
  .kpi-cell {{
    display: block !important;
    padding: 6px 0 !important;
  }}
  /* Table font size */
  table {{ font-size: 12px !important; }}
  /* Section headers */
  h2, h3 {{ font-size: 14px !important; }}
}}
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def render_eod_email(report_data: Dict[str, Any]) -> str:
    """
    Render the EOD report as a self-contained HTML string.

    Parameters
    ----------
    report_data : dict
        Keys: date, holdings, analyst, news, bonds (optional), performance,
              fa_topics, run_duration_s
    """
    date           = report_data.get("date", "")
    holdings       = report_data.get("holdings", {})
    analyst        = report_data.get("analyst", {})
    news           = report_data.get("news", {})
    bonds          = report_data.get("bonds")
    performance    = report_data.get("performance", {})
    fa_topics      = report_data.get("fa_topics", [])
    run_duration_s = float(report_data.get("run_duration_s", 0))

    raw         = holdings.get("summary") or holdings.get("data", {}).get("summary", {})
    total_value = float(raw.get("total_value", 0))

    body_parts = [
        _render_portfolio_summary(holdings),
        _render_top_holdings(holdings, analyst),
        _render_analyst_summary(analyst),
        _render_news_summary(news),
        _render_bond_summary(bonds),
        _render_performance_summary(performance),
        _render_fa_topics(fa_topics),
        _render_disclaimer(),
        _render_footer(run_duration_s),
    ]
    body = "\n".join(p for p in body_parts if p)

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,maximum-scale=1">
  <meta name="color-scheme" content="dark">
  <meta name="supported-color-schemes" content="dark">
  <title>InvestorClaw EOD Report \u2014 {date}</title>
  <style type="text/css">
{_MOBILE_CSS}
  </style>
</head>
<body style="margin:0;padding:0;background:{_C_BG};font-family:{_FONT_STACK};color:{_C_TEXT_BODY};">
  <div class="wrapper" style="max-width:680px;margin:24px auto;border-radius:8px;
              border:1px solid {_C_BORDER};
              box-shadow:0 4px 16px rgba(0,0,0,0.5);overflow:hidden;">
    {_render_header(date, total_value)}
    <div class="inner-pad" style="padding:24px 28px;background:{_C_BG};">
      {body}
    </div>
  </div>
</body>
</html>"""

    return html
