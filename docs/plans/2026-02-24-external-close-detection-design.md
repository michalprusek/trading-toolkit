# External Close Detection — Design Doc

**Date:** 2026-02-24

## Goal

Automatically detect positions closed externally (SL hit, TP hit, TSL hit, or manual close in eToro UI) and record them in `position_closes` so the trade-journal agent and performance-report have complete data.

## Constraint

eToro Public API has no closed-positions endpoint. Detection is done by comparing the live portfolio against the last `portfolio_snapshots` entry.

## Approach

Agent-side only — no new Python code in `src/`. Logic lives in the `trade-journal` agent instructions and in `morning-check.md` Phase 0.

## Detection Logic

```
1. GET live positions via: python3 cli.py portfolio --format json
   → Extract set of live position_ids

2. GET last snapshot:
   SELECT positions_json FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1
   → Extract set of snapshot position_ids + full position data dict

3. disappeared = snapshot_ids − live_ids

4. Already recorded:
   SELECT position_id FROM position_closes WHERE position_id IN (...)
   → Skip duplicates

5. For each new disappearance:
   a) Fetch live rate: python3 cli.py market price SYMBOL
   b) Compute P&L:
      units = amount / open_rate
      pnl = units * (live_rate - open_rate)   # BUY
      pnl = units * (open_rate - live_rate)   # SELL
   c) Infer reason:
      if abs(live_rate - sl_rate) / live_rate < 0.005 → "SL"
      if abs(live_rate - tp_rate) / live_rate < 0.005 → "TP"
      if pnl > 0 → "TSL"  (can't distinguish TSL from manual profit)
      else → "manual"
   d) INSERT INTO position_closes (position_id, symbol, pnl, reason)
```

## P&L Accuracy

Live rate at detection time ≠ actual close price. For SL hits detected hours later, price may have rebounded. This is a known limitation; P&L is approximate.

## Integration Points

1. `trade-journal.md` — reconciliation step at the top, before journaling specific symbol
2. `morning-check.md` Phase 0 — Python block after portfolio load, before health checks

## Files Changed

- `.claude/agents/trade-journal.md` — add reconciliation logic at top
- `.claude/commands/morning-check.md` — add reconciliation block in Phase 0
