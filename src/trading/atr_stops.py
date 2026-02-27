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


# Conviction-level parameters: (risk_pct_of_portfolio, max_concentration_pct)
# risk_pct: max portfolio % lost if SL is hit
# max_concentration: max portfolio % allocated to a single position
_CONVICTION = {
    "strong": (0.02, 0.08),
    "moderate": (0.015, 0.05),
    "weak": (0.01, 0.03),
}


def calculate_position_size(
    portfolio_value: float,
    cash_available: float,
    atr: float,
    price: float,
    conviction: str = "moderate",
    current_exposure_pct: float = 0.0,
    sl_distance_pct: float | None = None,
) -> dict:
    """SL-aware position sizing with concentration caps.

    Sizes the position so that hitting the stop-loss costs exactly risk_budget
    dollars. Then caps by concentration limit to prevent over-allocation.

    The actual binding constraint depends on the SL distance:
    - Tight SL (1-3%): risk-based sizing dominates → smaller positions
    - Wide SL (8-15%): concentration cap dominates → larger positions capped

    Args:
        portfolio_value: Total portfolio value (invested + cash + P&L).
        cash_available: Cash remaining in the account.
        atr: ATR value (used as SL proxy when sl_distance_pct not provided).
        price: Current instrument price.
        conviction: "strong", "moderate", or "weak".
        current_exposure_pct: Current portfolio exposure as a fraction (0-1).
        sl_distance_pct: Actual SL distance as fraction (e.g. 0.05 for 5%).
            When provided, sizing is based on real SL. Otherwise falls back
            to 2×ATR as SL estimate.

    Returns:
        dict with amount, risk_budget, actual_risk, actual_risk_pct,
        conviction, binding_constraint, method.
    """
    if portfolio_value <= 0 or price <= 0:
        return {"error": "Invalid inputs (portfolio_value, price must be > 0)"}
    if atr <= 0 and sl_distance_pct is None:
        return {"error": "Need either atr > 0 or sl_distance_pct"}

    conviction = conviction.lower()
    if conviction not in _CONVICTION:
        conviction = "moderate"

    risk_pct, max_concentration = _CONVICTION[conviction]
    risk_budget = portfolio_value * risk_pct

    # Determine SL distance: prefer explicit sl_distance_pct, fall back to 2×ATR.
    if sl_distance_pct is not None and sl_distance_pct > 0:
        sl_frac = sl_distance_pct
    else:
        sl_frac = (atr * 2) / price
        sl_frac = max(0.01, min(sl_frac, 0.15))  # clamp 1-15%

    # Risk-based sizing: invest X so that X × sl_frac = risk_budget.
    risk_based_amount = risk_budget / sl_frac

    # Concentration cap: max % of portfolio in one position.
    concentration_cap = portfolio_value * max_concentration

    # Determine binding constraint
    if risk_based_amount <= concentration_cap:
        amount = risk_based_amount
        binding = "risk"
    else:
        amount = concentration_cap
        binding = "concentration"

    # Cap by available cash minus $200 buffer
    usable_cash = max(0, cash_available - 200.0)
    if amount > usable_cash:
        amount = usable_cash
        binding = "cash"

    # Halve if exposure already above 80%
    if current_exposure_pct > 0.80:
        amount = amount / 2
        binding = f"{binding}+high_exposure"

    # Floor at $50 minimum
    if amount < 50:
        return {
            "amount": 0,
            "risk_budget": round(risk_budget, 2),
            "actual_risk": 0,
            "actual_risk_pct": 0,
            "conviction": conviction,
            "binding_constraint": "below_minimum",
            "method": "sl_sizing",
            "reason": f"Calculated amount ${amount:.0f} below $50 minimum",
        }

    # Calculate actual risk at this position size
    actual_risk = amount * sl_frac
    actual_risk_pct = actual_risk / portfolio_value * 100

    return {
        "amount": round(amount, 2),
        "risk_budget": round(risk_budget, 2),
        "actual_risk": round(actual_risk, 2),
        "actual_risk_pct": round(actual_risk_pct, 2),
        "sl_distance_pct": round(sl_frac * 100, 2),
        "concentration_pct": round(amount / portfolio_value * 100, 1),
        "conviction": conviction,
        "binding_constraint": binding,
        "method": "sl_sizing",
    }
