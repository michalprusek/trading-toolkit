import numpy as np
import pandas as pd
import pytest

from src.trading.atr_stops import calculate_atr_stops, calculate_chandelier_stops, calculate_position_size


@pytest.fixture
def trending_ohlcv() -> pd.DataFrame:
    """60-bar uptrending OHLCV DataFrame for Chandelier/SuperTrend tests."""
    np.random.seed(7)
    prices = np.linspace(100, 160, 60) + np.random.normal(0, 0.5, 60)
    return pd.DataFrame({
        "high": prices + np.random.uniform(0.5, 2.0, 60),
        "low": prices - np.random.uniform(0.5, 2.0, 60),
        "close": prices,
    })


class TestCalculateAtrStops:
    def test_buy_basic(self):
        result = calculate_atr_stops(price=100, atr=5, direction="BUY")
        assert result["method"] == "atr"
        assert result["sl_rate"] < 100  # SL below price for BUY
        assert result["tp_rate"] > 100  # TP above price for BUY
        assert result["sl_rate"] == 90.0  # 100 - 5*2
        assert result["tp_rate"] == 115.0  # 100 + 5*3

    def test_sell_basic(self):
        result = calculate_atr_stops(price=100, atr=5, direction="SELL")
        assert result["sl_rate"] > 100  # SL above price for SELL
        assert result["tp_rate"] < 100  # TP below price for SELL
        assert result["sl_rate"] == 110.0  # 100 + 5*2
        assert result["tp_rate"] == 85.0  # 100 - 5*3

    def test_max_sl_cap(self):
        # ATR=20 on price=100 → 40% SL, should be capped at 15%
        result = calculate_atr_stops(price=100, atr=20, direction="BUY", max_sl_pct=15.0)
        assert result["sl_pct"] == 15.0
        assert result["sl_rate"] == 85.0  # 100 - 15%

    def test_min_sl_floor(self):
        # ATR=0.1 on price=100 → 0.2% SL, should be floored at 1%
        result = calculate_atr_stops(price=100, atr=0.1, direction="BUY", min_sl_pct=1.0)
        assert result["sl_pct"] == 1.0
        assert result["sl_rate"] == 99.0  # 100 - 1%

    def test_invalid_price_returns_error(self):
        result = calculate_atr_stops(price=0, atr=5, direction="BUY")
        assert "error" in result

    def test_invalid_atr_returns_error(self):
        result = calculate_atr_stops(price=100, atr=0, direction="BUY")
        assert "error" in result

    def test_negative_inputs_return_error(self):
        result = calculate_atr_stops(price=-10, atr=5, direction="BUY")
        assert "error" in result

    def test_custom_multipliers(self):
        result = calculate_atr_stops(price=100, atr=5, direction="BUY",
                                     sl_multiplier=1.5, tp_multiplier=4.0)
        # SL distance: 5 * 1.5 = 7.5 → 7.5%
        assert result["sl_pct"] == 7.5
        assert result["sl_rate"] == 92.5
        # TP distance: 5 * 4.0 = 20
        assert result["tp_pct"] == 20.0
        assert result["tp_rate"] == 120.0

    def test_sell_with_min_sl_floor(self):
        result = calculate_atr_stops(price=200, atr=0.5, direction="SELL", min_sl_pct=1.0)
        assert result["sl_pct"] == 1.0
        assert result["sl_rate"] == 202.0  # 200 + 1%


