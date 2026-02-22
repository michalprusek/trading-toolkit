"""ATR-based stop-loss / take-profit calculation and position sizing."""

from __future__ import annotations

import numpy as np
import pandas as pd

from src.market.indicators import chandelier_exit, supertrend


def calculate_atr_stops(
    price: float,
    atr: float,
    direction: str = "BUY",
    sl_multiplier: float = 2.0,
    tp_multiplier: float = 3.0,
    max_sl_pct: float = 15.0,
    min_sl_pct: float = 1.0,
) -> dict:
    """Calculate SL/TP rates from ATR (Average True Range).

    Args:
        price: Current instrument price.
        atr: ATR value (same unit as price).
        direction: "BUY" or "SELL".
        sl_multiplier: ATR multiplier for stop-loss distance.
        tp_multiplier: ATR multiplier for take-profit distance.
        max_sl_pct: Maximum stop-loss as % of price.
        min_sl_pct: Minimum stop-loss as % of price.

    Returns:
        dict with sl_rate, tp_rate, sl_pct, tp_pct, method.
    """
    if price <= 0 or atr <= 0:
        return {"error": "Invalid price or ATR (must be > 0)"}

    sl_distance = atr * sl_multiplier
    tp_distance = atr * tp_multiplier

    # Clamp SL distance to min/max percentage of price
    sl_pct = (sl_distance / price) * 100
    sl_pct = max(min_sl_pct, min(sl_pct, max_sl_pct))
    sl_distance = price * sl_pct / 100

    tp_pct = (tp_distance / price) * 100

    is_buy = direction.upper() == "BUY"
    if is_buy:
        sl_rate = price - sl_distance
        tp_rate = price + tp_distance
    else:
        sl_rate = price + sl_distance
        tp_rate = price - tp_distance

    return {
        "sl_rate": round(sl_rate, 4),
        "tp_rate": round(tp_rate, 4),
        "sl_pct": round(sl_pct, 2),
        "tp_pct": round(tp_pct, 2),
        "method": "atr",
    }


def calculate_chandelier_stops(
    df: pd.DataFrame,
    price: float,
    direction: str = "BUY",
    n: int = 22,
    mult: float = 3.0,
    supertrend_n: int = 14,
    supertrend_mult: float = 3.0,
    max_sl_pct: float = 15.0,
    min_sl_pct: float = 1.0,
) -> dict:
    """Calculate Chandelier Exit stop-loss with SuperTrend trend filter.

    Chandelier Exit anchors the stop to the highest high over n periods (for
    BUY), so the stop retreats more slowly than a simple ATR trailing stop —
    but can still decrease when ATR expands sharply. SuperTrend provides a
    trend-state gate: when trend is bearish the stop is still returned but TSL
    activation should be deferred.

    Args:
        df: OHLCV DataFrame with columns high, low, close (min n rows).
        price: Current instrument price.
        direction: "BUY" or "SELL".
        n: Chandelier lookback period (22 for equities/ETFs, 14 for crypto).
        mult: ATR multiplier for Chandelier stop distance (3.0 standard).
        supertrend_n: SuperTrend ATR period.
        supertrend_mult: SuperTrend ATR multiplier.
        max_sl_pct: Maximum stop-loss as % of price (clamp).
        min_sl_pct: Minimum stop-loss as % of price (clamp).

    Returns:
        dict with sl_rate, sl_pct, trend_up (bool), supertrend_value, method.
        Returns {"error": ...} on invalid inputs.
    """
    if price <= 0:
        return {"error": "Invalid price (must be > 0)"}
    min_bars = max(n, supertrend_n)
    if len(df) < min_bars:
        return {"error": f"Insufficient data: need at least {min_bars} bars, got {len(df)}"}

    long_stop, short_stop = chandelier_exit(df, n, mult)
    st_line, st_direction = supertrend(df, supertrend_n, supertrend_mult)

    is_buy = direction.upper() == "BUY"
    raw_sl = float(long_stop.iloc[-1] if is_buy else short_stop.iloc[-1])
    trend_up = bool(st_direction.iloc[-1] == 1)

    if np.isnan(raw_sl):
        return {"error": "Chandelier stop is NaN (insufficient data)"}

    # Clamp distance to min/max percentage of price.
    sl_pct = abs(price - raw_sl) / price * 100
    sl_pct = max(min_sl_pct, min(sl_pct, max_sl_pct))

    sl_rate = price * (1 - sl_pct / 100) if is_buy else price * (1 + sl_pct / 100)

    st_val = float(st_line.iloc[-1])
    if np.isnan(st_val):
        return {"error": "SuperTrend line is NaN (insufficient warmup data)"}

    return {
        "sl_rate": round(sl_rate, 4),
        "sl_pct": round(sl_pct, 2),
        "trend_up": trend_up,
        "supertrend_value": round(st_val, 4),
        "method": "chandelier",
    }


# Conviction-level parameters: (risk_pct_of_portfolio, max_trade_usd)
_CONVICTION = {
    "strong": (0.03, 3000.0),
    "moderate": (0.02, 1500.0),
    "weak": (0.01, 500.0),
}


def calculate_position_size(
    portfolio_value: float,
    cash_available: float,
    atr: float,
    price: float,
    conviction: str = "moderate",
    current_exposure_pct: float = 0.0,
) -> dict:
    """ATR + conviction-based position sizing.

    The risk budget is a percentage of portfolio value determined by conviction.
    The position size is then: risk_budget / (atr / price), which normalizes
    across instruments with different volatilities.

    Args:
        portfolio_value: Total portfolio value (invested + cash + P&L).
        cash_available: Cash remaining in the account.
        atr: ATR value for the instrument.
        price: Current instrument price.
        conviction: "strong", "moderate", or "weak".
        current_exposure_pct: Current portfolio exposure as a fraction (0-1).

    Returns:
        dict with amount, risk_pct, conviction, method.
    """
    if portfolio_value <= 0 or atr <= 0 or price <= 0:
        return {"error": "Invalid inputs (portfolio_value, atr, price must be > 0)"}

    conviction = conviction.lower()
    if conviction not in _CONVICTION:
        conviction = "moderate"

    risk_pct, max_trade = _CONVICTION[conviction]
    risk_budget = portfolio_value * risk_pct

    # ATR-adjusted: how many dollars to invest so that a 1-ATR move = risk_budget.
    # Guard against float underflow (atr/price → 0.0 for extreme value ratios) which
    # would cause ZeroDivisionError in the next line even though atr > 0 was validated.
    atr_ratio = atr / price
    if atr_ratio <= 0:
        return {"error": f"ATR ratio is zero (atr={atr}, price={price}) — cannot size position"}
    amount = risk_budget / atr_ratio

    # Cap by max trade size for this conviction level
    amount = min(amount, max_trade)

    # Cap by available cash minus $200 buffer
    cash_buffer = 200.0
    usable_cash = max(0, cash_available - cash_buffer)
    amount = min(amount, usable_cash)

    # Halve if exposure already above 80%
    if current_exposure_pct > 0.80:
        amount = amount / 2

    # Floor at $50 minimum (AggressiveRiskLimits min)
    if amount < 50:
        return {
            "amount": 0,
            "risk_pct": risk_pct,
            "conviction": conviction,
            "method": "atr_sizing",
            "reason": "Calculated amount below $50 minimum",
        }

    return {
        "amount": round(amount, 2),
        "risk_pct": risk_pct,
        "conviction": conviction,
        "method": "atr_sizing",
    }
