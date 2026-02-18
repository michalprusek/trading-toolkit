# eToro Public API endpoint paths
# All endpoints go through public-api.etoro.com
#
# Demo/real prefix pattern: /api/v1/trading/{section}/{demo/}{action}
# e.g. /api/v1/trading/info/demo/portfolio
#      /api/v1/trading/execution/demo/market-open-orders/by-amount

from config import settings


# ── Market Data (no demo/real prefix) ─────────────────────────────────

SEARCH = "/api/v1/market-data/search"
INSTRUMENT_RATES = "/api/v1/market-data/instruments/rates"
CANDLES = "/api/v1/market-data/instruments/{instrument_id}/history/candles/{direction}/{period}/{count}"

# ── Portfolio / Account ───────────────────────────────────────────────

def portfolio_path() -> str:
    return f"/api/v1/trading/info/{settings.mode_prefix}portfolio"


# ── Trading Execution ─────────────────────────────────────────────────

def open_trade_path() -> str:
    return f"/api/v1/trading/execution/{settings.mode_prefix}market-open-orders/by-amount"


def close_trade_path(position_id: int) -> str:
    return f"/api/v1/trading/execution/{settings.mode_prefix}market-close-orders/positions/{position_id}"


def limit_order_path() -> str:
    return f"/api/v1/trading/execution/{settings.mode_prefix}limit-orders"


# ── Watchlists ────────────────────────────────────────────────────────

WATCHLISTS = "/api/v1/watchlists"
