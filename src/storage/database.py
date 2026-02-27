from __future__ import annotations

import sqlite3
from pathlib import Path

from config import settings

SCHEMA = """
CREATE TABLE IF NOT EXISTS portfolio_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    total_value REAL NOT NULL,
    total_invested REAL NOT NULL,
    total_pnl REAL NOT NULL,
    cash_available REAL NOT NULL,
    positions_json TEXT NOT NULL,
    num_positions INTEGER NOT NULL,
    mode TEXT NOT NULL DEFAULT 'real'
);

CREATE TABLE IF NOT EXISTS trade_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    instrument_id INTEGER,
    symbol TEXT NOT NULL,
    direction TEXT NOT NULL,
    amount REAL NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('executed','rejected','error')),
    result_json TEXT,
    reason TEXT,
    mode TEXT NOT NULL DEFAULT 'real'
);

CREATE TABLE IF NOT EXISTS position_closes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    position_id INTEGER NOT NULL,
    symbol TEXT NOT NULL,
    pnl REAL,
    reason TEXT,
    mode TEXT NOT NULL DEFAULT 'real'
);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL DEFAULT (datetime('now')),
    category TEXT NOT NULL CHECK(category IN ('lesson','pattern','market_note')),
    content TEXT NOT NULL,
    relevance_score REAL DEFAULT 1.0
);

CREATE TABLE IF NOT EXISTS instruments (
    instrument_id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    name TEXT,
    asset_class TEXT
);

CREATE TABLE IF NOT EXISTS daily_pnl (
    date TEXT PRIMARY KEY,
    realized_pnl REAL DEFAULT 0,
    unrealized_pnl REAL DEFAULT 0,
    portfolio_value REAL DEFAULT 0,
    trades_count INTEGER DEFAULT 0
);
"""


def get_connection() -> sqlite3.Connection:
    db_path = Path(settings.db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


_MIGRATIONS = [
    # Add mode column to tables that predate mode tracking
    ("portfolio_snapshots", "mode", "ALTER TABLE portfolio_snapshots ADD COLUMN mode TEXT NOT NULL DEFAULT 'real'"),
    ("trade_log", "mode", "ALTER TABLE trade_log ADD COLUMN mode TEXT NOT NULL DEFAULT 'real'"),
    ("position_closes", "mode", "ALTER TABLE position_closes ADD COLUMN mode TEXT NOT NULL DEFAULT 'real'"),
]


def _run_migrations(conn: sqlite3.Connection) -> None:
    for table, column, sql in _MIGRATIONS:
        cols = {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            conn.execute(sql)


def init_db() -> None:
    conn = get_connection()
    try:
        conn.executescript(SCHEMA)
        _run_migrations(conn)
        conn.commit()
    finally:
        conn.close()
