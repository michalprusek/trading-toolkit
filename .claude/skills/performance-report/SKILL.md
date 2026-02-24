---
name: performance-report
description: >
  Generate a trading performance report from the SQLite trade log.
  Calculates win rate, average realized P&L, best/worst trades by symbol,
  and flags CFD positions held >14 days (overnight fee drag risk).
  Use when the user asks for a performance review, P&L summary, or trade stats.
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

    trades = conn.execute("""
        SELECT symbol, direction, amount, open_rate, created_at, status
        FROM trade_log ORDER BY created_at DESC LIMIT 100
    """).fetchall()

    closes = conn.execute("""
        SELECT symbol, net_profit, close_reason, closed_at
        FROM position_closes ORDER BY closed_at DESC
    """).fetchall()

    daily = conn.execute("""
        SELECT date, daily_pnl, cumulative_pnl
        FROM daily_pnl ORDER BY date DESC LIMIT 30
    """).fetchall()
    conn.close()

    if closes:
        profits = [c['net_profit'] for c in closes if c['net_profit'] is not None]
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
    else:
        print("No closed trades found in position_closes table.")

    print(f"\nRecent opens (trade_log): {len(trades)}")
    for t in trades[:5]:
        print(f"  {t['symbol']} {t['direction']} ${t['amount']} @ {t['open_rate']} [{t['created_at'][:10]}]")

## Step 3 — Live portfolio P&L

    python3 cli.py portfolio

## Step 4 — Present report

Format the output as a markdown summary table:

| Metric | Value |
|--------|-------|
| Win Rate | X% |
| Avg Win | $X |
| Avg Loss | $X |
| Total Realized P&L | $X |
| Open Positions | X |

Flag any open position held >14 days as ⚠️ CFD fee drag risk (per CLAUDE.md: overnight fees ~$0.22/day per $1K).

Flag any position without SL/TSL and give the exact Chandelier stop value by running:

    python3 cli.py market analyze SYMBOL
