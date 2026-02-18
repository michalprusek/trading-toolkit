from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from src.api.client import EtoroClient
from src.api import endpoints
from src.market.data import resolve_symbol, get_rate


@dataclass
class FeeEstimate:
    spread_cost: float
    crypto_fee: float
    overnight_daily: float
    overnight_weekly: float
    overnight_monthly: float
    total_entry_cost: float
    total_1month_cost: float
    cost_pct: float


# eToro overnight fee rates (annual %)
_OVERNIGHT_RATES: dict[str, float] = {
    "stocks": 6.4,
    "crypto": 0.0,  # No overnight for unleveraged crypto
    "crypto_cfd": 5.0,
    "forex": 3.0,
    "commodities": 5.0,
    "indices": 5.0,
    "etf": 6.4,
}

# eToro asset class ID → fee category
_ASSET_CLASS_MAP: dict[int, str] = {
    5: "stocks",
    10: "etf",
    6: "indices",
    3: "forex",
    2: "commodities",
    4: "crypto",
    73: "crypto",
}


def _map_asset_class(asset_class_id: int | str) -> str:
    try:
        return _ASSET_CLASS_MAP.get(int(asset_class_id), "stocks")
    except (ValueError, TypeError):
        return "stocks"


def estimate_fees(
    amount: float,
    spread_pct: float,
    asset_class: str = "stocks",
    leverage: float = 1.0,
    is_short: bool = False,
) -> FeeEstimate:
    if amount <= 0:
        return FeeEstimate(
            spread_cost=0, crypto_fee=0,
            overnight_daily=0, overnight_weekly=0, overnight_monthly=0,
            total_entry_cost=0, total_1month_cost=0, cost_pct=0,
        )

    spread_cost = amount * (spread_pct / 100)

    crypto_fee = 0.0
    if asset_class == "crypto" and leverage <= 1 and not is_short:
        crypto_fee = amount * 0.01  # 1% buy/sell

    # Overnight fees apply to CFDs (leveraged, short, or certain assets)
    is_cfd = leverage > 1 or is_short
    overnight_daily = 0.0
    if is_cfd:
        if asset_class == "crypto":
            annual_rate = _OVERNIGHT_RATES["crypto_cfd"]
        else:
            annual_rate = _OVERNIGHT_RATES.get(asset_class, 6.4)
        notional = amount * leverage
        overnight_daily = notional * (annual_rate / 100) / 365

    overnight_weekly = overnight_daily * 7
    overnight_monthly = overnight_daily * 30

    total_entry_cost = spread_cost + crypto_fee
    total_1month_cost = total_entry_cost + overnight_monthly

    cost_pct = (total_1month_cost / amount * 100) if amount > 0 else 0

    return FeeEstimate(
        spread_cost=round(spread_cost, 2),
        crypto_fee=round(crypto_fee, 2),
        overnight_daily=round(overnight_daily, 2),
        overnight_weekly=round(overnight_weekly, 2),
        overnight_monthly=round(overnight_monthly, 2),
        total_entry_cost=round(total_entry_cost, 2),
        total_1month_cost=round(total_1month_cost, 2),
        cost_pct=round(cost_pct, 4),
    )


def estimate_trade_fees(
    symbol: str,
    amount: float,
    direction: str = "BUY",
    leverage: float = 1.0,
) -> dict[str, Any]:
    info = resolve_symbol(symbol)
    if not info:
        return {"error": f"Instrument '{symbol}' not found"}

    iid = info["instrument_id"]
    rate = get_rate(iid)
    spread_pct = rate.spread_pct if rate else 0.1

    asset_class = _map_asset_class(info.get("type", ""))
    is_short = direction.upper() == "SELL"

    fee = estimate_fees(amount, spread_pct, asset_class, leverage, is_short)

    return {
        "symbol": symbol,
        "amount": amount,
        "direction": direction.upper(),
        "leverage": leverage,
        "asset_class": asset_class,
        "spread_pct": round(spread_pct, 4),
        "price": round(rate.mid, 4) if rate else None,
        "spread_cost": fee.spread_cost,
        "crypto_fee": fee.crypto_fee,
        "overnight_daily": fee.overnight_daily,
        "overnight_weekly": fee.overnight_weekly,
        "overnight_monthly": fee.overnight_monthly,
        "total_entry_cost": fee.total_entry_cost,
        "total_1month_cost": fee.total_1month_cost,
        "cost_pct": fee.cost_pct,
    }
