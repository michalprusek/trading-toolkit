"""Tests for src.market.data — analyze_market_regime and _fetch_vix_external."""
from unittest.mock import MagicMock, patch

import pytest

from src.market.data import _fetch_vix_external, analyze_market_regime


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
        # Old default (vix_ok=True): bull_score=2 → CAUTIOUS (wrong)
        assert regime["bias"] == "RISK_OFF"
        assert "vix" not in regime

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

    def test_vix_none_does_not_add_vix_key(self):
        spy = _spy_result()
        qqq = _qqq_result()
        with (
            patch("src.market.data.analyze_instrument", side_effect=[spy, qqq]),
            patch("src.market.data._fetch_vix_external", return_value=None),
        ):
            regime = analyze_market_regime()

        assert "vix" not in regime
        assert any("VIX" in e for e in regime["errors"])
