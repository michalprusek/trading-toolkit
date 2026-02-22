from __future__ import annotations

from datetime import datetime, time
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")

# US federal holidays (month, day) — static list covers most closures.
# Markets also close early some days (day after Thanksgiving, Christmas Eve)
# but we only track full closures here.
US_MARKET_HOLIDAYS: list[tuple[int, int]] = [
    (1, 1),    # New Year's Day
    (1, 20),   # MLK Day (approx — 3rd Monday)
    (2, 17),   # Presidents' Day (approx — 3rd Monday)
    (3, 29),   # Good Friday (varies — 2025/2026 approximate)
    (5, 26),   # Memorial Day (approx — last Monday)
    (6, 19),   # Juneteenth
    (7, 4),    # Independence Day
    (9, 1),    # Labor Day (approx — 1st Monday)
    (11, 27),  # Thanksgiving (approx — 4th Thursday)
    (12, 25),  # Christmas
]

MARKET_OPEN = time(9, 30)
MARKET_CLOSE = time(16, 0)


def is_market_open(asset_type: str = "stock") -> dict:
    """Check if the market is currently open for the given asset type.

    Returns:
        {"open": bool, "reason": str, "next_open": str | None}
    """
    if asset_type.lower() in ("crypto", "cryptocurrency"):
        return {"open": True, "reason": "Crypto markets trade 24/7", "next_open": None}

    now_et = datetime.now(ET)
    weekday = now_et.weekday()  # 0=Monday, 6=Sunday
    current_time = now_et.time()

    # Weekend check
    if weekday >= 5:
        days_until_monday = 7 - weekday
        next_open_dt = now_et.replace(
            hour=9, minute=30, second=0, microsecond=0
        )
        # Move to next Monday
        from datetime import timedelta
        next_open_dt += timedelta(days=days_until_monday)
        return {
            "open": False,
            "reason": "Weekend — US markets closed",
            "next_open": next_open_dt.strftime("%Y-%m-%d %H:%M ET"),
        }

    # Holiday check (approximate — fixed dates)
    if (now_et.month, now_et.day) in US_MARKET_HOLIDAYS:
        from datetime import timedelta
        next_day = now_et + timedelta(days=1)
        next_open_dt = next_day.replace(hour=9, minute=30, second=0, microsecond=0)
        return {
            "open": False,
            "reason": "US market holiday",
            "next_open": next_open_dt.strftime("%Y-%m-%d %H:%M ET"),
        }

    # Trading hours check
    if current_time < MARKET_OPEN:
        return {
            "open": False,
            "reason": "Pre-market — opens at 9:30 AM ET",
            "next_open": now_et.replace(
                hour=9, minute=30, second=0, microsecond=0
            ).strftime("%Y-%m-%d %H:%M ET"),
        }

    if current_time >= MARKET_CLOSE:
        from datetime import timedelta
        next_day = now_et + timedelta(days=1)
        # Skip to Monday if Friday
        if weekday == 4:
            next_day += timedelta(days=2)
        next_open_dt = next_day.replace(hour=9, minute=30, second=0, microsecond=0)
        return {
            "open": False,
            "reason": "After hours — market closed at 4:00 PM ET",
            "next_open": next_open_dt.strftime("%Y-%m-%d %H:%M ET"),
        }

    return {"open": True, "reason": "US market is open", "next_open": None}
