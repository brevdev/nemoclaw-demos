#!/usr/bin/env python3
"""
commands/fa_discussion.py — FA Discussion Topic Extractor

Reads today's JSON report outputs and surfaces actionable discussion items
an investor might want to bring up with their Financial Advisor.

Topics are derived purely from existing analysis outputs — no new market
data is fetched, no LLM is invoked.  All thresholds are heuristic and
educational; this is NOT financial advice.

Output schema (as JSON list):
  [
    {
      "category": "concentration|allocation|performance|analyst|news|bonds|tax",
      "priority": "high|medium|low",
      "title": "<one-line summary>",
      "detail": "<2-3 sentence explanation>",
      "metric": "<key metric value, optional>"
    },
    ...
  ]
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load(path: Path) -> Optional[dict]:
    """Load JSON from *path*, return None on any error."""
    try:
        with open(path) as fh:
            return json.load(fh)
    except Exception:
        return None


def _fmt_pct(v: float) -> str:
    return f"{v:.1%}"


def _fmt_currency(v: float) -> str:
    return f"${v:,.0f}"


# ---------------------------------------------------------------------------
# Per-source extractors
# ---------------------------------------------------------------------------

def _topics_from_holdings(data: dict) -> List[dict]:
    topics: List[dict] = []

    raw = data.get("summary") or data.get("data", {}).get("summary", {})
    top_equity: List[dict] = data.get("top_equity", [])
    sector_weights: dict = data.get("sector_weights", {})
    sector_weights_ex_espp: dict = data.get("sector_weights_ex_espp", {})
    espp_sector_pct: dict = data.get("espp_sector_pct", {})

    total_value = float(raw.get("total_value", 0))
    equity_pct  = float(raw.get("equity_pct", 0))
    bond_pct    = float(raw.get("bond_pct", 0))
    cash_pct    = float(raw.get("cash_pct", 0))
    margin_val  = float(raw.get("margin_value", 0))
    # unrealized_gl_pct may be stored as a percentage (e.g. -96.58) or decimal (-0.9658)
    _ugl_pct_raw = float(raw.get("unrealized_gl_pct", 0))
    # Normalise: values outside (-1.0, 1.0) are already in percentage form
    unrealized_pct = _ugl_pct_raw / 100.0 if abs(_ugl_pct_raw) > 1.0 else _ugl_pct_raw
    unrealized_gl  = float(raw.get("unrealized_gl", 0))

    # --- Single-position concentration ---
    for pos in top_equity:
        w = float(pos.get("weight_pct", 0))
        is_espp = bool(pos.get("espp_status"))
        if w >= 10.0:
            espp_note = (
                " This position is held as ESPP shares, which may carry vesting schedules, "
                "holding period requirements, or tax treatment that differs from open-market purchases. "
                "Discuss concentration reduction strategy and any lockup constraints."
                if is_espp else
                " Concentrated positions amplify both upside and downside. "
                "Discuss whether the current weight aligns with your risk tolerance and whether "
                "any rebalancing is appropriate."
            )
            topics.append({
                "category": "concentration",
                "priority": "high" if w >= 20.0 else "medium",
                "title": f"{pos['symbol']} represents {w:.1f}% of the portfolio"
                         + (" (ESPP)" if is_espp else ""),
                "detail": (
                    f"{pos['symbol']} is your largest single holding at {w:.1f}% of total value "
                    f"({_fmt_currency(float(pos.get('value', 0)))}).{espp_note}"
                ),
                "metric": f"{w:.1f}% weight" + (" · ESPP" if is_espp else ""),
            })

    # --- Sector concentration (ESPP-aware) ---
    for sector, pct in sorted(sector_weights.items(), key=lambda x: -x[1]):
        pct_f = float(pct)
        if pct_f < 30.0:
            continue
        espp_pct = float(espp_sector_pct.get(sector, 0))
        organic_pct = float(sector_weights_ex_espp.get(sector, pct_f))
        if espp_pct > 0:
            detail = (
                f"Your {sector} sector exposure is {pct_f:.1f}% of equity holdings, "
                f"of which {espp_pct:.1f}% is from ESPP-held positions (vesting/liquidity constrained) "
                f"and {organic_pct:.1f}% is from discretionary holdings. "
                f"The organic (non-ESPP) concentration alone is {organic_pct:.1f}%. "
                f"Discuss the vesting timeline for ESPP shares and whether a diversification plan "
                f"is appropriate as shares vest or holding periods expire."
            )
            metric = f"{pct_f:.1f}% total · {espp_pct:.1f}% ESPP · {organic_pct:.1f}% organic"
        else:
            detail = (
                f"Your {sector} sector exposure is {pct_f:.1f}% of equity holdings. "
                f"High sector concentration increases sensitivity to sector-specific events "
                f"(regulatory changes, earnings cycles, interest rate sensitivity). "
                f"Consider whether this reflects a deliberate overweight or drift that needs rebalancing."
            )
            metric = f"{pct_f:.1f}% sector weight"
        topics.append({
            "category": "concentration",
            "priority": "high" if pct_f >= 40.0 else "medium",
            "title": f"Sector concentration: {sector} at {pct_f:.1f}%"
                     + (f" ({espp_pct:.1f}% ESPP)" if espp_pct > 0 else ""),
            "detail": detail,
            "metric": metric,
        })

    # --- Asset allocation extremes ---
    if equity_pct >= 90.0 and total_value > 0:
        topics.append({
            "category": "allocation",
            "priority": "medium",
            "title": f"Portfolio is {equity_pct:.0f}% equities — minimal fixed-income buffer",
            "detail": (
                f"With {equity_pct:.0f}% in equities, the portfolio has limited downside cushion "
                f"from bonds or cash. Discuss whether this allocation fits your time horizon and "
                f"whether adding fixed income or alternatives would reduce overall volatility."
            ),
            "metric": f"{equity_pct:.0f}% equity",
        })
    elif bond_pct >= 80.0 and total_value > 0:
        topics.append({
            "category": "allocation",
            "priority": "medium",
            "title": f"Portfolio is {bond_pct:.0f}% fixed income — limited growth exposure",
            "detail": (
                f"With {bond_pct:.0f}% in bonds, the portfolio may underperform equity markets "
                f"in bull cycles and faces reinvestment risk as bonds mature. "
                f"Discuss whether the current allocation serves your income and growth objectives."
            ),
            "metric": f"{bond_pct:.0f}% bonds",
        })

    # --- Margin debt ---
    if margin_val > 0:
        topics.append({
            "category": "allocation",
            "priority": "high",
            "title": f"Margin debt balance: {_fmt_currency(abs(margin_val))}",
            "detail": (
                f"There is an outstanding margin balance of {_fmt_currency(abs(margin_val))}. "
                f"Margin amplifies losses in declining markets and incurs interest charges. "
                f"Discuss your margin utilization strategy, current interest rate on the balance, "
                f"and whether a planned paydown timeline is in place."
            ),
            "metric": _fmt_currency(abs(margin_val)),
        })

    # --- Account-type breakdown (401K, IRA, Roth, Brokerage, Managed) ---
    accounts: dict = data.get("accounts", {})
    if accounts and total_value > 0:
        _type_labels = {
            'ira': 'IRA', 'roth_ira': 'Roth IRA', 'sep_ira': 'SEP IRA',
            '401k': '401(K)', 'brokerage': 'Brokerage',
            'taxable': 'Taxable', 'etf_bundle': 'ETF Bundle',
        }
        # Group by financial type; track managed value separately
        _type_totals: dict = {}
        _managed_value = 0.0
        _self_directed_value = 0.0
        for acct_name, acct_data in accounts.items():
            ft  = acct_data.get("financial_type", "taxable")
            val = float(acct_data.get("value", 0))
            _type_totals[ft] = _type_totals.get(ft, 0.0) + val
            if acct_data.get("managed"):
                _managed_value += val
            else:
                _self_directed_value += val

        if _type_totals:
            parts = [
                f"{_type_labels.get(ft, ft)}: {_fmt_currency(v)} ({v / total_value:.0%})"
                for ft, v in sorted(_type_totals.items(), key=lambda x: -x[1])
            ]
            named_accts = []
            for name, acct_data in list(accounts.items())[:8]:
                mgd_tag = " [Managed]" if acct_data.get("managed") else ""
                named_accts.append(
                    f"{name}{mgd_tag} ({_type_labels.get(acct_data.get('financial_type','?'), '?')}, "
                    f"{_fmt_currency(float(acct_data.get('value',0)))}, "
                    f"{acct_data.get('position_count',0)} positions)"
                )
            managed_note = ""
            if _managed_value > 0:
                managed_note = (
                    f" {_fmt_currency(_managed_value)} ({_managed_value/total_value:.0%}) "
                    f"is in discretionary/advisor-managed strategies — concentration in those "
                    f"accounts reflects advisor allocation, not self-directed decisions. "
                )
            topics.append({
                "category": "allocation",
                "priority": "low",
                "title": "Account structure: " + ", ".join(
                    f"{_type_labels.get(ft, ft)} {v/total_value:.0%}"
                    for ft, v in sorted(_type_totals.items(), key=lambda x: -x[1])
                ),
                "detail": (
                    f"Portfolio spans {len(accounts)} accounts with distinct tax treatment. "
                    f"{'; '.join(parts)}.{managed_note} "
                    f"Named accounts: {'; '.join(named_accts)}. "
                    f"Review that asset location strategy (placing tax-inefficient holdings in "
                    f"tax-advantaged accounts) is being applied appropriately."
                ),
                "metric": " · ".join(
                    f"{_type_labels.get(ft, ft)} {v/total_value:.0%}"
                    for ft, v in sorted(_type_totals.items(), key=lambda x: -x[1])
                ) + (" · Managed: " + f"{_managed_value/total_value:.0%}" if _managed_value > 0 else ""),
            })

    # --- Significant unrealized gain/loss ---
    if abs(unrealized_pct) >= 0.15 and abs(unrealized_gl) >= 10_000:
        sign = "gain" if unrealized_gl > 0 else "loss"
        topics.append({
            "category": "performance",
            "priority": "medium",
            "title": (
                f"Significant unrealized {sign}: "
                f"{_fmt_currency(abs(unrealized_gl))} ({_fmt_pct(abs(unrealized_pct))})"
            ),
            "detail": (
                f"The portfolio has an unrealized {sign} of "
                f"{_fmt_currency(abs(unrealized_gl))} ({_fmt_pct(abs(unrealized_pct))}). "
                + (
                    "Harvesting losses before year-end may offset taxable gains. "
                    "Discuss tax-loss harvesting candidates and wash-sale rule constraints with your FA."
                    if unrealized_gl < 0 else
                    "Significant unrealized gains may create a tax liability upon sale. "
                    "Discuss whether any positions should be trimmed and whether gifting "
                    "appreciated shares or a donor-advised fund makes sense."
                )
            ),
            "metric": f"{_fmt_pct(unrealized_pct)} unrealized",
        })

    return topics


def _topics_from_analyst(recommendations: dict, top_equity: List[dict]) -> List[dict]:
    topics: List[dict] = []

    # Build lookup of top equity symbols by weight for context
    top_symbols = {e["symbol"]: float(e.get("weight_pct", 0)) for e in top_equity}

    sells: List[tuple] = []
    wide_gap: List[tuple] = []    # target/current gap > 30%
    divergent: List[tuple] = []   # high analyst count but mixed ratings

    for sym, rec in recommendations.items():
        consensus = rec.get("consensus", "") or ""
        count = int(rec.get("analyst_count", 0) or 0)
        current = float(rec.get("current_price", 0) or 0)
        target  = float(rec.get("target_price_mean", 0) or 0)
        buy     = int(rec.get("buy_count", 0) or 0)
        sell    = int(rec.get("sell_count", 0) or 0)
        hold    = int(rec.get("hold_count", 0) or 0)

        if consensus.lower() in ("sell", "strong sell") and count >= 5:
            weight = top_symbols.get(sym, 0)
            sells.append((sym, consensus, count, weight))

        if current > 0 and target > 0 and count >= 5:
            gap_pct = (target - current) / current
            if abs(gap_pct) >= 0.30:
                wide_gap.append((sym, gap_pct, current, target, count))

        if count >= 10 and (buy + sell + hold) > 0:
            total = buy + sell + hold
            sell_pct = sell / total
            if sell_pct >= 0.25:
                divergent.append((sym, buy, hold, sell, total))

    # Emit a single topic grouping sell-rated holdings by weight
    sells_sorted = sorted(sells, key=lambda x: -x[3])
    if sells_sorted:
        names = ", ".join(f"{s[0]} ({s[1]}, {s[2]} analysts)" for s in sells_sorted[:3])
        topics.append({
            "category": "analyst",
            "priority": "high",
            "title": f"Analyst sell consensus on held position(s): {', '.join(s[0] for s in sells_sorted[:3])}",
            "detail": (
                f"The following holdings have a sell or strong-sell analyst consensus: {names}. "
                f"This does not require immediate action, but warrants a discussion of the investment "
                f"thesis for each position and whether the original rationale still holds."
            ),
            "metric": f"{len(sells_sorted)} position(s)",
        })

    # Wide upside gap — potential opportunity
    upside = [(s, g, c, t, n) for s, g, c, t, n in wide_gap if g > 0]
    upside = sorted(upside, key=lambda x: -x[1])[:3]
    if upside:
        top = upside[0]
        topics.append({
            "category": "analyst",
            "priority": "low",
            "title": f"Wide analyst upside target: {top[0]} (+{top[1]:.0%} to ${top[3]:.0f})",
            "detail": (
                f"Analyst consensus has {top[0]} at a mean target of ${top[3]:.0f} vs. current ${top[2]:.0f} "
                f"(+{top[1]:.0%} implied upside, based on {top[4]} analysts). "
                f"Consider whether your current position size reflects your conviction in this upside."
            ),
            "metric": f"+{top[1]:.0%} upside target",
        })

    return topics


def _topics_from_news(news_data: dict) -> List[dict]:
    topics: List[dict] = []

    posture = news_data.get("posture", "neutral") or "neutral"
    _raw_themes = news_data.get("macro_themes", []) or []
    # macro_themes may be a list of dicts (compact serializer) or plain strings
    macro_themes: List[str] = [
        t['theme'] if isinstance(t, dict) else t for t in _raw_themes
    ]
    key_risks: List[str] = news_data.get("key_risks", []) or []
    top_negative: List[dict] = news_data.get("top_negative", []) or []

    if posture.lower() in ("bearish", "cautious") and top_negative:
        neg = top_negative[0]
        topics.append({
            "category": "news",
            "priority": "medium",
            "title": f"Bearish news posture — {neg.get('symbol', 'portfolio')} flagged",
            "detail": (
                f"Today's news analysis indicates a {posture.lower()} stance. "
                f"Top negative item: \"{neg.get('title', '')}\" ({neg.get('symbol', '')}). "
                f"Discuss how current macro headwinds might affect your holdings and whether "
                f"any protective adjustments are warranted."
            ),
            "metric": posture,
        })

    if key_risks:
        risks_str = "; ".join(key_risks[:3])
        topics.append({
            "category": "news",
            "priority": "low",
            "title": f"Identified portfolio risks: {key_risks[0]}" if key_risks else "News risk flags",
            "detail": (
                f"Today's news digest flagged the following risks affecting your holdings: "
                f"{risks_str}. Review whether these risks alter your near-term outlook "
                f"or require positioning adjustments."
            ),
            "metric": f"{len(key_risks)} risk(s) flagged",
        })

    if macro_themes:
        themes_str = ", ".join(macro_themes[:4])
        topics.append({
            "category": "news",
            "priority": "low",
            "title": f"Macro themes active: {themes_str}",
            "detail": (
                f"Key macro themes in today's portfolio news: {themes_str}. "
                f"Discuss how your current allocation positions you relative to these themes "
                f"and whether any tactical adjustments are appropriate."
            ),
            "metric": None,
        })

    return topics


def _topics_from_bonds(bond_data: dict) -> List[dict]:
    topics: List[dict] = []
    ps = bond_data.get("portfolio_summary", {})

    avg_duration = float(ps.get("weighted_avg_duration", 0) or 0)
    avg_ytm      = float(ps.get("weighted_avg_ytm", 0) or 0)
    avg_coupon   = float(ps.get("weighted_avg_coupon", 0) or 0)
    duration_risk = ps.get("duration_risk", "") or ""
    tax_savings   = float(ps.get("total_annual_muni_tax_savings", 0) or 0)
    bond_count    = int(ps.get("bond_count", 0) or 0)
    maturity_ladder: dict = ps.get("maturity_ladder", {}) or {}
    asset_breakdown: dict = ps.get("asset_type_breakdown", {}) or {}
    recommendations: list = ps.get("recommendations", []) or []
    avg_credit    = ps.get("average_credit_quality", "") or ""

    if not bond_count:
        return topics

    # Duration risk
    if avg_duration > 6.0 or duration_risk.lower() == "high":
        topics.append({
            "category": "bonds",
            "priority": "high" if avg_duration > 8.0 else "medium",
            "title": f"Bond portfolio duration: {avg_duration:.1f} years ({duration_risk} interest-rate sensitivity)",
            "detail": (
                f"Your bond portfolio has a weighted average duration of {avg_duration:.1f} years. "
                f"Each 1% rise in interest rates would reduce bond portfolio value by approximately "
                f"{avg_duration:.0f}%. Discuss whether this duration exposure is appropriate given "
                f"your view on the rate environment and your liquidity needs."
            ),
            "metric": f"{avg_duration:.1f}yr duration",
        })

    # YTM vs coupon spread (premium/discount context)
    # Both avg_ytm and avg_coupon are stored in percentage units (e.g. 3.1 = 3.1%)
    if avg_ytm > 0 and avg_coupon > 0:
        ytm_coupon_spread = avg_ytm - avg_coupon  # both in same units
        if abs(ytm_coupon_spread) >= 0.05:  # >5bp difference
            direction = "above coupon" if ytm_coupon_spread > 0 else "below coupon"
            topics.append({
                "category": "bonds",
                "priority": "low",
                "title": f"Bond yield-to-maturity ({avg_ytm:.2f}%) is {direction} ({avg_coupon:.2f}% avg coupon)",
                "detail": (
                    f"The portfolio's weighted average YTM ({avg_ytm:.2f}%) is "
                    f"{'above' if ytm_coupon_spread > 0 else 'below'} the average coupon rate ({avg_coupon:.2f}%). "
                    f"{'Bonds trading at a discount may create capital gains upon maturity.' if ytm_coupon_spread > 0 else 'Premium bonds will return less than face value — factor this into total return projections.'} "
                    f"Discuss reinvestment risk as bonds mature and what rates are likely available then."
                ),
                "metric": f"{avg_ytm:.2f}% YTM",
            })

    # Concentration in single bond type
    for btype, binfo in asset_breakdown.items():
        pct = float(binfo.get("pct", 0))
        if pct >= 80.0:
            topics.append({
                "category": "bonds",
                "priority": "medium",
                "title": f"Bond portfolio is {pct:.0f}% {btype.replace('_', ' ')}",
                "detail": (
                    f"{pct:.0f}% of your bond holdings are {btype.replace('_', ' ')} bonds. "
                    f"High concentration in a single bond type increases exposure to type-specific risks "
                    f"(credit risk, AMT exposure for munis, government credit for treasuries). "
                    f"Discuss whether diversification across bond types is appropriate."
                ),
                "metric": f"{pct:.0f}% {btype}",
            })

    # Municipal tax savings (worth discussing)
    if tax_savings >= 1_000:
        topics.append({
            "category": "tax",
            "priority": "low",
            "title": f"Estimated annual muni tax savings: {_fmt_currency(tax_savings)}",
            "detail": (
                f"Based on the current municipal bond holdings, InvestorClaw estimates approximately "
                f"{_fmt_currency(tax_savings)} in annual federal tax savings from tax-exempt coupon income. "
                f"Discuss whether your tax bracket justifies the muni allocation, and whether the "
                f"tax-equivalent yield is competitive with equivalent taxable bonds."
            ),
            "metric": _fmt_currency(tax_savings),
        })

    # Maturity concentration
    for bucket, binfo in maturity_ladder.items():
        pct = float(binfo.get("pct", 0))
        if pct >= 50.0:
            topics.append({
                "category": "bonds",
                "priority": "low",
                "title": f"Bond maturity concentration in {bucket}: {pct:.0f}%",
                "detail": (
                    f"{pct:.0f}% of the bond portfolio matures in the {bucket} window. "
                    f"Significant maturity bunching creates reinvestment risk — when those bonds mature, "
                    f"you'll need to reinvest at whatever rates prevail. "
                    f"Discuss laddering strategies to spread maturities more evenly."
                ),
                "metric": f"{pct:.0f}% in {bucket}",
            })

    return topics


def _topics_from_performance(perf_data: dict, top_equity: List[dict]) -> List[dict]:
    topics: List[dict] = []

    portfolio_summary = perf_data.get("portfolio_summary", {})
    holdings_perf: dict = perf_data.get("performance", {})

    w_vol   = float(portfolio_summary.get("weighted_volatility", 0) or 0)
    w_sharpe = float(portfolio_summary.get("weighted_sharpe", 0) or 0)

    # Portfolio-level volatility
    if w_vol >= 0.35:
        topics.append({
            "category": "performance",
            "priority": "high" if w_vol >= 0.50 else "medium",
            "title": f"Portfolio annualized volatility: {w_vol:.0%}",
            "detail": (
                f"The value-weighted portfolio volatility is {w_vol:.0%} annualized. "
                f"{'This is high relative to typical diversified equity portfolios (~15-20%).' if w_vol >= 0.40 else 'This is elevated relative to broad market benchmarks.'} "
                f"Discuss whether this volatility level is intentional, and whether diversification "
                f"into lower-correlation assets could reduce overall portfolio risk."
            ),
            "metric": f"{w_vol:.0%} annualized vol",
        })

    # Portfolio Sharpe
    if w_sharpe < 0.3 and w_sharpe > -99:
        topics.append({
            "category": "performance",
            "priority": "medium" if w_sharpe < 0 else "low",
            "title": f"Portfolio Sharpe ratio: {w_sharpe:.2f} (risk-adjusted return)",
            "detail": (
                f"The value-weighted Sharpe ratio is {w_sharpe:.2f}. "
                + (
                    "A negative Sharpe indicates returns have been below the risk-free rate on a risk-adjusted basis."
                    if w_sharpe < 0 else
                    "A Sharpe below 0.5 suggests the portfolio's returns have not well-compensated for the volatility taken."
                ) +
                " Discuss whether concentration in high-volatility names is generating commensurate returns."
            ),
            "metric": f"Sharpe {w_sharpe:.2f}",
        })

    # Find top-equity positions with very high individual volatility
    high_vol_positions = []
    top_syms = {e["symbol"]: float(e.get("weight_pct", 0)) for e in top_equity}
    for sym, pdata in holdings_perf.items():
        if sym not in top_syms:
            continue
        vol_data = pdata.get("volatility", {}) or {}
        if not vol_data.get("_valid"):
            continue
        ann_vol = float(vol_data.get("annualized_volatility", 0) or 0)
        if ann_vol >= 0.70:
            high_vol_positions.append((sym, ann_vol, top_syms[sym]))

    high_vol_positions.sort(key=lambda x: -x[2])
    if high_vol_positions[:3]:
        names = ", ".join(f"{s} ({v:.0%})" for s, v, _ in high_vol_positions[:3])
        topics.append({
            "category": "performance",
            "priority": "medium",
            "title": f"High-volatility top holdings: {', '.join(s for s, _, _ in high_vol_positions[:3])}",
            "detail": (
                f"The following top holdings have annualized volatility above 70%: {names}. "
                f"High individual volatility in significant positions contributes disproportionately "
                f"to portfolio risk. Discuss whether position sizes are appropriate given this volatility, "
                f"and whether stop-loss or covered call strategies are worth considering."
            ),
            "metric": f"{len(high_vol_positions)} high-vol position(s)",
        })

    return topics


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def extract_fa_topics(
    reports_dir: Path,
    preloaded: Optional[dict] = None,
) -> List[dict]:
    """
    Return FA discussion topic dicts sorted by priority (high → medium → low).

    Parameters
    ----------
    reports_dir : Path
        Directory to load JSON outputs from when *preloaded* is not supplied.
    preloaded : dict, optional
        Pre-loaded data dict (e.g. from eod_report's fallback-aware loader).
        Keys: "holdings", "analyst_raw", "news", "bonds", "performance".
        When supplied, file loading is skipped for keys that are present.
    """
    pd = preloaded or {}
    topics: List[dict] = []

    # Holdings
    holdings = pd.get("holdings") or _load(reports_dir / "holdings_summary.json")
    if holdings:
        topics.extend(_topics_from_holdings(holdings))

    # Analyst
    analyst_data = pd.get("analyst_raw") or _load(reports_dir / "analyst_data.json")
    top_equity: List[dict] = holdings.get("top_equity", []) if holdings else []
    if analyst_data:
        recs = analyst_data.get("recommendations", {})
        topics.extend(_topics_from_analyst(recs, top_equity))

    # News
    news = pd.get("news") or _load(reports_dir / "portfolio_news.json")
    if news:
        topics.extend(_topics_from_news(news))

    # Bonds
    bond = pd.get("bonds") or _load(reports_dir / "bond_analysis.json")
    if bond:
        bond_data = bond.get("data", {})
        topics.extend(_topics_from_bonds(bond_data))

    # Performance
    perf = pd.get("performance") or _load(reports_dir / "performance.json")
    if perf:
        perf_data = perf.get("data", {})
        topics.extend(_topics_from_performance(perf_data, top_equity))

    # Sort: high → medium → low
    _order = {"high": 0, "medium": 1, "low": 2}
    topics.sort(key=lambda t: _order.get(t.get("priority", "low"), 2))

    return topics


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import argparse, os

    parser = argparse.ArgumentParser(description="Extract FA discussion topics from portfolio reports")
    parser.add_argument("--reports-dir", help="Path to reports directory (default: today's dated dir)")
    parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    args = parser.parse_args()

    sys.path.insert(0, str(Path(__file__).parent.parent))
    from config.path_resolver import get_reports_dir

    reports_dir = Path(args.reports_dir) if args.reports_dir else get_reports_dir()

    topics = extract_fa_topics(reports_dir)
    indent = 2 if args.pretty else None
    print(json.dumps(topics, indent=indent, default=str))
