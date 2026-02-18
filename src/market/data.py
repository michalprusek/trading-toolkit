from __future__ import annotations

from datetime import datetime
from typing import Any

import pandas as pd

from src.api.client import EtoroClient
from src.api import endpoints
from src.api.models import InstrumentRate, Candle, Instrument
from src.market import indicators as ind
from src.storage.repositories import InstrumentRepo


_client: EtoroClient | None = None


def _get_client() -> EtoroClient:
    global _client
    if _client is None:
        _client = EtoroClient()
    return _client


def search_instrument(query: str) -> list[dict]:
    client = _get_client()
    data = client.get(
        endpoints.SEARCH,
        internalSymbolFull=query,
    )
    items = data.get("items", [])
    results = []
    repo = InstrumentRepo()
    for item in items:
        inst = {
            "instrument_id": item.get("instrumentId") or item.get("internalInstrumentId"),
            "symbol": item.get("internalSymbolFull", ""),
            "name": item.get("internalInstrumentDisplayName", ""),
            "type": item.get("internalAssetClassId", ""),
            "exchange": item.get("internalExchangeId", ""),
        }
        results.append(inst)
        if inst["instrument_id"]:
            repo.upsert(inst["instrument_id"], inst["symbol"], inst["name"], inst.get("type", ""))
    return results


def resolve_symbol(symbol: str) -> dict | None:
    repo = InstrumentRepo()
    cached = repo.get_by_symbol(symbol)
    if cached:
        return cached
    results = search_instrument(symbol)
    for r in results:
        if r["symbol"].upper() == symbol.upper():
            return r
    return results[0] if results else None


def get_rates(instrument_ids: list[int]) -> list[InstrumentRate]:
    client = _get_client()
    results = []
    for iid in instrument_ids:
        data = client.get(endpoints.INSTRUMENT_RATES, instrumentIds=str(iid))
        rates_list = data.get("rates", data.get("Rates", []))
        for r in rates_list:
            results.append(InstrumentRate.model_validate(r))
    return results


def get_rate(instrument_id: int) -> InstrumentRate | None:
    rates = get_rates([instrument_id])
    return rates[0] if rates else None


def get_candles(
    instrument_id: int, interval: str = "OneDay", count: int = 60
) -> pd.DataFrame:
    client = _get_client()
    path = endpoints.CANDLES.format(
        instrument_id=instrument_id, direction="desc", period=interval, count=count
    )
    data = client.get(path)

    # Public API nests candles: {"candles": [{"instrumentId": ..., "candles": [...]}]}
    outer = data.get("candles", [])
    if outer and isinstance(outer[0], dict) and "candles" in outer[0]:
        candles_raw = outer[0]["candles"]
    else:
        candles_raw = outer

    rows = []
    for c in candles_raw:
        rows.append({
            "timestamp": c.get("fromDate", c.get("FromDate", "")),
            "open": c.get("open", c.get("Open", 0)),
            "high": c.get("high", c.get("High", 0)),
            "low": c.get("low", c.get("Low", 0)),
            "close": c.get("close", c.get("Close", 0)),
            "volume": c.get("volume", c.get("Volume", 0)),
        })

    df = pd.DataFrame(rows)
    if not df.empty:
        df["timestamp"] = pd.to_datetime(df["timestamp"])
        df = df.sort_values("timestamp").reset_index(drop=True)
    return df


INTERVAL_MAP = {
    "M1": "OneMinute",
    "M5": "FiveMinutes",
    "M15": "FifteenMinutes",
    "M30": "ThirtyMinutes",
    "H1": "OneHour",
    "H4": "FourHours",
    "D1": "OneDay",
    "W1": "OneWeek",
}


