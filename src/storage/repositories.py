from __future__ import annotations

import json
from datetime import date
from typing import Any

from config import settings
from src.storage.database import get_connection


class PortfolioRepo:
    def save_snapshot(
        self,
        total_value: float,
        total_invested: float,
        total_pnl: float,
        cash_available: float,
        positions: list[dict],
    ) -> int:
        conn = get_connection()
        try:
            cur = conn.execute(
                """INSERT INTO portfolio_snapshots
                   (total_value, total_invested, total_pnl, cash_available, positions_json, num_positions, mode)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (total_value, total_invested, total_pnl, cash_available,
                 json.dumps(positions), len(positions), settings.trading_mode),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_snapshots(self, limit: int = 20, mode: str | None = None) -> list[dict]:
        conn = get_connection()
        try:
            if mode:
                rows = conn.execute(
                    "SELECT * FROM portfolio_snapshots WHERE mode = ? ORDER BY timestamp DESC LIMIT ?",
                    (mode, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT ?",
                    (limit,),
                ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()


class TradeLogRepo:
    def log_trade(
        self,
        instrument_id: int | None,
        symbol: str,
        direction: str,
        amount: float,
        status: str,
        result: dict | None = None,
        reason: str | None = None,
    ) -> int:
        conn = get_connection()
        try:
            cur = conn.execute(
                """INSERT INTO trade_log
                   (instrument_id, symbol, direction, amount, status, result_json, reason, mode)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (instrument_id, symbol, direction, amount, status,
                 json.dumps(result) if result else None, reason, settings.trading_mode),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def log_close(
        self, position_id: int, symbol: str, pnl: float | None, reason: str | None
    ) -> int:
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO position_closes (position_id, symbol, pnl, reason, mode) VALUES (?, ?, ?, ?, ?)",
                (position_id, symbol, pnl, reason, settings.trading_mode),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def get_trades(self, limit: int = 50) -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM trade_log ORDER BY timestamp DESC LIMIT ?", (limit,)
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def get_today_stats(self) -> dict:
        """Compute today's realized P&L from position_closes (the only table
        that reliably records close outcomes).  Falls back to 0 if no closes."""
        today = date.today().isoformat()
        conn = get_connection()
        try:
            row = conn.execute(
                """SELECT COALESCE(SUM(pnl), 0) AS realized_pnl,
                          COUNT(*) AS trades_count
                   FROM position_closes
                   WHERE date(timestamp) = ? AND mode = ?""",
                (today, settings.trading_mode),
            ).fetchone()
            return {
                "date": today,
                "realized_pnl": row["realized_pnl"] if row else 0,
                "trades_count": row["trades_count"] if row else 0,
            }
        finally:
            conn.close()


class MemoryRepo:
    def add(self, category: str, content: str, relevance: float = 1.0) -> int:
        conn = get_connection()
        try:
            cur = conn.execute(
                "INSERT INTO memories (category, content, relevance_score) VALUES (?, ?, ?)",
                (category, content, relevance),
            )
            conn.commit()
            return cur.lastrowid
        finally:
            conn.close()

    def list_all(self, limit: int = 50) -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY relevance_score DESC, timestamp DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def search(self, query: str) -> list[dict]:
        conn = get_connection()
        try:
            rows = conn.execute(
                "SELECT * FROM memories WHERE content LIKE ? ORDER BY relevance_score DESC",
                (f"%{query}%",),
            ).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def delete(self, memory_id: int) -> None:
        conn = get_connection()
        try:
            conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            conn.commit()
        finally:
            conn.close()


class InstrumentRepo:
    def upsert(self, instrument_id: int, symbol: str, name: str, asset_class: str) -> None:
        conn = get_connection()
        try:
            conn.execute(
                """INSERT INTO instruments (instrument_id, symbol, name, asset_class)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(instrument_id) DO UPDATE SET
                     symbol=excluded.symbol, name=excluded.name, asset_class=excluded.asset_class""",
                (instrument_id, symbol, name, asset_class),
            )
            conn.commit()
        finally:
            conn.close()

    def get_by_symbol(self, symbol: str) -> dict | None:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM instruments WHERE symbol = ? COLLATE NOCASE", (symbol,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def get_by_id(self, instrument_id: int) -> dict | None:
        conn = get_connection()
        try:
            row = conn.execute(
                "SELECT * FROM instruments WHERE instrument_id = ?", (instrument_id,)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.close()

    def delete_by_symbol(self, symbol: str) -> bool:
        conn = get_connection()
        try:
            cur = conn.execute(
                "DELETE FROM instruments WHERE symbol = ? COLLATE NOCASE", (symbol,)
            )
            conn.commit()
            return cur.rowcount > 0
        finally:
            conn.close()