class TestCalculatePositionSize:
    def test_strong_conviction(self):
        result = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=5, price=100, conviction="strong",
        )
        assert "amount" in result
        assert result["conviction"] == "strong"
        assert result["amount"] > 0
        # strong: max 8% concentration = $800
        assert result["amount"] <= 800

    def test_moderate_conviction(self):
        result = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=5, price=100, conviction="moderate",
        )
        assert result["conviction"] == "moderate"
        # moderate: max 5% concentration = $500
        assert result["amount"] <= 500

    def test_weak_conviction(self):
        result = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=5, price=100, conviction="weak",
        )
        assert result["conviction"] == "weak"
        # weak: max 3% concentration = $300
        assert result["amount"] <= 300

    def test_high_exposure_halving(self):
        normal = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=5, price=100, conviction="moderate",
            current_exposure_pct=0.50,
        )
        halved = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=5, price=100, conviction="moderate",
            current_exposure_pct=0.85,
        )
        assert normal.get("amount", 0) > 0
        assert halved.get("amount", 0) > 0
        assert halved["amount"] < normal["amount"]

    def test_exposure_exactly_80pct_does_not_halve(self):
        # Condition is strictly > 0.80, so 0.80 exactly should NOT trigger halving
        normal = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=5, price=100, conviction="moderate",
            current_exposure_pct=0.50,
        )
        at_threshold = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=5, price=100, conviction="moderate",
            current_exposure_pct=0.80,
        )
        assert at_threshold.get("amount") == normal.get("amount")

    def test_exposure_above_80pct_halves(self):
        normal = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=5, price=100, conviction="moderate",
            current_exposure_pct=0.50,
        )
        above_threshold = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=5, price=100, conviction="moderate",
            current_exposure_pct=0.801,
        )
        assert above_threshold["amount"] == pytest.approx(normal["amount"] / 2, rel=0.01)

    def test_cash_buffer_respected(self):
        # $250 cash → usable = $50 (250 - 200 buffer); capped below concentration amount
        result = calculate_position_size(
            portfolio_value=10000, cash_available=250,
            atr=5, price=100, conviction="strong",
        )
        assert result.get("amount") == pytest.approx(50.0)

    def test_below_minimum_returns_zero(self):
        # usable = $10 (210 - 200 buffer); → capped to $10 < $50 minimum
        result = calculate_position_size(
            portfolio_value=10000, cash_available=210,
            atr=50, price=100, conviction="weak",
        )
        assert result.get("amount") == 0
        assert "reason" in result

    def test_invalid_inputs_return_error(self):
        result = calculate_position_size(
            portfolio_value=0, cash_available=1000,
            atr=5, price=100,
        )
        assert "error" in result

    def test_unknown_conviction_defaults_to_moderate(self):
        result = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=5, price=100, conviction="unknown",
        )
        assert result["conviction"] == "moderate"

    def test_method_is_sl_sizing(self):
        result = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=5, price=100,
        )
        assert result["method"] == "sl_sizing"

    def test_returns_actual_risk(self):
        """New sizing reports actual $ at risk and binding constraint."""
        result = calculate_position_size(
            portfolio_value=18000, cash_available=11000,
            atr=5, price=200, conviction="moderate",
        )
        assert "actual_risk" in result
        assert "actual_risk_pct" in result
        assert "binding_constraint" in result
        assert result["actual_risk"] > 0
        assert result["actual_risk_pct"] > 0

    def test_sl_distance_pct_overrides_atr(self):
        """When sl_distance_pct is provided, sizing uses it instead of ATR."""
        # With 10% SL distance, risk_budget = 10000 * 0.015 = $150
        # risk_based = $150 / 0.10 = $1500 → capped by concentration (5% = $500)
        result = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=5, price=100, conviction="moderate",
            sl_distance_pct=0.10,
        )
        assert result["sl_distance_pct"] == 10.0
        assert result["amount"] <= 500

    def test_tight_sl_produces_smaller_position(self):
        """Tight SL with low risk budget can produce amount below concentration cap."""
        # Very large portfolio: risk_budget = 1M * 0.015 = $15K
        # SL 1%: risk_based = $15K / 0.01 = $1.5M → capped at 5% = $50K
        # SL 50%: risk_based = $15K / 0.50 = $30K → capped at 5% = $50K
        # For normal portfolios, concentration always wins.
        # But for small risk budgets with tight SLs, risk can win:
        result_tight = calculate_position_size(
            portfolio_value=5000, cash_available=4000,
            atr=1, price=100, conviction="weak",
            sl_distance_pct=0.20,  # 20% SL
        )
        # risk_budget = 5000 * 0.01 = $50, risk_based = $50/0.20 = $250
        # concentration cap = 5000 * 0.03 = $150
        # $250 > $150 → concentration wins, amount = $150
        assert result_tight["binding_constraint"] == "concentration"

        result_wide = calculate_position_size(
            portfolio_value=5000, cash_available=4000,
            atr=1, price=100, conviction="weak",
            sl_distance_pct=0.50,  # 50% SL
        )
        # risk_based = $50/0.50 = $100 < $150 → risk wins
        assert result_wide["binding_constraint"] == "risk"
        assert result_wide["amount"] < result_tight["amount"]

    def test_sl_distance_pct_zero_returns_error(self):
        """sl_distance_pct=0 must return error, not silently fall through to ATR."""
        result = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=5, price=100, conviction="moderate",
            sl_distance_pct=0.0,
        )
        assert "error" in result

    def test_sl_distance_pct_negative_returns_error(self):
        """Negative sl_distance_pct must return error."""
        result = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=5, price=100, conviction="moderate",
            sl_distance_pct=-0.05,
        )
        assert "error" in result

    def test_atr_zero_with_sl_distance_pct_succeeds(self):
        """atr=0 is OK when sl_distance_pct is explicitly provided."""
        result = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=0, price=100, conviction="moderate",
            sl_distance_pct=0.05,
        )
        assert "error" not in result
        assert result["amount"] > 0

    def test_atr_zero_without_sl_distance_returns_error(self):
        """atr=0 without sl_distance_pct must return error."""
        result = calculate_position_size(
            portfolio_value=10000, cash_available=5000,
            atr=0, price=100, conviction="moderate",
        )
        assert "error" in result

    def test_cash_buffer_binding_constraint(self):
        """When cash is the binding constraint, result should report it."""
        result = calculate_position_size(
            portfolio_value=10000, cash_available=250,
            atr=5, price=100, conviction="strong",
        )
        assert result.get("amount") == pytest.approx(50.0)
        assert result.get("binding_constraint") == "cash"


