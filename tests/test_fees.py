import pytest

from src.trading.fees import estimate_fees, _map_asset_class, FeeEstimate


class TestEstimateFees:
    def test_stock_no_leverage(self):
        fee = estimate_fees(500, 0.05, "stocks", 1.0, False)
        assert isinstance(fee, FeeEstimate)
        assert fee.spread_cost == 0.25  # 500 * 0.05%
        assert fee.crypto_fee == 0
        assert fee.overnight_daily == 0  # No CFD
        assert fee.total_entry_cost == 0.25
        assert fee.total_1month_cost == 0.25

    def test_stock_with_leverage(self):
        fee = estimate_fees(500, 0.05, "stocks", 2.0, False)
        assert fee.spread_cost == 0.25
        assert fee.overnight_daily > 0  # CFD due to leverage
        notional = 500 * 2.0
        expected_daily = notional * (6.4 / 100) / 365
        assert fee.overnight_daily == round(expected_daily, 2)
        assert fee.overnight_monthly == round(expected_daily * 30, 2)

    def test_short_position(self):
        fee = estimate_fees(500, 0.05, "stocks", 1.0, True)
        assert fee.overnight_daily > 0  # CFD due to short

    def test_crypto_unleveraged(self):
        fee = estimate_fees(1000, 0.5, "crypto", 1.0, False)
        assert fee.crypto_fee == 10.0  # 1% of 1000
        assert fee.spread_cost == 5.0   # 1000 * 0.5%
        assert fee.overnight_daily == 0  # No CFD
        assert fee.total_entry_cost == 15.0

    def test_crypto_leveraged(self):
        fee = estimate_fees(1000, 0.5, "crypto", 2.0, False)
        assert fee.crypto_fee == 0  # No crypto fee for CFD
        assert fee.overnight_daily > 0  # crypto_cfd rate

    def test_zero_amount(self):
        fee = estimate_fees(0, 0.1, "stocks")
        assert fee.spread_cost == 0
        assert fee.total_entry_cost == 0
        assert fee.total_1month_cost == 0
        assert fee.cost_pct == 0

    def test_cost_pct(self):
        fee = estimate_fees(1000, 0.1, "stocks", 1.0, False)
        expected_entry = 1000 * 0.001
        assert fee.cost_pct == pytest.approx(expected_entry / 1000 * 100, abs=0.01)


class TestMapAssetClass:
    def test_known_classes(self):
        assert _map_asset_class(5) == "stocks"
        assert _map_asset_class(4) == "crypto"
        assert _map_asset_class(3) == "forex"
        assert _map_asset_class(10) == "etf"
        assert _map_asset_class(6) == "indices"
        assert _map_asset_class(2) == "commodities"
        assert _map_asset_class(73) == "crypto"

    def test_unknown_class(self):
        assert _map_asset_class(999) == "stocks"

    def test_string_input(self):
        assert _map_asset_class("5") == "stocks"
        assert _map_asset_class("4") == "crypto"

    def test_invalid_input(self):
        assert _map_asset_class("abc") == "stocks"
        assert _map_asset_class(None) == "stocks"
