from __future__ import annotations

import numpy as np
import pandas as pd


def sma(series: pd.Series, period: int) -> pd.Series:
    return series.rolling(window=period).mean()


def ema(series: pd.Series, period: int) -> pd.Series:
    return series.ewm(span=period, adjust=False).mean()


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1 / period, min_periods=period).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> tuple[pd.Series, pd.Series, pd.Series]:
    ema_fast = ema(series, fast)
    ema_slow = ema(series, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram


def bollinger_bands(
    series: pd.Series, period: int = 20, std_dev: float = 2.0
) -> tuple[pd.Series, pd.Series, pd.Series]:
    middle = sma(series, period)
    std = series.rolling(window=period).std()
    upper = middle + std_dev * std
    lower = middle - std_dev * std
    return upper, middle, lower


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]
    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / period, min_periods=period).mean()


def stochastic(
    df: pd.DataFrame, k_period: int = 14, d_period: int = 3
) -> tuple[pd.Series, pd.Series]:
    low_min = df["low"].rolling(window=k_period).min()
    high_max = df["high"].rolling(window=k_period).max()
    k = 100 * (df["close"] - low_min) / (high_max - low_min)
    d = k.rolling(window=d_period).mean()
    return k, d


def adx(df: pd.DataFrame, period: int = 14) -> pd.Series:
    high = df["high"]
    low = df["low"]
    close = df["close"]

    plus_dm = high.diff()
    minus_dm = -low.diff()
    plus_dm = plus_dm.where((plus_dm > minus_dm) & (plus_dm > 0), 0.0)
    minus_dm = minus_dm.where((minus_dm > plus_dm) & (minus_dm > 0), 0.0)

    tr1 = high - low
    tr2 = (high - close.shift()).abs()
    tr3 = (low - close.shift()).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)

    atr_vals = tr.ewm(alpha=1 / period, min_periods=period).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr_vals
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, min_periods=period).mean() / atr_vals

    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    return dx.ewm(alpha=1 / period, min_periods=period).mean()


def obv(df: pd.DataFrame) -> pd.Series:
    direction = np.sign(df["close"].diff()).fillna(0)
    return (direction * df["volume"]).cumsum()


def _dedupe_levels(levels: list[float], tolerance: float = 0.02) -> list[float]:
    if not levels:
        return levels
    sorted_levels = sorted(levels)
    deduped = [sorted_levels[0]]
    for lvl in sorted_levels[1:]:
        if abs(lvl - deduped[-1]) / deduped[-1] > tolerance:
            deduped.append(lvl)
    return deduped


def support_resistance(df: pd.DataFrame, window: int = 20) -> dict:
    highs = df["high"].rolling(window=window, center=True).max()
    lows = df["low"].rolling(window=window, center=True).min()
    current = df["close"].iloc[-1]

    resistance_levels = _dedupe_levels(
        sorted(set(highs.dropna().unique()))[-5:]
    )
    support_levels = _dedupe_levels(
        sorted(set(lows.dropna().unique()))[:5]
    )

    nearest_support = max((s for s in support_levels if s < current), default=None)
    nearest_resistance = min((r for r in resistance_levels if r > current), default=None)

    return {
        "support_levels": [round(s, 4) for s in support_levels],
        "resistance_levels": [round(r, 4) for r in resistance_levels],
        "nearest_support": round(nearest_support, 4) if nearest_support else None,
        "nearest_resistance": round(nearest_resistance, 4) if nearest_resistance else None,
    }


def chandelier_exit(
    df: pd.DataFrame,
    n: int = 22,
    mult: float = 3.0,
) -> tuple[pd.Series, pd.Series]:
    """Chandelier Exit trailing stop levels.

    Anchors the stop to the highest high (long) or lowest low (short) over n
    periods rather than the current close. This means the long stop only moves
    up — it never retreats — so profits are protected as the trade advances.

    Args:
        df: OHLCV DataFrame with columns high, low, close.
        n: Lookback period (22 for equities/ETFs, 14 for crypto).
        mult: ATR multiplier for stop distance (3.0 standard).

    Returns:
        (long_stop, short_stop) — Series aligned to df.index.
        long_stop  = Highest_High(n) - mult × ATR(n)
        short_stop = Lowest_Low(n)  + mult × ATR(n)
    """
    atr_series = atr(df, n)
    long_stop = df["high"].rolling(n).max() - mult * atr_series
    short_stop = df["low"].rolling(n).min() + mult * atr_series
    return long_stop, short_stop