def analyze_instrument(symbol: str, extended: bool = False) -> dict:
    info = resolve_symbol(symbol)
    if not info:
        return {"error": f"Instrument '{symbol}' not found"}

    iid = info["instrument_id"]
    rate = get_rate(iid)
    df = get_candles(iid, "OneDay", 60)

    if df.empty:
        return {
            "symbol": symbol,
            "instrument_id": iid,
            "price": rate.mid if rate else None,
            "error": "No candle data available",
        }

    close = df["close"]
    current_price = rate.mid if rate else close.iloc[-1]

    rsi_val = ind.rsi(close).iloc[-1]
    macd_line, signal_line, histogram = ind.macd(close)
    bb_upper, bb_middle, bb_lower = ind.bollinger_bands(close)
    atr_val = ind.atr(df).iloc[-1]
    sma_20 = ind.sma(close, 20).iloc[-1]
    sma_50 = ind.sma(close, 50).iloc[-1]
    ema_12 = ind.ema(close, 12).iloc[-1]
    ema_26 = ind.ema(close, 26).iloc[-1]

    # Determine trend
    signals = []
    if rsi_val < 30:
        signals.append("RSI oversold (bullish)")
    elif rsi_val > 70:
        signals.append("RSI overbought (bearish)")

    if histogram.iloc[-1] > 0 and histogram.iloc[-2] <= 0:
        signals.append("MACD bullish crossover")
    elif histogram.iloc[-1] < 0 and histogram.iloc[-2] >= 0:
        signals.append("MACD bearish crossover")

    if current_price < bb_lower.iloc[-1]:
        signals.append("Price below lower BB (oversold)")
    elif current_price > bb_upper.iloc[-1]:
        signals.append("Price above upper BB (overbought)")

    if sma_20 > sma_50:
        signals.append("SMA20 > SMA50 (bullish)")
    else:
        signals.append("SMA20 < SMA50 (bearish)")

    bullish = sum(1 for s in signals if "bullish" in s.lower())
    bearish = sum(1 for s in signals if "bearish" in s.lower())
    if bullish > bearish:
        trend = "BULLISH"
    elif bearish > bullish:
        trend = "BEARISH"
    else:
        trend = "NEUTRAL"

    result = {
        "symbol": symbol,
        "name": info.get("name", ""),
        "instrument_id": iid,
        "price": round(current_price, 4),
        "spread_pct": round(rate.spread_pct, 4) if rate else None,
        "rsi": round(rsi_val, 2),
        "macd": {
            "line": round(macd_line.iloc[-1], 4),
            "signal": round(signal_line.iloc[-1], 4),
            "histogram": round(histogram.iloc[-1], 4),
        },
        "bollinger": {
            "upper": round(bb_upper.iloc[-1], 4),
            "middle": round(bb_middle.iloc[-1], 4),
            "lower": round(bb_lower.iloc[-1], 4),
        },
        "sma_20": round(sma_20, 4),
        "sma_50": round(sma_50, 4),
        "ema_12": round(ema_12, 4),
        "ema_26": round(ema_26, 4),
        "atr": round(atr_val, 4),
        "trend": trend,
        "signals": signals,
    }

    if extended:
        stoch_k, stoch_d = ind.stochastic(df)
        adx_val = ind.adx(df)
        obv_series = ind.obv(df)
        sr = ind.support_resistance(df)
        fib = ind.fibonacci_retracement(
            float(df["high"].max()), float(df["low"].min())
        )

        stoch_k_val = stoch_k.iloc[-1]
        stoch_d_val = stoch_d.iloc[-1]
        adx_last = adx_val.iloc[-1]

        result["stochastic"] = {
            "k": round(stoch_k_val, 2),
            "d": round(stoch_d_val, 2),
        }
        result["adx"] = round(adx_last, 2)
        result["obv"] = round(obv_series.iloc[-1], 0)
        result["support_resistance"] = sr
        result["fibonacci"] = fib

        if stoch_k_val < 20:
            signals.append("Stochastic oversold (bullish)")
        elif stoch_k_val > 80:
            signals.append("Stochastic overbought (bearish)")

        if adx_last > 25:
            signals.append(f"ADX {adx_last:.0f} strong trend")
        else:
            signals.append(f"ADX {adx_last:.0f} weak trend")

        # Recompute trend with new signals
        bullish = sum(1 for s in signals if "bullish" in s.lower())
        bearish = sum(1 for s in signals if "bearish" in s.lower())
        if bullish > bearish:
            result["trend"] = "BULLISH"
        elif bearish > bullish:
            result["trend"] = "BEARISH"
        else:
            result["trend"] = "NEUTRAL"

    return result
