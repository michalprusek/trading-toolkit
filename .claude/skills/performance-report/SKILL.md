---
name: performance-report
description: >
  Generate a trading performance report from the SQLite trade log.
  Calculates win rate, average realized P&L, best/worst trades by symbol,
  and shows last 30 days of daily P&L. Flags positions held >14 days (CFD
  overnight fee drag risk). Use when the user asks for a performance review,
  P&L summary, or trade stats. Also invoked automatically by morning-check
  and analyze-portfolio.
---

# Performance Report

Generate a comprehensive trading performance report using the local SQLite database.

## Step 1 — Check trade history

Run the CLI history command:

    python3 cli.py history

## Step 2 — Query key metrics from the DB

Run this Python snippet to compute the report:

    import sqlite3, os
    os.environ.setdefault('TRADING_MODE', 'real')
    db_path = 'data/etoro.db'
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Recent trade log (schema: id, timestamp, instrument_id, symbol, direction, amount, status, result_json, reason)
    trades = conn.execute("""
        SELECT symbol, direction, amount, timestamp, status
        FROM trade_log ORDER BY timestamp DESC LIMIT 100
    """).fetchall()

    # Closed positions (schema: id, timestamp, position_id, symbol, pnl, reason)
    closes = conn.execute("""
        SELECT symbol, pnl, reason, timestamp
        FROM position_closes ORDER BY timestamp DESC
    """).fetchall()

    # Daily P&L (schema: date, realized_pnl, unrealized_pnl, portfolio_value, trades_count)
    daily = conn.execute("""
        SELECT date, realized_pnl, unrealized_pnl, portfolio_value
        FROM daily_pnl ORDER BY date DESC LIMIT 30
    """).fetchall()
    conn.close()

    if closes:
        profits = [c['pnl'] for c in closes if c['pnl'] is not None]
        wins = [p for p in profits if p > 0]
        losses = [p for p in profits if p <= 0]
        win_rate = len(wins) / len(profits) * 100 if profits else 0
        avg_win = sum(wins) / len(wins) if wins else 0
        avg_loss = sum(losses) / len(losses) if losses else 0
        total_pnl = sum(profits)
        best = max(profits) if profits else 0
        worst = min(profits) if profits else 0
        print(f"Closed trades: {len(profits)}")
        print(f"Win rate:      {win_rate:.1f}%")
        print(f"Avg win:       ${avg_win:.2f} | Avg loss: ${avg_loss:.2f}")
        print(f"Total P&L:     ${total_pnl:.2f}")
        print(f"Best trade:    ${best:.2f} | Worst: ${worst:.2f}")
        print()
        # Last 5 closed trades
        print("Last 5 closed trades:")
        for c in closes[:5]:
            sign = '+' if c['pnl'] >= 0 else ''
            print(f"  {c['symbol']:<8} {sign}${c['pnl']:.2f}  [{c['timestamp'][:10]}]  reason={c['reason']}")
    else:
        print("No closed trades found in position_closes table.")

    print(f"\nRecent opens (trade_log): {len(trades)}")
    for t in trades[:5]:
        print(f"  {t['symbol']:<8} {t['direction']} ${t['amount']}  [{t['timestamp'][:10]}]")

    if daily:
        print(f"\nLast 7 days P&L:")
        for d in daily[:7]:
            sign = '+' if d['realized_pnl'] >= 0 else ''
            print(f"  {d['date']}  realized {sign}${d['realized_pnl']:.2f}  unrealized ${d['unrealized_pnl']:.2f}  portfolio ${d['portfolio_value']:.2f}")

## Step 3 — Live portfolio P&L

    python3 cli.py portfolio

## Step 4 — Present report

Format the output as a markdown summary table:

| Metric | Value |
|--------|-------|
| Closed Trades | N |
| Win Rate | X% |
| Avg Win | $X |
| Avg Loss | $X |
| Total Realized P&L | $X |
| Best Trade | $X |
| Worst Trade | $X |

Flag any open position held >14 days as ⚠️ CFD fee drag risk (per CLAUDE.md: overnight fees ~$0.22/day per $1K for leveraged/short positions; unleveraged BUY stocks/ETFs have NO overnight fees).

Flag any position without SL/TSL and give the exact Chandelier stop value by running:

    python3 cli.py market analyze SYMBOL
