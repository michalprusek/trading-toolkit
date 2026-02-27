from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx
import logging

import pandas as pd

from src.api.client import EtoroClient
from src.api import endpoints
from src.api.models import InstrumentRate
from src.market import indicators as ind
from src.storage.repositories import InstrumentRepo


# Standard tickers that resolve incorrectly on eToro's search API.
# Single/double-letter symbols often match forex pairs or futures first.
# Values are the eToro-specific symbol that resolves correctly.
SYMBOL_ALIASES: dict[str, str] = {
    "V": "V.RTH",       # Visa Inc — search returns VIX futures
    "C": "C.RTH",       # Citigroup — search returns CHF/JPY
    "CL": "CL.RTH",     # Colgate-Palmolive — search returns Crude Oil futures
    "SQ": "XYZ",         # Block Inc — ticker changed from SQ to XYZ
}

_client: EtoroClient | None = None
_vix_client: httpx.Client | None = None
_log = logging.getLogger(__name__)


def _get_client() -> EtoroClient:
    global _client
    if _client is None:
        _client = EtoroClient()
    return _client


def _get_vix_client() -> httpx.Client:
    global _vix_client
    if _vix_client is None:
        _vix_client = httpx.Client(
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
    return _vix_client


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

    # Redirect ambiguous tickers to their correct eToro symbol
    lookup = SYMBOL_ALIASES.get(symbol.upper(), symbol)

    results = search_instrument(lookup)
    for r in results:
        if r["symbol"].upper() == lookup.upper():
            # Cache under the original symbol too (e.g. V → V.RTH)
            if lookup.upper() != symbol.upper():
                repo.upsert(r["instrument_id"], symbol.upper(), r["name"], r.get("type", ""))
            return r

    # No exact match — return None instead of blindly picking results[0]
    return None


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


def _build_chandelier_dict(
    chandelier_long: Any,
    chandelier_short: Any,
    st_direction: Any,
    st_line: Any,
) -> dict | None:
    """Build the chandelier result dict, returning None when any value is NaN.

    Returns None instead of a dict with NaN values to avoid invalid JSON
    (float('nan') is not JSON-serialisable) and to signal that there is
    insufficient candle history for a reliable stop calculation.
    """
    ch_long = chandelier_long.iloc[-1]
    ch_short = chandelier_short.iloc[-1]
    direction_val = st_direction.iloc[-1]
    st_val = st_line.iloc[-1]
    if pd.isna(ch_long) or pd.isna(ch_short) or pd.isna(direction_val) or pd.isna(st_val):
        return None
    return {
        "long_stop": round(float(ch_long), 4),
        "short_stop": round(float(ch_short), 4),
        "trend_up": bool(direction_val == 1),
        "supertrend": round(float(st_val), 4),
    }


def analyze_instrument(symbol: str, extended: bool = False) -> dict:
    info = resolve_symbol(symbol)
    if not info:
        return {"error": f"Instrument '{symbol}' not found"}

    iid = info["instrument_id"]
    rate = get_rate(iid)
    df = get_candles(iid, "OneDay", 220)

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
    chandelier_long, chandelier_short = ind.chandelier_exit(df)
    st_line, st_direction = ind.supertrend(df)
    sma_20 = ind.sma(close, 20).iloc[-1]
    sma_50 = ind.sma(close, 50).iloc[-1]
    ema_12 = ind.ema(close, 12).iloc[-1]
    ema_26 = ind.ema(close, 26).iloc[-1]

    # Swing-trading MAs
    ema_8 = ind.ema(close, 8).iloc[-1]
    ema_21 = ind.ema(close, 21).iloc[-1]
    sma_200_val = ind.sma(close, 200).iloc[-1] if len(close) >= 200 else float("nan")

    # Relative volume
    rvol_val = ind.rvol(df) if "volume" in df.columns else float("nan")

    # MA alignment (use sma_50 for alignment; sma_200 may be NaN with 60 bars)
    alignment = ind.ma_alignment(current_price, ema_21, sma_50, sma_200_val)

    # Pre-market gap: current live price vs last candle close
    last_close = close.iloc[-1]
    gap_pct = round((current_price - last_close) / last_close * 100, 2) if last_close else None

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

    # MA alignment signals
    if alignment["status"] == "GOLDEN":
        signals.append("Golden MA alignment (bullish)")
    elif alignment["status"] == "DEATH":
        signals.append("Death MA alignment (bearish)")

    # RVOL signals
    if not pd.isna(rvol_val):
        if rvol_val >= 2.0:
            signals.append(f"RVOL {rvol_val:.1f}x very high volume")
        elif rvol_val >= 1.5:
            signals.append(f"RVOL {rvol_val:.1f}x above average volume")
        elif rvol_val < 0.5:
            signals.append(f"RVOL {rvol_val:.1f}x low volume (weak conviction)")

    # Gap signals
    if gap_pct is not None and abs(gap_pct) >= 1.0:
        direction = "up" if gap_pct > 0 else "down"
        signals.append(f"Gap {direction} {abs(gap_pct):.1f}%")

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
        "ema_8": round(ema_8, 4),
        "ema_12": round(ema_12, 4),
        "ema_21": round(ema_21, 4),
        "ema_26": round(ema_26, 4),
        "sma_200": round(sma_200_val, 4) if not pd.isna(sma_200_val) else None,
        "rvol": round(rvol_val, 2) if not pd.isna(rvol_val) else None,
        "ma_alignment": alignment,
        "gap_pct": gap_pct,
        "atr": round(atr_val, 4),
        "chandelier": _build_chandelier_dict(
            chandelier_long, chandelier_short, st_direction, st_line
        ),
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


def _fetch_vix_external() -> float | None:
    """Fetch current VIX value from external sources.

    VIX is not available on eToro. Tries in order:
    1. Yahoo Finance (^VIX) — free, no API key
    2. Finnhub quote for VIX — requires FINNHUB_API_KEY
    Returns None if all sources fail.
    """
    client = _get_vix_client()

    # 1. Yahoo Finance ^VIX (undocumented but stable chart API)
    try:
        resp = client.get(
            "https://query1.finance.yahoo.com/v8/finance/chart/%5EVIX",
            params={"interval": "1d", "range": "1d"},
        )
        if resp.status_code == 200:
            data = resp.json()
            result_list = data.get("chart", {}).get("result") or []
            if not result_list:
                _log.debug("VIX Yahoo Finance: status 200 but result list is null/empty")
            else:
                meta = result_list[0].get("meta", {})
                price = meta.get("regularMarketPrice") or meta.get("previousClose")
                try:
                    if price and float(price) > 0:
                        return float(price)
                    _log.debug(
                        "VIX Yahoo Finance: status 200 but no usable price "
                        "(regularMarketPrice=%r, previousClose=%r)",
                        meta.get("regularMarketPrice"), meta.get("previousClose"),
                    )
                except (ValueError, TypeError) as conv_err:
                    _log.warning(
                        "VIX Yahoo Finance: could not convert price to float (%r): %s",
                        price, conv_err,
                    )
    except Exception:
        _log.warning("VIX fetch from Yahoo Finance failed", exc_info=True)

    # 2. Finnhub quote for VIX (if API key configured)
    try:
        from config import settings
        finnhub_key = getattr(settings, "finnhub_api_key", "")
        if finnhub_key:
            resp = client.get(
                "https://finnhub.io/api/v1/quote",
                params={"symbol": "CBOE:VIX", "token": finnhub_key},
            )
            if resp.status_code == 200:
                price = resp.json().get("c")  # current price
                try:
                    if price and float(price) > 0:
                        return float(price)
                except (ValueError, TypeError) as conv_err:
                    _log.warning(
                        "VIX Finnhub: could not convert price to float (%r): %s",
                        price, conv_err,
                    )
    except Exception:
        _log.warning("VIX fetch from Finnhub failed", exc_info=True)

    return None


def analyze_market_regime() -> dict[str, Any]:
    """Analyze broad market regime: SPY + QQQ trend, VIX level.

    This is the 'weather check' that should run before any individual stock analysis.
    Returns market bias, VIX interpretation, and position-sizing guidance.
    """
    regime: dict[str, Any] = {"errors": []}

    # SPY analysis
    spy = analyze_instrument("SPY", extended=True)
    if "error" not in spy:
        regime["spy"] = {
            "price": spy["price"],
            "trend": spy["trend"],
            "rsi": spy["rsi"],
            "sma_20": spy["sma_20"],
            "sma_50": spy["sma_50"],
            "above_sma20": bool(spy["price"] > spy["sma_20"]),
            "above_sma50": bool(spy["price"] > spy["sma_50"]),
            "ma_alignment": spy.get("ma_alignment"),
            "rvol": spy.get("rvol"),
        }
    else:
        regime["errors"].append(f"SPY: {spy['error']}")

    # QQQ analysis
    qqq = analyze_instrument("QQQ", extended=True)
    if "error" not in qqq:
        regime["qqq"] = {
            "price": qqq["price"],
            "trend": qqq["trend"],
            "rsi": qqq["rsi"],
            "sma_20": qqq["sma_20"],
            "sma_50": qqq["sma_50"],
            "above_sma20": bool(qqq["price"] > qqq["sma_20"]),
            "above_sma50": bool(qqq["price"] > qqq["sma_50"]),
        }
    else:
        regime["errors"].append(f"QQQ: {qqq['error']}")

    # VIX analysis — fetched from external sources (VIX is not on eToro)
    vix_val = _fetch_vix_external()
    if vix_val is not None:
        if vix_val < 13:
            vix_regime = "VERY_LOW"
            vix_guidance = "Complacency — low hedging. Good for longs but watch for spikes."
            sizing_adj = 1.0
        elif vix_val < 16:
            vix_regime = "LOW"
            vix_guidance = "Calm market. Standard position sizes."
            sizing_adj = 1.0
        elif vix_val < 20:
            vix_regime = "NORMAL"
            vix_guidance = "Normal volatility. Standard position sizes."
            sizing_adj = 1.0
        elif vix_val < 25:
            vix_regime = "ELEVATED"
            vix_guidance = "Elevated risk. Reduce position sizes by 25%."
            sizing_adj = 0.75
        elif vix_val < 30:
            vix_regime = "HIGH"
            vix_guidance = "High fear. Reduce position sizes by 50%. Avoid new longs unless oversold bounce."
            sizing_adj = 0.5
        else:
            vix_regime = "EXTREME"
            vix_guidance = "Panic/crisis. Minimal new positions. Focus on capital preservation."
            sizing_adj = 0.25
        regime["vix"] = {
            "value": round(vix_val, 2),
            "regime": vix_regime,
            "guidance": vix_guidance,
            "sizing_adjustment": sizing_adj,
        }
    else:
        regime["errors"].append("VIX: Could not fetch from external sources (defaulting to NORMAL)")
        # Provide safe defaults so callers don't KeyError on regime["vix"]
        regime["vix"] = {
            "value": None,
            "regime": "UNKNOWN",
            "guidance": "VIX unavailable — assuming normal volatility.",
            "sizing_adjustment": 1.0,
        }

    # Overall market bias — requires at least one index to be available
    spy_present = "spy" in regime
    qqq_present = "qqq" in regime
    if not spy_present and not qqq_present:
        _log.error(
            "Market regime analysis failed: both SPY and QQQ unavailable. Errors: %s",
            regime["errors"],
        )
        regime["bias"] = "UNKNOWN"
        regime["bias_guidance"] = "Market data unavailable — cannot determine regime."
        return regime

    spy_bull = regime.get("spy", {}).get("trend") == "BULLISH"
    qqq_bull = regime.get("qqq", {}).get("trend") == "BULLISH"
    spy_above_20 = regime.get("spy", {}).get("above_sma20", False)
    spy_above_50 = regime.get("spy", {}).get("above_sma50", False)
    # Conservative default: when VIX is unavailable treat as NOT ok (avoid biasing to RISK_ON)
    vix_val_raw = regime.get("vix", {}).get("value")
    vix_ok = vix_val_raw is not None and vix_val_raw < 25

    bull_score = sum([spy_bull, qqq_bull, spy_above_20, spy_above_50, vix_ok])
    if bull_score >= 4:
        regime["bias"] = "RISK_ON"
        regime["bias_guidance"] = "Favorable for swing longs. Full position sizes."
    elif bull_score >= 2:
        regime["bias"] = "CAUTIOUS"
        regime["bias_guidance"] = "Mixed signals. Reduce sizes, focus on strongest setups only."
    else:
        regime["bias"] = "RISK_OFF"
        regime["bias_guidance"] = "Unfavorable for longs. Defensive positioning, consider sitting out."

    return regime