class TestCalculateChandelierStops:
    def test_buy_returns_expected_keys(self, trending_ohlcv):
        price = float(trending_ohlcv["close"].iloc[-1])
        result = calculate_chandelier_stops(trending_ohlcv, price, "BUY")
        assert "error" not in result
        assert "sl_rate" in result
        assert "sl_pct" in result
        assert "trend_up" in result
        assert "supertrend_value" in result
        assert result["method"] == "chandelier"

    def test_buy_stop_below_price(self, trending_ohlcv):
        price = float(trending_ohlcv["close"].iloc[-1])
        result = calculate_chandelier_stops(trending_ohlcv, price, "BUY")
        assert result["sl_rate"] < price

    def test_sell_stop_above_price(self, trending_ohlcv):
        price = float(trending_ohlcv["close"].iloc[-1])
        result = calculate_chandelier_stops(trending_ohlcv, price, "SELL")
        assert result["sl_rate"] > price

    def test_uptrend_detected(self, trending_ohlcv):
        price = float(trending_ohlcv["close"].iloc[-1])
        result = calculate_chandelier_stops(trending_ohlcv, price, "BUY")
        assert result["trend_up"] is True

    def test_sl_pct_within_bounds(self, trending_ohlcv):
        price = float(trending_ohlcv["close"].iloc[-1])
        result = calculate_chandelier_stops(trending_ohlcv, price, "BUY",
                                            max_sl_pct=15.0, min_sl_pct=1.0)
        assert 1.0 <= result["sl_pct"] <= 15.0

    def test_invalid_price_returns_error(self, trending_ohlcv):
        result = calculate_chandelier_stops(trending_ohlcv, 0.0, "BUY")
        assert "error" in result

    def test_insufficient_data_returns_error(self):
        short_df = pd.DataFrame({
            "high": [105.0] * 10,
            "low":  [95.0] * 10,
            "close": [100.0] * 10,
        })
        result = calculate_chandelier_stops(short_df, 100.0, "BUY")
        assert "error" in result

    def test_wider_mult_gives_lower_buy_stop(self, trending_ohlcv):
        price = float(trending_ohlcv["close"].iloc[-1])
        r3 = calculate_chandelier_stops(trending_ohlcv, price, "BUY", mult=3.0)
        r5 = calculate_chandelier_stops(trending_ohlcv, price, "BUY", mult=5.0)
        assert r5["sl_rate"] < r3["sl_rate"]

    def test_downtrend_not_trend_up(self):
        prices = np.linspace(200, 100, 60)
        df = pd.DataFrame({
            "high": prices + 1,
            "low":  prices - 1,
            "close": prices,
        })
        price = float(df["close"].iloc[-1])
        result = calculate_chandelier_stops(df, price, "BUY")
        assert result["trend_up"] is False
