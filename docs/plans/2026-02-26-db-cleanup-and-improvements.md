# DB Cleanup + Mode Tagging + Command Improvements

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Remove demo data from DB, add mode tagging to prevent recurrence, fix close_position symbol bug, improve sector rotation and portfolio benchmark in morning-check/analyze-portfolio.

**Architecture:** Schema migration adds `mode` column to 3 tables. Repos pass `settings.trading_mode` on every insert. Commands use 20-day RS for sectors and mode-filtered snapshots for benchmark.

**Tech Stack:** SQLite (ALTER TABLE), Python, existing repo/engine patterns.

---

### Task 1: One-time DB Cleanup

**Files:**
- Script only (no permanent file)

Delete demo data:
- 3 snapshots with total_value > $50K (ids 1, 2, 6)
- 5 position_closes with symbol='' AND pnl IS NULL (broken records from close_position bug)
- Deduplicate position_close for pos 3437553365 (keep the one with reason)

Verify counts before and after.

### Task 2: Schema Migration — add `mode` column

**Files:**
- Modify: `src/storage/database.py` — add mode column to schema + migration logic in init_db()

Add `mode TEXT NOT NULL DEFAULT 'real'` to: portfolio_snapshots, trade_log, position_closes.
Use ALTER TABLE IF NOT EXISTS pattern for migration of existing DBs.

### Task 3: Repository Updates — pass mode on inserts

**Files:**
- Modify: `src/storage/repositories.py` — PortfolioRepo.save_snapshot(), TradeLogRepo.log_trade(), TradeLogRepo.log_close()

Each insert includes `settings.trading_mode` in the mode column.

### Task 4: Fix close_position symbol bug

**Files:**
- Modify: `src/trading/engine.py:138-175` — close_position() should extract symbol from portfolio before logging

The bug: line 165 always logs `symbol=""`. Fix: capture symbol during the instrument_id lookup loop.

### Task 5: Sector Rotation — use 20-day RS instead of 1-day gap

**Files:**
- Modify: `.claude/commands/morning-check.md` — Phase 0.5 sector rotation code
- Modify: `.claude/commands/analyze-portfolio.md` — same section if present

Replace gap% comparison with 20-day return comparison. Always meaningful regardless of time-of-day.

### Task 6: Portfolio Benchmark — mode-filtered, rolling 20-day

**Files:**
- Modify: `.claude/commands/morning-check.md` — Phase 2 benchmark code

Filter snapshots by mode. Use rolling 20-day window (not since-inception). Graceful fallback if < 2 snapshots.

### Task 7: 52-week Range via Yahoo Finance Fallback

**Files:**
- Modify: `.claude/commands/morning-check.md` — Phase 0 fundamental flash code

When fundamentals API returns null for high_52w/low_52w, fetch from Yahoo Finance chart API (52-week range from `meta.fiftyTwoWeekHigh/Low`).

### Task 8: Tests

**Files:**
- Modify: `tests/test_risk.py` or new `tests/test_repos.py`

Test mode column in save_snapshot and log_trade.
Test close_position extracts symbol correctly (mock).
