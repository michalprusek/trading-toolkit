from unittest.mock import patch, MagicMock

import pytest

from config import AggressiveRiskLimits
from src.api.models import Position, PortfolioSummary
from src.trading.risk import check_trade


def _mock_portfolio(
    positions: int = 5,
    total_invested: float = 5000,
    total_pnl: float = 200,
    cash: float = 5000,
) -> PortfolioSummary:
    pos_list = []
    for i in range(positions):
        pos_list.append(
            Position.model_validate({
                "PositionID": 1000 + i,
                "InstrumentID": 100 + i,
                "IsBuy": True,
                "Amount": total_invested / max(positions, 1),
                "OpenRate": 100.0,
                "NetProfit": total_pnl / max(positions, 1),
                "Leverage": 1,
            })
        )
    return PortfolioSummary(
        positions=pos_list,
        total_invested=total_invested,
        total_pnl=total_pnl,
        cash_available=cash,
    )


class TestRiskCheck:
    @patch("src.trading.risk.get_portfolio")
    def test_normal_trade_passes(self, mock_portfolio):
        mock_portfolio.return_value = _mock_portfolio()
        result = check_trade("AAPL", 500, "BUY")
        assert result.passed

    @patch("src.trading.risk.get_portfolio")
    def test_below_minimum_rejected(self, mock_portfolio):
        mock_portfolio.return_value = _mock_portfolio()
        result = check_trade("AAPL", 5, "BUY")
        assert not result.passed
        assert any("below minimum" in v for v in result.violations)

    @patch("src.trading.risk.get_portfolio")
    def test_above_maximum_rejected(self, mock_portfolio):
        mock_portfolio.return_value = _mock_portfolio()
        result = check_trade("AAPL", 5000, "BUY")
        assert not result.passed
        assert any("exceeds maximum" in v for v in result.violations)

    @patch("src.trading.risk.get_portfolio")
    def test_max_positions_rejected(self, mock_portfolio):
        mock_portfolio.return_value = _mock_portfolio(positions=20)
        result = check_trade("AAPL", 100, "BUY")
        assert not result.passed
        assert any("max positions" in v for v in result.violations)

    @patch("src.trading.risk.get_portfolio")
    def test_leverage_rejected(self, mock_portfolio):
        mock_portfolio.return_value = _mock_portfolio()
        result = check_trade("AAPL", 100, "BUY", leverage=5.0)
        assert not result.passed
        assert any("Leverage" in v for v in result.violations)

    @patch("src.trading.risk.get_portfolio")
    def test_high_exposure_warning(self, mock_portfolio):
        mock_portfolio.return_value = _mock_portfolio(
            total_invested=8000, cash=2000, total_pnl=0
        )
        result = check_trade("AAPL", 500, "BUY")
        assert any("High exposure" in w for w in result.warnings)

    @patch("src.trading.risk.get_portfolio")
    def test_short_has_cfd_warning(self, mock_portfolio):
        mock_portfolio.return_value = _mock_portfolio()
        result = check_trade("AAPL", 100, "SELL")
        assert any("overnight" in w.lower() for w in result.warnings)

    @patch("src.trading.risk.get_portfolio")
    def test_concentration_rejected(self, mock_portfolio):
        mock_portfolio.return_value = _mock_portfolio(
            total_invested=1000, cash=1000, total_pnl=0
        )
        result = check_trade("AAPL", 500, "BUY")
        assert not result.passed
        assert any("portfolio" in v.lower() for v in result.violations)


class TestLimitsOverride:
    @patch("src.trading.risk.get_portfolio")
    def test_aggressive_allows_larger_trade(self, mock_portfolio):
        """AggressiveRiskLimits allows $2000 trade (default $1000 max would reject)."""
        mock_portfolio.return_value = _mock_portfolio(
            total_invested=5000, cash=15000, total_pnl=0
        )
        aggressive = AggressiveRiskLimits()
        result = check_trade("AAPL", 2000, "BUY", limits_override=aggressive)
        assert result.passed

    @patch("src.trading.risk.get_portfolio")
    def test_aggressive_still_rejects_over_max(self, mock_portfolio):
        """AggressiveRiskLimits still rejects $6000 (over $5000 max)."""
        mock_portfolio.return_value = _mock_portfolio(
            total_invested=5000, cash=15000, total_pnl=0
        )
        aggressive = AggressiveRiskLimits()
        result = check_trade("AAPL", 6000, "BUY", limits_override=aggressive)
        assert not result.passed
        assert any("exceeds maximum" in v for v in result.violations)

    @patch("src.trading.risk.get_portfolio")
    def test_default_limits_unchanged_without_override(self, mock_portfolio):
        """Default limits reject $2000 when no override is passed."""
        mock_portfolio.return_value = _mock_portfolio(
            total_invested=5000, cash=15000, total_pnl=0
        )
        result = check_trade("AAPL", 2000, "BUY")
        assert not result.passed
        assert any("exceeds maximum" in v for v in result.violations)

    @patch("src.trading.risk.get_portfolio")
    def test_aggressive_rejects_below_min(self, mock_portfolio):
        """AggressiveRiskLimits rejects $30 (below $50 min)."""
        mock_portfolio.return_value = _mock_portfolio()
        aggressive = AggressiveRiskLimits()
        result = check_trade("AAPL", 30, "BUY", limits_override=aggressive)
        assert not result.passed
        assert any("below minimum" in v for v in result.violations)
