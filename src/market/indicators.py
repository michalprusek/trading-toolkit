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
