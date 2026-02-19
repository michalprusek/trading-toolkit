from __future__ import annotations

from typing import Any

from src.api.client import EtoroClient
from src.api import endpoints
from src.api.models import Position, PortfolioSummary
from src.market.data import get_rates
from src.storage.repositories import PortfolioRepo, InstrumentRepo


_client: EtoroClient | None = None


def _get_client() -> EtoroClient:
    global _client
    if _client is None:
        _client = EtoroClient()
    return _client


def enrich_positions_with_rates(positions: list[Position]) -> list[Position]:
    """Fetch live rates for positions missing current_rate and recompute P&L."""
    needs_rate = [p for p in positions if p.current_rate is None or p.current_rate == 0]
    if not needs_rate:
        return positions

    iids = list({p.instrument_id for p in needs_rate})
    try:
        rates = get_rates(iids)
    except Exception:
        return positions

    rate_map = {r.instrument_id: r.mid for r in rates}

    for p in positions:
        if (p.current_rate is None or p.current_rate == 0) and p.instrument_id in rate_map:
            live_price = rate_map[p.instrument_id]
            p.current_rate = live_price
            if p.open_rate and p.open_rate > 0:
                units = p.amount / p.open_rate
                if p.is_buy:
                    p.net_profit = units * (live_price - p.open_rate)
                else:
                    p.net_profit = units * (p.open_rate - live_price)

    return positions


def get_portfolio() -> PortfolioSummary:
    client = _get_client()
    data = client.get(endpoints.portfolio_path())

    # Public API wraps response in "clientPortfolio"
    portfolio_data = data.get("clientPortfolio", data)

    positions_raw = portfolio_data.get("positions", portfolio_data.get("Positions", []))
    positions = [Position.model_validate(p) for p in positions_raw]

    # Enrich positions with live rates when API returns zeros (e.g. market closed)
    positions = enrich_positions_with_rates(positions)

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
        live_price = p.current_rate if p.current_rate else p.open_rate
        current_value = p.amount + p.net_profit
        result.append({
            "position_id": p.position_id,
            "instrument_id": p.instrument_id,
            "symbol": symbol,
            "name": name,
            "direction": p.direction,
            "amount": p.amount,
            "open_rate": p.open_rate,
            "current_rate": p.current_rate,
            "live_price": live_price,
            "current_value": round(current_value, 2),
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
