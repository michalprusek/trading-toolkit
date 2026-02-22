import numpy as np
import pandas as pd
import pytest

from src.market.indicators import (
    sma, ema, rsi, macd, bollinger_bands, atr,
    stochastic, adx, obv, support_resistance, fibonacci_retracement,
    chandelier_exit, supertrend, rvol, ma_alignment,
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


class TestRVOL:
    def test_rvol_normal(self, ohlcv_df):
        df = ohlcv_df.copy()
        df["volume"] = 1000.0
        # All volumes equal → RVOL should be ~1.0
        result = rvol(df)
        assert result == pytest.approx(1.0, abs=0.01)

    def test_rvol_high(self, ohlcv_df):
        df = ohlcv_df.copy()
        df["volume"] = 1000.0
        df.iloc[-1, df.columns.get_loc("volume")] = 3000.0
        result = rvol(df)
        assert result > 2.5

    def test_rvol_low(self, ohlcv_df):
        df = ohlcv_df.copy()
        df["volume"] = 1000.0
        df.iloc[-1, df.columns.get_loc("volume")] = 200.0
        result = rvol(df)
        assert result < 0.3

    def test_rvol_no_volume_column(self):
        df = pd.DataFrame({"close": [100, 101, 102]})
        result = rvol(df)
        assert pd.isna(result)

    def test_rvol_short_data_uses_available_bars(self):
        """When len(df) <= lookback, uses all available bars except the last as average."""
        # 10 bars, lookback=30 → falls back to vol.iloc[:-1].mean()
        df = pd.DataFrame({
            "close": [100.0] * 10,
            "high": [101.0] * 10,
            "low": [99.0] * 10,
            "volume": [1000.0] * 9 + [2000.0],  # last bar is 2x average
        })
        result = rvol(df, lookback=30)
        assert result == pytest.approx(2.0, abs=0.01)

    def test_rvol_nan_current_volume_returns_nan(self):
        """NaN in the current (last) volume bar should return NaN, not crash."""
        df = pd.DataFrame({
            "close": [100.0] * 5,
            "high": [101.0] * 5,
            "low": [99.0] * 5,
            "volume": [1000.0, 1000.0, 1000.0, 1000.0, float("nan")],
        })
        result = rvol(df, lookback=3)
        assert pd.isna(result)


class TestMAAlignment:
    def test_golden_alignment(self):
        result = ma_alignment(price=150, ema_21=140, sma_50=130, sma_200=120)
        assert result["status"] == "GOLDEN"
        assert result["bullish_layers"] == 3

    def test_death_alignment(self):
        result = ma_alignment(price=100, ema_21=110, sma_50=120, sma_200=130)
        assert result["status"] == "DEATH"
        assert result["bearish_layers"] == 3

    def test_mostly_bullish(self):
        # Price > EMA21 > SMA50, but SMA50 < SMA200
        result = ma_alignment(price=150, ema_21=140, sma_50=130, sma_200=135)
        assert result["status"] == "MOSTLY_BULLISH"

    def test_mixed(self):
        # 1 bullish (price > ema21), 1 bearish (ema21 < sma50), sma50 == sma200 → MIXED
        result = ma_alignment(price=150, ema_21=140, sma_50=145, sma_200=145)
        assert result["status"] == "MIXED"

    def test_mostly_bearish(self):
        # Price < EMA21 < SMA50, but SMA50 > SMA200 → 2 bearish layers, not DEATH
        result = ma_alignment(price=100, ema_21=110, sma_50=120, sma_200=115)
        assert result["status"] == "MOSTLY_BEARISH"

    def test_nan_sma200(self):
        # price > ema_21 > sma_50 but sma_200 unavailable → SMA200 layer excluded
        result = ma_alignment(price=150, ema_21=140, sma_50=130, sma_200=float("nan"))
        # 2 bullish layers (price>ema21, ema21>sma50), SMA200 layer skipped → MOSTLY_BULLISH
        assert result["status"] == "MOSTLY_BULLISH"
        assert result["sma50_above_sma200"] is False  # explicitly False when sma200 unknown

    def test_none_sma200(self):
        result = ma_alignment(price=150, ema_21=140, sma_50=130, sma_200=None)
        assert result["status"] == "MOSTLY_BULLISH"


class TestChandelierExit:
    def test_returns_two_series(self, ohlcv_df):
        long_stop, short_stop = chandelier_exit(ohlcv_df)
        assert len(long_stop) == len(ohlcv_df)
        assert len(short_stop) == len(ohlcv_df)

    def test_long_stop_below_price(self, ohlcv_df):
        long_stop, _ = chandelier_exit(ohlcv_df)
        last_close = ohlcv_df["close"].iloc[-1]
        assert long_stop.iloc[-1] < last_close

    def test_short_stop_above_price_in_downtrend(self):
        # Short stop = Lowest_Low(22) + 3×ATR. In a downtrend the recent lows
        # are near current price, so short_stop is above close.
        prices = np.linspace(200, 100, 60)
        df = pd.DataFrame({
            "high": prices + 2,
            "low": prices - 2,
            "close": prices,
        })
        _, short_stop = chandelier_exit(df)
        last_close = df["close"].iloc[-1]
        assert short_stop.iloc[-1] > last_close

    def test_long_stop_anchored_to_highest_high(self, ohlcv_df):
        n, mult = 22, 3.0
        long_stop, _ = chandelier_exit(ohlcv_df, n=n, mult=mult)
        highest_high = ohlcv_df["high"].rolling(n).max().iloc[-1]
        atr_val = atr(ohlcv_df, n).iloc[-1]
        expected = highest_high - mult * atr_val
        assert long_stop.iloc[-1] == pytest.approx(expected, rel=1e-6)

    def test_nan_before_warmup(self, ohlcv_df):
        long_stop, _ = chandelier_exit(ohlcv_df, n=22)
        # First 21 bars should be NaN (rolling window not yet full).
        assert pd.isna(long_stop.iloc[0])

    def test_wider_mult_gives_lower_long_stop(self, ohlcv_df):
        long_3, _ = chandelier_exit(ohlcv_df, mult=3.0)
        long_5, _ = chandelier_exit(ohlcv_df, mult=5.0)
        assert long_5.iloc[-1] < long_3.iloc[-1]

    def test_uptrend_stop_ratchets_up(self):
        # Strongly uptrending price: stop should be strictly increasing.
        np.random.seed(0)
        prices = np.linspace(100, 200, 60)
        df = pd.DataFrame({
            "high": prices + 2,
            "low": prices - 2,
            "close": prices,
        })
        long_stop, _ = chandelier_exit(df, n=22)
        valid = long_stop.dropna()
        # In a clean uptrend the stop should be non-decreasing.
        assert (valid.diff().dropna() >= 0).all()


class TestSupertrend:
    def test_returns_two_series(self, ohlcv_df):
        st_line, direction = supertrend(ohlcv_df)
        assert len(st_line) == len(ohlcv_df)
        assert len(direction) == len(ohlcv_df)

    def test_direction_values(self, ohlcv_df):
        _, direction = supertrend(ohlcv_df)
        assert set(direction.unique()).issubset({1, -1})

    def test_uptrend_detected(self):
        # Strongly uptrending market: SuperTrend should be bullish at the end.
        prices = np.linspace(100, 200, 60)
        df = pd.DataFrame({
            "high": prices + 1,
            "low": prices - 1,
            "close": prices,
        })
        _, direction = supertrend(df)
        assert direction.iloc[-1] == 1

    def test_downtrend_detected(self):
        # Strongly downtrending market: SuperTrend should be bearish at the end.
        prices = np.linspace(200, 100, 60)
        df = pd.DataFrame({
            "high": prices + 1,
            "low": prices - 1,
            "close": prices,
        })
        _, direction = supertrend(df)
        assert direction.iloc[-1] == -1

    def test_line_below_price_in_uptrend(self):
        prices = np.linspace(100, 200, 60)
        df = pd.DataFrame({
            "high": prices + 1,
            "low": prices - 1,
            "close": prices,
        })
        st_line, direction = supertrend(df)
        valid = ~st_line.isna()
        bullish_bars = (direction == 1) & valid
        # In bullish bars the SuperTrend line (support) is below close.
        assert (st_line[bullish_bars] < df["close"][bullish_bars]).all()

    def test_length_matches_input(self, ohlcv_df):
        st_line, direction = supertrend(ohlcv_df)
        assert len(st_line) == len(ohlcv_df)
        assert len(direction) == len(ohlcv_df)

    def test_single_dip_does_not_flip_trend(self):
        """Band-locking: one pullback bar should not flip a well-established uptrend."""
        prices = np.linspace(100, 200, 59)
        # Append a single dip — moderate pullback, not a full reversal
        prices_with_dip = np.append(prices, prices[-1] - 5)
        df = pd.DataFrame({
            "high": prices_with_dip + 1,
            "low": prices_with_dip - 1,
            "close": prices_with_dip,
        })
        _, direction = supertrend(df)
        assert direction.iloc[-1] == 1  # still bullish after one dip
