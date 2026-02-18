from __future__ import annotations

from typing import Any

from src.api.client import EtoroClient
from src.api import endpoints
from src.api.models import Position, PortfolioSummary
from src.storage.repositories import PortfolioRepo, InstrumentRepo


_client: EtoroClient | None = None


def _get_client() -> EtoroClient:
    global _client
    if _client is None:
        _client = EtoroClient()
    return _client


def get_portfolio() -> PortfolioSummary:
    client = _get_client()
    data = client.get(endpoints.portfolio_path())

    # Public API wraps response in "clientPortfolio"
    portfolio_data = data.get("clientPortfolio", data)

    positions_raw = portfolio_data.get("positions", portfolio_data.get("Positions", []))
    positions = [Position.model_validate(p) for p in positions_raw]

    credit = portfolio_data.get("credit", portfolio_data.get("CreditByRealizedEquity", 0))
    total_invested = sum(p.amount for p in positions)
    total_pnl = sum(p.net_profit for p in positions)

    return PortfolioSummary(
        positions=positions,
        total_invested=total_invested,
        total_pnl=total_pnl,
        cash_available=credit,
    )


def get_positions_with_symbols() -> list[dict]:
    portfolio = get_portfolio()
    inst_repo = InstrumentRepo()

    result = []
    for p in portfolio.positions:
        inst = inst_repo.get_by_id(p.instrument_id)
        symbol = inst["symbol"] if inst else f"ID:{p.instrument_id}"
        name = inst["name"] if inst else ""
        result.append({
            "position_id": p.position_id,
            "instrument_id": p.instrument_id,
            "symbol": symbol,
            "name": name,
            "direction": p.direction,
            "amount": p.amount,
            "open_rate": p.open_rate,
            "current_rate": p.current_rate,
            "net_profit": p.net_profit,
            "pnl_pct": p.pnl_pct,
            "leverage": p.leverage,
            "stop_loss_rate": p.stop_loss_rate,
            "take_profit_rate": p.take_profit_rate,
            "open_date": p.open_date,
        })
    return result


def save_snapshot() -> int:
    portfolio = get_portfolio()
    positions = get_positions_with_symbols()
    repo = PortfolioRepo()
    return repo.save_snapshot(
        total_value=portfolio.total_value,
        total_invested=portfolio.total_invested,
        total_pnl=portfolio.total_pnl,
        cash_available=portfolio.cash_available,
        positions=positions,
    )


def get_snapshot_history(limit: int = 20) -> list[dict]:
    repo = PortfolioRepo()
    return repo.get_snapshots(limit)


def get_watchlists() -> list[dict]:
    client = _get_client()
    data = client.get(endpoints.WATCHLISTS)
    if isinstance(data, list):
        return data
    return data.get("watchlists", data.get("Watchlists", []))
