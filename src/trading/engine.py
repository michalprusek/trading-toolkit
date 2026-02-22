from __future__ import annotations

import logging
from typing import Any

import pandas as pd

from config import settings, RiskLimits
from src.api.client import EtoroClient
from src.api import endpoints
from src.api.models import TradeResult
from src.market.data import resolve_symbol, get_rate
from src.trading.risk import check_trade
from src.trading.atr_stops import calculate_atr_stops, calculate_chandelier_stops
from src.storage.repositories import TradeLogRepo


_client: EtoroClient | None = None
_log = logging.getLogger(__name__)


def _get_client() -> EtoroClient:
    global _client
    if _client is None:
        _client = EtoroClient()
    return _client


def open_position(
    symbol: str,
    amount: float,
    direction: str = "BUY",
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    leverage: float = 1.0,
    reason: str | None = None,
    atr_value: float | None = None,
    trailing_sl: bool = False,
    limits_override: RiskLimits | None = None,
    df: pd.DataFrame | None = None,
) -> TradeResult:
    trade_log = TradeLogRepo()
    active_limits = limits_override or settings.risk
    sl_pct = sl_pct or active_limits.default_stop_loss_pct
    tp_pct = tp_pct or active_limits.default_take_profit_pct

    # Resolve instrument
    info = resolve_symbol(symbol)
    if not info:
        result = TradeResult(success=False, message=f"Instrument '{symbol}' not found")
        trade_log.log_trade(None, symbol, direction, amount, "error", reason=reason)
        return result

    iid = info["instrument_id"]

    # Risk check (pass through limits override)
    risk = check_trade(symbol, amount, direction, leverage, limits_override=limits_override)
    if not risk.passed:
        result = TradeResult(success=False, message=risk.summary)
        trade_log.log_trade(iid, symbol, direction, amount, "rejected",
                           result={"violations": risk.violations}, reason=reason)
        return result

    # Get current rate for SL/TP calculation
    rate = get_rate(iid)
    if not rate:
        result = TradeResult(success=False, message="Could not get current rate")
        trade_log.log_trade(iid, symbol, direction, amount, "error", reason=reason)
        return result

    is_buy = direction.upper() == "BUY"
    price = rate.ask if is_buy else rate.bid

    # Calculate SL rates — priority: Chandelier Exit > ATR-based > percentage.
    # TP is always percentage-based (Chandelier is a trailing stop, not a TP tool).
    # The guard len(df) >= 22 matches calculate_chandelier_stops default min_bars=max(22,14).
    tp_rate = price * (1 + tp_pct / 100) if is_buy else price * (1 - tp_pct / 100)
    sl_method = "pct"

    if df is not None and len(df) >= 22:
        chandelier = calculate_chandelier_stops(df, price, direction)
        if "error" not in chandelier:
            sl_rate = chandelier["sl_rate"]
            sl_method = "chandelier"
            # Enable TSL automatically for BUY when SuperTrend confirms the trend.
            if chandelier["trend_up"] and direction.upper() == "BUY":
                trailing_sl = True
        else:
            _log.warning(
                "Chandelier stop failed for %s (%s) — falling back to percentage SL",
                symbol, chandelier.get("error"),
            )
            sl_method = f"pct-fallback({chandelier.get('error')})"
            sl_rate = price * (1 - sl_pct / 100) if is_buy else price * (1 + sl_pct / 100)
    elif atr_value and atr_value > 0:
        atr_stops = calculate_atr_stops(price, atr_value, direction)
        if "error" in atr_stops:
            sl_rate = price * (1 - sl_pct / 100) if is_buy else price * (1 + sl_pct / 100)
        else:
            sl_rate = atr_stops["sl_rate"]
            tp_rate = atr_stops["tp_rate"]
            sl_method = "atr"
    else:
        sl_rate = price * (1 - sl_pct / 100) if is_buy else price * (1 + sl_pct / 100)

    # Build order payload
    payload = {
        "InstrumentID": iid,
        "IsBuy": is_buy,
        "Amount": amount,
        "Leverage": int(leverage),
        "StopLossRate": round(sl_rate, 4),
        "TakeProfitRate": round(tp_rate, 4),
        "IsTslEnabled": trailing_sl,
    }

    try:
        client = _get_client()
        resp = client.post(endpoints.open_trade_path(), payload)
        position_id = resp.get("PositionID") or resp.get("Position", {}).get("PositionID")
        result = TradeResult(
            success=True,
            position_id=position_id,
            message=f"Opened {direction} {symbol} for ${amount} [SL: {sl_method}]",
            raw=resp,
        )
        trade_log.log_trade(iid, symbol, direction, amount, "executed",
                           result=resp, reason=reason)
        return result
    except Exception as e:
        _log.exception("open_position failed for %s", symbol)
        result = TradeResult(success=False, message=str(e))
        trade_log.log_trade(iid, symbol, direction, amount, "error",
                           result={"error": str(e)}, reason=reason)
        return result


