"""
Canonical schema normalization for InvestorClaw.
Single source of truth to eliminate drift between modules.
Handles multiple formats: legacy schema (equity/bond/cash/margin),
disclaimer-wrapped, and FINOS CDM.
"""

from typing import Dict, Any

CANONICAL_KEYS = {
    "equity": ["equity"],
    "bond": ["bond", "fixed_income"],
    "cash": ["cash"],
    "margin": ["margin"]
}


def normalize_portfolio(data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Normalize portfolio structure to canonical schema.

    Handles:
    - Legacy schema: portfolio.equity, portfolio.bond, etc.
    - Disclaimer-wrapped: { "data": { "portfolio": {...} } }
    - FINOS CDM: { "cdmVersion": "5.x", "portfolio": { "aggregationParameters": {...}, "portfolioState": { "positions": [...] }, ... } }

    Returns canonical format: { "portfolio": { "equity": {...}, "bond": {...}, "cash": {...}, "margin": {...} } }
    """

    # Handle FINOS CDM format first
    if "cdmVersion" in data and "portfolio" in data:
        portfolio_cdm = data["portfolio"]
        if "portfolioState" in portfolio_cdm and "positions" in portfolio_cdm["portfolioState"]:
            # Convert CDM positions to canonical schema
            canonical_portfolio = {
                "equity": {},
                "bond": {},
                "cash": {},
                "margin": {}
            }

            for position in portfolio_cdm["portfolioState"]["positions"]:
                # Extract symbol from product identifier
                symbol = ""
                if "product" in position and "productIdentifier" in position["product"]:
                    symbol = position["product"]["productIdentifier"].get("identifier", "")

                if not symbol and "asset" in position and "productIdentifier" in position["asset"]:
                    symbol = position["asset"]["productIdentifier"].get("identifier", "")

                if not symbol:
                    continue

                # Determine asset type from security_type
                asset_type = "equity"  # default
                if "asset" in position:
                    security_type = position["asset"].get("securityType", "").lower()
                    if "bond" in security_type:
                        asset_type = "bond"
                    elif "cash" in security_type:
                        asset_type = "cash"

                # Build canonical holding entry
                entry = {}
                if "priceQuantity" in position:
                    pq = position["priceQuantity"]
                    if "quantity" in pq:
                        entry["shares"] = pq["quantity"].get("amount", 0.0)
                    if "currentPrice" in pq:
                        entry["current_price"] = pq["currentPrice"].get("amount", 0.0)
                    if "costBasisPrice" in pq:
                        entry["purchase_price"] = pq["costBasisPrice"].get("amount", 0.0)

                entry["market_value"] = position.get("marketValue", 0.0)
                entry["cost_basis"] = position.get("costBasis", 0.0)
                entry["unrealized_gain_loss"] = position.get("unrealizedGainLoss", 0.0)
                entry["unrealized_gain_loss_pct"] = position.get("unrealizedGainLossPct", 0.0)

                # For fixed-income positions: preserve price-as-%-of-par and face value
                # CDM currentPrice.amount IS the clean price as % of par (e.g. 99.769, 113.599)
                # CDM quantity.amount IS the face/par value of the position
                if "priceQuantity" in position:
                    pq = position["priceQuantity"]
                    cp_amount = pq.get("currentPrice", {}).get("amount")
                    qty_amount = pq.get("quantity", {}).get("amount")
                    if cp_amount is not None and 0 < cp_amount <= 200:
                        entry["price_percent"] = cp_amount
                    if qty_amount is not None:
                        entry["par_value"] = qty_amount

                if "asset" in position:
                    asset = position["asset"]
                    entry["sector"] = asset.get("sector")
                    entry["cusip"] = asset.get("cusip")
                    entry["isin"] = asset.get("isin")
                    entry["security_name"] = asset.get("securityName", "")

                canonical_portfolio[asset_type][symbol] = entry

            # Preserve CDM summary so _get_summary() can find it post-normalization
            cdm_summary = portfolio_cdm.get("summary", {})
            if cdm_summary:
                canonical_portfolio["summary"] = cdm_summary

            return {
                **data,
                "portfolio": canonical_portfolio
            }

    # Handle disclaimer-wrapped format
    if "data" in data and isinstance(data["data"], dict):
        data = data["data"]

    portfolio = data.get("portfolio", {})

    normalized = {
        "equity": {},
        "bond": {},
        "cash": {},
        "margin": {}
    }

    for canonical, aliases in CANONICAL_KEYS.items():
        for alias in aliases:
            if alias in portfolio and isinstance(portfolio[alias], dict):
                normalized[canonical].update(portfolio[alias])

    return {
        **data,
        "portfolio": normalized
    }


def validate_portfolio(data: Dict[str, Any]) -> None:
    """
    Validate portfolio structure is correct.
    Accepts CDM format or canonical schema.
    """
    # CDM format is valid if it has cdmVersion AND portfolio.portfolioState
    # (after normalize_portfolio() the cdmVersion key remains but portfolioState
    # is replaced by equity/bond/cash/margin — fall through to canonical check)
    if "cdmVersion" in data:
        portfolio = data.get("portfolio", {})
        if "portfolioState" in portfolio:
            # Raw CDM, not yet normalized
            return

    # Canonical format must have all keys
    if "portfolio" not in data:
        raise ValueError("Missing portfolio key")

    for key in ["equity", "bond", "cash", "margin"]:
        if key not in data["portfolio"]:
            raise ValueError(f"Missing portfolio.{key}")
