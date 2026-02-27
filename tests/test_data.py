"""Tests for src.market.data — analyze_market_regime and _fetch_vix_external."""
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from src.market.data import _build_chandelier_dict, _fetch_vix_external, analyze_market_regime


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _spy_result(trend="BULLISH", rsi=55.0, price=580.0, sma_20=570.0, sma_50=560.0):
    return {
        "price": price,
        "trend": trend,
        "rsi": rsi,
        "sma_20": sma_20,
        "sma_50": sma_50,
        "ma_alignment": {"status": "GOLDEN"},
        "rvol": 1.2,
    }


def _qqq_result(trend="BULLISH", rsi=54.0, price=470.0, sma_20=460.0, sma_50=450.0):
    return {
        "price": price,
        "trend": trend,
        "rsi": rsi,
        "sma_20": sma_20,
        "sma_50": sma_50,
    }


# ---------------------------------------------------------------------------
# _fetch_vix_external
# ---------------------------------------------------------------------------

class TestFetchVixExternal:
    def test_returns_float_on_yahoo_success(self):
        mock_data = {
            "chart": {"result": [{"meta": {"regularMarketPrice": 18.5}}]}
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_data

        with patch("src.market.data._get_vix_client") as mock_factory:
            mock_factory.return_value.get.return_value = mock_resp
            result = _fetch_vix_external()

        assert result == pytest.approx(18.5)

    def test_returns_none_on_bad_status(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 503

        with patch("src.market.data._get_vix_client") as mock_factory:
            mock_factory.return_value.get.return_value = mock_resp
            result = _fetch_vix_external()

        assert result is None

    def test_returns_none_when_price_zero(self):
        mock_data = {"chart": {"result": [{"meta": {"regularMarketPrice": 0}}]}}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_data

        with patch("src.market.data._get_vix_client") as mock_factory:
            mock_factory.return_value.get.return_value = mock_resp
            result = _fetch_vix_external()

        assert result is None

    def test_returns_none_on_network_exception(self):
        with patch("src.market.data._get_vix_client") as mock_factory:
            mock_factory.return_value.get.side_effect = Exception("timeout")
            result = _fetch_vix_external()

        assert result is None

    def test_falls_back_to_previous_close_when_regular_market_price_is_none(self):
        """regularMarketPrice=None should fall back to previousClose."""
        mock_data = {
            "chart": {"result": [{"meta": {"regularMarketPrice": None, "previousClose": 21.3}}]}
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_data

        with patch("src.market.data._get_vix_client") as mock_factory:
            mock_factory.return_value.get.return_value = mock_resp
            result = _fetch_vix_external()

        assert result == pytest.approx(21.3)

    def test_returns_none_when_result_is_null(self):
        """Yahoo returns result: null — should not crash, should return None."""
        mock_data = {"chart": {"result": None}}
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = mock_data

        with patch("src.market.data._get_vix_client") as mock_factory:
            mock_factory.return_value.get.return_value = mock_resp
            result = _fetch_vix_external()

        assert result is None


# ---------------------------------------------------------------------------
# analyze_market_regime
# ---------------------------------------------------------------------------

class TestAnalyzeMarketRegime:
    def test_risk_on_bullish_markets_low_vix(self):
        spy = _spy_result(trend="BULLISH")
        qqq = _qqq_result(trend="BULLISH")
        with (
            patch("src.market.data.analyze_instrument", side_effect=[spy, qqq]),
            patch("src.market.data._fetch_vix_external", return_value=15.0),  # < 16 → LOW
        ):
            regime = analyze_market_regime()

        assert regime["bias"] == "RISK_ON"
        assert regime["vix"]["regime"] == "LOW"
        assert regime["vix"]["sizing_adjustment"] == 1.0

    def test_risk_off_bearish_markets_extreme_vix(self):
        spy = _spy_result(trend="BEARISH", price=490.0, sma_20=510.0, sma_50=530.0)
        qqq = _qqq_result(trend="BEARISH", price=400.0, sma_20=430.0, sma_50=450.0)
        with (
            patch("src.market.data.analyze_instrument", side_effect=[spy, qqq]),
            patch("src.market.data._fetch_vix_external", return_value=38.0),
        ):
            regime = analyze_market_regime()

        assert regime["bias"] == "RISK_OFF"
        assert regime["vix"]["regime"] == "EXTREME"
        assert regime["vix"]["sizing_adjustment"] == 0.25

    def test_unknown_bias_when_both_indices_fail(self):
        with (
            patch("src.market.data.analyze_instrument", return_value={"error": "unreachable"}),
            patch("src.market.data._fetch_vix_external", return_value=None),
        ):
            regime = analyze_market_regime()

        assert regime["bias"] == "UNKNOWN"
        assert "spy" not in regime
        assert "qqq" not in regime

    def test_vix_unavailable_treated_as_conservative(self):
        """When VIX=None, vix_ok=False — must not inflate bull_score."""
        # Only SPY bullish (qqq bearish, SPY below both SMAs) → bull_score = 1 without VIX
        spy = _spy_result(trend="BULLISH", price=490.0, sma_20=510.0, sma_50=530.0)
        qqq = _qqq_result(trend="BEARISH")
        with (
            patch("src.market.data.analyze_instrument", side_effect=[spy, qqq]),
            patch("src.market.data._fetch_vix_external", return_value=None),
        ):
            regime = analyze_market_regime()

        # spy_bull=T, qqq_bull=F, above_sma20=F (490<510), above_sma50=F (490<530), vix_ok=F → 1 → RISK_OFF
        assert regime["bias"] == "RISK_OFF"
        # VIX key is always present with safe defaults when fetch fails
        assert regime["vix"]["value"] is None
        assert regime["vix"]["regime"] == "UNKNOWN"
        assert regime["vix"]["sizing_adjustment"] == 1.0

    def test_elevated_vix_reduces_sizing(self):
        spy = _spy_result()
        qqq = _qqq_result()
        with (
            patch("src.market.data.analyze_instrument", side_effect=[spy, qqq]),
            patch("src.market.data._fetch_vix_external", return_value=22.5),
        ):
            regime = analyze_market_regime()

        assert regime["vix"]["regime"] == "ELEVATED"
        assert regime["vix"]["sizing_adjustment"] == 0.75

    def test_errors_list_populated_on_index_failure(self):
        spy = _spy_result()
        with (
            patch(
                "src.market.data.analyze_instrument",
                side_effect=[spy, {"error": "QQQ not found"}],
            ),
            patch("src.market.data._fetch_vix_external", return_value=18.0),
        ):
            regime = analyze_market_regime()

        assert any("QQQ" in e for e in regime["errors"])
        assert "qqq" not in regime

    def test_vix_none_provides_safe_defaults(self):
        spy = _spy_result()
        qqq = _qqq_result()
        with (
            patch("src.market.data.analyze_instrument", side_effect=[spy, qqq]),
            patch("src.market.data._fetch_vix_external", return_value=None),
        ):
            regime = analyze_market_regime()

        # VIX key always present with safe defaults — prevents KeyError in callers
        assert regime["vix"]["value"] is None
        assert regime["vix"]["regime"] == "UNKNOWN"
        assert regime["vix"]["sizing_adjustment"] == 1.0
        assert any("VIX" in e for e in regime["errors"])

    def test_cautious_bias_mixed_signals(self):
        """bull_score=2 should produce CAUTIOUS, not RISK_ON or RISK_OFF."""
        # spy_bull=T, qqq_bull=F, above_sma20=T, above_sma50=F, vix_ok=F → score=2 → CAUTIOUS
        spy = _spy_result(trend="BULLISH", price=580.0, sma_20=570.0, sma_50=600.0)
        qqq = _qqq_result(trend="BEARISH")
        with (
            patch("src.market.data.analyze_instrument", side_effect=[spy, qqq]),
            patch("src.market.data._fetch_vix_external", return_value=None),
        ):
            regime = analyze_market_regime()

        assert regime["bias"] == "CAUTIOUS"

    def test_vix_high_regime_50pct_sizing(self):
        """VIX in HIGH range (25-30) should give 0.5x sizing adjustment."""
        spy = _spy_result()
        qqq = _qqq_result()
        with (
            patch("src.market.data.analyze_instrument", side_effect=[spy, qqq]),
            patch("src.market.data._fetch_vix_external", return_value=27.5),
        ):
            regime = analyze_market_regime()

        assert regime["vix"]["regime"] == "HIGH"
        assert regime["vix"]["sizing_adjustment"] == 0.5

    def test_vix_very_low_regime_full_sizing(self):
        """VIX < 13 (VERY_LOW) should give 1.0x sizing (complacency, not panic)."""
        spy = _spy_result()
        qqq = _qqq_result()
        with (
            patch("src.market.data.analyze_instrument", side_effect=[spy, qqq]),
            patch("src.market.data._fetch_vix_external", return_value=11.5),
        ):
            regime = analyze_market_regime()

        assert regime["vix"]["regime"] == "VERY_LOW"
        assert regime["vix"]["sizing_adjustment"] == 1.0


# ---------------------------------------------------------------------------
# _build_chandelier_dict
# ---------------------------------------------------------------------------

class TestBuildChandelierDict:
    def _make_series(self, val):
        return pd.Series([val])

    def test_returns_dict_when_all_values_valid(self):
        result = _build_chandelier_dict(
            self._make_series(150.0),
            self._make_series(155.0),
            self._make_series(1),    # direction=1 → trend_up=True
            self._make_series(148.0),
        )
        assert result is not None
        assert result["long_stop"] == pytest.approx(150.0)
        assert result["short_stop"] == pytest.approx(155.0)
        assert result["trend_up"] is True
        assert result["supertrend"] == pytest.approx(148.0)

    def test_trend_up_false_when_direction_is_minus_1(self):
        result = _build_chandelier_dict(
            self._make_series(150.0),
            self._make_series(155.0),
            self._make_series(-1),   # direction=-1 → trend_up=False
            self._make_series(157.0),
        )
        assert result is not None
        assert result["trend_up"] is False

    def test_returns_none_when_long_stop_is_nan(self):
        import numpy as np
        result = _build_chandelier_dict(
            self._make_series(float("nan")),
            self._make_series(155.0),
            self._make_series(1),
            self._make_series(148.0),
        )
        assert result is None

    def test_returns_none_when_supertrend_is_nan(self):
        import numpy as np
        result = _build_chandelier_dict(
            self._make_series(150.0),
            self._make_series(155.0),
            self._make_series(1),
            self._make_series(float("nan")),
        )
        assert result is None

    def test_returns_none_when_direction_is_nan(self):
        result = _build_chandelier_dict(
            self._make_series(150.0),
            self._make_series(155.0),
            self._make_series(float("nan")),
            self._make_series(148.0),
        )
        assert result is None