def close_position(
    position_id: int,
    instrument_id: int | None = None,
    reason: str | None = None,
) -> TradeResult:
    trade_log = TradeLogRepo()

    # If instrument_id not provided, look it up from portfolio
    if instrument_id is None:
        from src.portfolio.manager import get_portfolio
        portfolio = get_portfolio()
        for p in portfolio.positions:
            if p.position_id == position_id:
                instrument_id = p.instrument_id
                break

    if instrument_id is None:
        return TradeResult(
            success=False,
            message=f"Could not find instrument_id for position {position_id}. "
                    "Pass --instrument-id explicitly.",
        )

    try:
        client = _get_client()
        path = endpoints.close_trade_path(position_id)
        resp = client.post(path, {"InstrumentId": instrument_id})
        trade_log.log_close(position_id, symbol="", pnl=None, reason=reason)
        return TradeResult(
            success=True,
            position_id=position_id,
            message=f"Closed position {position_id}",
            raw=resp if isinstance(resp, dict) else {"status": "ok"},
        )
    except Exception as e:
        _log.exception("close_position failed for position %s", position_id)
        trade_log.log_close(position_id, symbol="", pnl=None, reason=f"FAILED: {e}")
        return TradeResult(success=False, message=str(e))


def create_limit_order(
    symbol: str,
    amount: float,
    limit_price: float,
    direction: str = "BUY",
    sl_pct: float | None = None,
    tp_pct: float | None = None,
    leverage: float = 1.0,
    reason: str | None = None,
) -> TradeResult:
    trade_log = TradeLogRepo()
    sl_pct = sl_pct or settings.risk.default_stop_loss_pct
    tp_pct = tp_pct or settings.risk.default_take_profit_pct

    info = resolve_symbol(symbol)
    if not info:
        result = TradeResult(success=False, message=f"Instrument '{symbol}' not found")
        return result

    iid = info["instrument_id"]

    risk = check_trade(symbol, amount, direction, leverage)
    if not risk.passed:
        result = TradeResult(success=False, message=risk.summary)
        trade_log.log_trade(iid, symbol, direction, amount, "rejected",
                           result={"violations": risk.violations}, reason=reason)
        return result

    is_buy = direction.upper() == "BUY"
    if is_buy:
        sl_rate = limit_price * (1 - sl_pct / 100)
        tp_rate = limit_price * (1 + tp_pct / 100)
    else:
        sl_rate = limit_price * (1 + sl_pct / 100)
        tp_rate = limit_price * (1 - tp_pct / 100)

    payload = {
        "InstrumentID": iid,
        "IsBuy": is_buy,
        "Amount": amount,
        "Leverage": int(leverage),
        "StopLossRate": round(sl_rate, 4),
        "TakeProfitRate": round(tp_rate, 4),
        "IsTslEnabled": False,
        "Rate": limit_price,
    }

    try:
        client = _get_client()
        resp = client.post(endpoints.limit_order_path(), payload)
        order_id = resp.get("OrderID") or resp.get("Order", {}).get("OrderID")
        result = TradeResult(
            success=True,
            order_id=order_id,
            message=f"Limit order: {direction} {symbol} ${amount} @ ${limit_price}",
            raw=resp,
        )
        trade_log.log_trade(iid, symbol, direction, amount, "executed",
                           result=resp, reason=f"LIMIT@{limit_price} {reason or ''}")
        return result
    except Exception as e:
        _log.exception("create_limit_order failed for %s @ $%s", symbol, limit_price)
        result = TradeResult(success=False, message=str(e))
        trade_log.log_trade(iid, symbol, direction, amount, "error",
                           result={"error": str(e)}, reason=reason)
        return result
