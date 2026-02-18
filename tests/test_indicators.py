import numpy as np
import pandas as pd
import pytest

from src.market.indicators import (
    sma, ema, rsi, macd, bollinger_bands, atr,
    stochastic, adx, obv, support_resistance, fibonacci_retracement,
)


@pytest.fixture
def price_series() -> pd.Series:
    """Simulated daily close prices (uptrend with noise)."""
    np.random.seed(42)
    base = np.linspace(100, 130, 60)
    noise = np.random.normal(0, 1.5, 60)
    return pd.Series(base + noise)


@pytest.fixture
def ohlcv_df(price_series) -> pd.DataFrame:
    close = price_series
    high = close + np.random.uniform(0.5, 2.0, len(close))
    low = close - np.random.uniform(0.5, 2.0, len(close))
    open_ = close.shift(1).fillna(close.iloc[0])
    return pd.DataFrame({"open": open_, "high": high, "low": low, "close": close})


class TestSMA:
    def test_sma_length(self, price_series):
        result = sma(price_series, 20)
        assert len(result) == len(price_series)

    def test_sma_nan_start(self, price_series):
        result = sma(price_series, 20)
        assert pd.isna(result.iloc[0])
        assert not pd.isna(result.iloc[19])

    def test_sma_value(self):
        s = pd.Series([1.0, 2.0, 3.0, 4.0, 5.0])
        result = sma(s, 3)
        assert result.iloc[2] == pytest.approx(2.0)
        assert result.iloc[4] == pytest.approx(4.0)


class TestEMA:
    def test_ema_length(self, price_series):
        result = ema(price_series, 12)
        assert len(result) == len(price_series)

    def test_ema_no_nan(self, price_series):
        result = ema(price_series, 12)
        assert not result.isna().any()

    def test_ema_tracks_trend(self, price_series):
        result = ema(price_series, 12)
        assert result.iloc[-1] > result.iloc[0]


class TestRSI:
    def test_rsi_range(self, price_series):
        result = rsi(price_series)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_rsi_uptrend(self):
        s = pd.Series(np.linspace(100, 150, 30))
        result = rsi(s)
        assert result.iloc[-1] > 50

    def test_rsi_downtrend(self):
        s = pd.Series(np.linspace(150, 100, 30))
        result = rsi(s)
        assert result.iloc[-1] < 50


class TestMACD:
    def test_macd_returns_three(self, price_series):
        line, signal, hist = macd(price_series)
        assert len(line) == len(price_series)
        assert len(signal) == len(price_series)
        assert len(hist) == len(price_series)

    def test_histogram_is_diff(self, price_series):
        line, signal, hist = macd(price_series)
        valid_idx = line.dropna().index[-1]
        assert hist.iloc[valid_idx] == pytest.approx(
            line.iloc[valid_idx] - signal.iloc[valid_idx], abs=1e-10
        )


class TestBollingerBands:
    def test_bb_order(self, price_series):
        upper, middle, lower = bollinger_bands(price_series)
        valid = ~(upper.isna() | middle.isna() | lower.isna())
        assert (upper[valid] >= middle[valid]).all()
        assert (middle[valid] >= lower[valid]).all()

    def test_bb_middle_is_sma(self, price_series):
        upper, middle, lower = bollinger_bands(price_series, 20)
        expected = sma(price_series, 20)
        pd.testing.assert_series_equal(middle, expected)


class TestATR:
    def test_atr_positive(self, ohlcv_df):
        result = atr(ohlcv_df)
        valid = result.dropna()
        assert (valid > 0).all()

    def test_atr_length(self, ohlcv_df):
        result = atr(ohlcv_df)
        assert len(result) == len(ohlcv_df)


class TestStochastic:
    def test_stochastic_range(self, ohlcv_df):
        k, d = stochastic(ohlcv_df)
        valid_k = k.dropna()
        valid_d = d.dropna()
        assert (valid_k >= 0).all() and (valid_k <= 100).all()
        assert (valid_d >= 0).all() and (valid_d <= 100).all()

    def test_stochastic_length(self, ohlcv_df):
        k, d = stochastic(ohlcv_df)
        assert len(k) == len(ohlcv_df)
        assert len(d) == len(ohlcv_df)


class TestADX:
    def test_adx_positive(self, ohlcv_df):
        result = adx(ohlcv_df)
        valid = result.dropna()
        assert (valid >= 0).all()

    def test_adx_length(self, ohlcv_df):
        result = adx(ohlcv_df)
        assert len(result) == len(ohlcv_df)


class TestOBV:
    def test_obv_length(self, ohlcv_df):
        df = ohlcv_df.copy()
        df["volume"] = np.random.uniform(1e6, 5e6, len(df))
        result = obv(df)
        assert len(result) == len(df)

    def test_obv_cumulative(self, ohlcv_df):
        df = ohlcv_df.copy()
        df["volume"] = 1000.0
        result = obv(df)
        # OBV is cumulative, so it shouldn't be constant
        assert result.iloc[-1] != 0 or len(df) == 0


class TestSupportResistance:
    def test_returns_dict(self, ohlcv_df):
        result = support_resistance(ohlcv_df)
        assert "support_levels" in result
        assert "resistance_levels" in result
        assert "nearest_support" in result
        assert "nearest_resistance" in result

    def test_levels_are_lists(self, ohlcv_df):
        result = support_resistance(ohlcv_df)
        assert isinstance(result["support_levels"], list)
        assert isinstance(result["resistance_levels"], list)


class TestFibonacciRetracement:
    def test_fibonacci_levels(self):
        result = fibonacci_retracement(150.0, 100.0)
        assert result["0.0%"] == 150.0
        assert result["100.0%"] == 100.0
        assert result["50.0%"] == 125.0
        assert result["23.6%"] == pytest.approx(138.2, abs=0.1)
        assert result["61.8%"] == pytest.approx(119.1, abs=0.1)

    def test_fibonacci_same_high_low(self):
        result = fibonacci_retracement(100.0, 100.0)
        for v in result.values():
            assert v == 100.0

    def test_fibonacci_keys(self):
        result = fibonacci_retracement(200.0, 100.0)
        assert len(result) == 7
        assert "0.0%" in result
        assert "38.2%" in result
        assert "78.6%" in result
