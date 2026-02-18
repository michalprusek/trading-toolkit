from __future__ import annotations

from typing import Any

from src.api.client import EtoroClient
from src.api import endpoints


_client: EtoroClient | None = None


def _get_client() -> EtoroClient:
    global _client
    if _client is None:
        _client = EtoroClient()
    return _client


def _safe_float(data: dict, key: str) -> float | None:
    val = data.get(key)
    if val is None:
        return None
    try:
        return float(val)
    except (ValueError, TypeError):
        return None


def _safe_int(data: dict, key: str) -> int | None:
    val = data.get(key)
    if val is None:
        return None
    try:
        return int(val)
    except (ValueError, TypeError):
        return None


def get_instrument_fundamentals(symbol: str) -> dict[str, Any]:
    client = _get_client()
    data = client.get(endpoints.SEARCH, internalSymbolFull=symbol)
    items = data.get("items", [])

    if not items:
        return {"error": f"Instrument '{symbol}' not found"}

    # Find exact match or use first result
    item = items[0]
    for i in items:
        if (i.get("internalSymbolFull") or "").upper() == symbol.upper():
            item = i
            break

    return {
        "symbol": item.get("internalSymbolFull", symbol),
        "name": item.get("internalInstrumentDisplayName", ""),
        "instrument_id": item.get("instrumentId") or item.get("internalInstrumentId"),
        "asset_class_id": item.get("internalAssetClassId"),
        "valuation": {
            "pe_ratio": _safe_float(item, "peRatio-TTM"),
            "price_to_book": _safe_float(item, "priceToBook"),
            "price_to_sales": _safe_float(item, "priceToSales"),
            "market_cap": _safe_float(item, "marketCapitalization-TTM"),
            "book_value": _safe_float(item, "bookValue"),
        },
        "profitability": {
            "eps": _safe_float(item, "epS-TTM"),
            "eps_growth_1y": _safe_float(item, "epsGrowth1Year"),
            "revenue": _safe_float(item, "salesOrRevenue-TTM"),
            "net_profit_margin": _safe_float(item, "netProfitMargin"),
            "operating_margin": _safe_float(item, "operatingMargin"),
            "return_on_assets": _safe_float(item, "returnOnAssets"),
            "return_on_equity": _safe_float(item, "returnOnCommonEquity"),
            "free_cash_flow": _safe_float(item, "freeCashFlow"),
        },
        "analyst_ratings": {
            "consensus": item.get("tipranksConsensus"),
            "target_price": _safe_float(item, "tipranksTargetPrice"),
            "target_upside": _safe_float(item, "tipranksTargetPriceUpside"),
            "buy_count": _safe_int(item, "tipranksNumOfBuyRatings"),
            "hold_count": _safe_int(item, "tipranksNumOfHoldRatings"),
            "sell_count": _safe_int(item, "tipranksNumOfSellRatings"),
            "high_target": _safe_float(item, "tipranksHighTarget"),
            "low_target": _safe_float(item, "tipranksLowTarget"),
        },
        "sentiment": {
            "buy_pct": _safe_float(item, "buyHoldingPct"),
            "sell_pct": _safe_float(item, "sellHoldingPct"),
            "holding_pct": _safe_float(item, "holdingPct"),
            "traders_7d_change": _safe_float(item, "traders7dChange"),
            "traders_14d_change": _safe_float(item, "traders14dChange"),
            "traders_30d_change": _safe_float(item, "traders30dChange"),
            "institutional_holding_pct": _safe_float(item, "institutionalHoldingPct"),
        },
        "price_performance": {
            "daily_change": _safe_float(item, "dailyChange"),
            "weekly_change": _safe_float(item, "weeklyChange"),
            "monthly_change": _safe_float(item, "monthlyChange"),
            "high_52w": _safe_float(item, "highPriceLast52Weeks"),
            "low_52w": _safe_float(item, "lowPriceLast52Weeks"),
        },
        "earnings": {
            "next_earnings_date": item.get("nextEarningDate"),
            "days_till_earnings": _safe_int(item, "daysTillNextEarningReport"),
            "quarterly_eps": _safe_float(item, "quarterlyEPSValue"),
            "estimated_quarterly_eps": _safe_float(item, "estimatedQuarterlyEPS"),
            "eps_surprise": _safe_float(item, "quarterlyEPSSurprise"),
        },
        "dividends": {
            "dividend_rate": _safe_float(item, "dividendRate"),
            "dividend_yield": _safe_float(item, "dividendYieldDaily"),
            "ex_date": item.get("dividendExDate"),
            "pay_date": item.get("dividendPayDate"),
        },
        "esg": {
            "total": _safe_float(item, "arabesqueESGTotal"),
            "environment": _safe_float(item, "arabesqueESGEnvironment"),
            "social": _safe_float(item, "arabesqueESGSocial"),
            "governance": _safe_float(item, "arabesqueESGGovernance"),
        },
    }