def supertrend(
    df: pd.DataFrame,
    n: int = 14,
    mult: float = 3.0,
) -> tuple[pd.Series, pd.Series]:
    """SuperTrend indicator — ATR-based trend filter with band-locking logic.

    The band-locking mechanism is the key feature: the upper band only
    tightens in a downtrend (never widens), and the lower band only tightens
    in an uptrend. This prevents the indicator from being pushed away from
    price by short-term volatility spikes during an active trend.

    Args:
        df: OHLCV DataFrame with columns high, low, close.
        n: ATR period.
        mult: ATR multiplier for band distance.

    Returns:
        (supertrend_line, direction) where direction is +1 (bullish) or -1 (bearish).
    """
    hl2 = (df["high"] + df["low"]) / 2
    atr_series = atr(df, n)

    ub_basic = (hl2 + mult * atr_series).to_numpy(dtype=float)
    lb_basic = (hl2 - mult * atr_series).to_numpy(dtype=float)
    close_arr = df["close"].to_numpy(dtype=float)
    n_bars = len(df)

    ub_arr = ub_basic.copy()
    lb_arr = lb_basic.copy()
    trend_arr = np.ones(n_bars, dtype=np.int8)  # 1 = bullish, -1 = bearish

    for i in range(1, n_bars):
        if np.isnan(ub_arr[i]) or np.isnan(lb_arr[i]):
            trend_arr[i] = trend_arr[i - 1]
            continue

        # Band-locking: upper band only decreases (tightens) unless prior
        # close broke above it, which resets the band to basic value.
        prev_ub = ub_arr[i - 1] if not np.isnan(ub_arr[i - 1]) else ub_arr[i]
        ub_arr[i] = ub_arr[i] if (ub_arr[i] < prev_ub or close_arr[i - 1] > prev_ub) else prev_ub

        # Band-locking: lower band only increases (tightens) unless prior
        # close broke below it.
        prev_lb = lb_arr[i - 1] if not np.isnan(lb_arr[i - 1]) else lb_arr[i]
        lb_arr[i] = lb_arr[i] if (lb_arr[i] > prev_lb or close_arr[i - 1] < prev_lb) else prev_lb

        # Trend direction: flip only when price crosses the active band.
        if trend_arr[i - 1] == -1:
            trend_arr[i] = 1 if close_arr[i] > ub_arr[i] else -1
        else:
            trend_arr[i] = -1 if close_arr[i] < lb_arr[i] else 1

    # SuperTrend line: lower band when bullish, upper band when bearish.
    st_arr = np.where(trend_arr == 1, lb_arr, ub_arr)
    return (
        pd.Series(st_arr, index=df.index),
        pd.Series(trend_arr, index=df.index),
    )


def rvol(df: pd.DataFrame, lookback: int = 30) -> float:
    """Relative Volume — today's volume vs. average of last *lookback* days.

    RVOL > 1.5 signals strong institutional interest.
    RVOL < 0.5 signals lack of conviction (avoid breakout trades).
    """
    if "volume" not in df.columns or len(df) < 2:
        return float("nan")
    vol = df["volume"]
    current_vol = vol.iloc[-1]
    avg_vol = vol.iloc[-lookback - 1 : -1].mean() if len(vol) > lookback else vol.iloc[:-1].mean()
    if avg_vol == 0 or pd.isna(avg_vol):
        return float("nan")
    return float(current_vol / avg_vol)


def ma_alignment(
    price: float,
    ema_21: float,
    sma_50: float,
    sma_200: float,
) -> dict:
    """Moving average alignment check for swing trading.

    Golden alignment (BUY): Price > EMA21 > SMA50 > SMA200
    Death alignment (SELL): Price < EMA21 < SMA50 < SMA200
    """
    bullish = price > ema_21 > sma_50 > sma_200
    bearish = price < ema_21 < sma_50 < sma_200
    # Count how many MA layers are correctly stacked
    bull_layers = sum([
        price > ema_21,
        ema_21 > sma_50,
        sma_50 > sma_200,
    ])
    bear_layers = sum([
        price < ema_21,
        ema_21 < sma_50,
        sma_50 < sma_200,
    ])
    if bullish:
        status = "GOLDEN"
    elif bearish:
        status = "DEATH"
    elif bull_layers >= 2:
        status = "MOSTLY_BULLISH"
    elif bear_layers >= 2:
        status = "MOSTLY_BEARISH"
    else:
        status = "MIXED"
    return {
        "status": status,
        "bullish_layers": bull_layers,
        "bearish_layers": bear_layers,
        "price_above_ema21": price > ema_21,
        "ema21_above_sma50": ema_21 > sma_50,
        "sma50_above_sma200": sma_50 > sma_200,
    }


def fibonacci_retracement(high: float, low: float) -> dict:
    diff = high - low
    return {
        "0.0%": round(high, 4),
        "23.6%": round(high - 0.236 * diff, 4),
        "38.2%": round(high - 0.382 * diff, 4),
        "50.0%": round(high - 0.500 * diff, 4),
        "61.8%": round(high - 0.618 * diff, 4),
        "78.6%": round(high - 0.786 * diff, 4),
        "100.0%": round(low, 4),
    }
