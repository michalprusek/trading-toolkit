# External Close Detection Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Detect positions closed externally (SL/TP/TSL/manual) by comparing live portfolio to last snapshot, and record them in `position_closes` — integrated into `trade-journal` agent and `morning-check` Phase 0.

**Architecture:** Agent-side only (Approach C). Reconciliation runs as inline Python via Bash. No new code in `src/`. Two integration points: `trade-journal.md` (on-demand) and `morning-check.md` Phase 0 (automatic). Uses `portfolio_snapshots.positions_json` as source of truth for last known state; fetches live rate via `get_rate()` for P&L computation.

**Tech Stack:** Python 3.12, SQLite (`data/etoro.db`), existing `src.portfolio.manager.get_portfolio()`, existing `src.market.data.get_rate()`

**Snapshot keys available:** `position_id`, `instrument_id`, `symbol`, `direction`, `amount`, `open_rate`, `current_rate`, `stop_loss_rate`, `take_profit_rate`, `net_profit`

---

### Task 1: Build and verify the reconciliation Python script

**Files:**
- No file creation — just verify the script works against the real DB before embedding it anywhere

**The reconciliation script (copy exactly):**

```python
import sqlite3, json, os
os.environ.setdefault('TRADING_MODE', 'real')

# Step 1: Get last snapshot
conn = sqlite3.connect('data/etoro.db')
conn.row_factory = sqlite3.Row
snap = conn.execute(
    'SELECT positions_json FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1'
).fetchone()

if not snap:
    print('No snapshot found — skipping reconciliation')
    conn.close()
else:
    snapshot_positions = json.loads(snap['positions_json'])
    snapshot_by_id = {p['position_id']: p for p in snapshot_positions if p.get('position_id')}

    # Step 2: Get live portfolio position_ids
    from src.portfolio.manager import get_portfolio
    portfolio = get_portfolio()
    live_ids = {p.position_id for p in portfolio.positions}

    # Step 3: Find disappeared positions
    disappeared_ids = set(snapshot_by_id.keys()) - live_ids

    if not disappeared_ids:
        print('No new external closes detected')
        conn.close()
    else:
        # Step 4: Skip already recorded
        placeholders = ','.join('?' * len(disappeared_ids))
        already_recorded = {
            r[0] for r in conn.execute(
                f'SELECT position_id FROM position_closes WHERE position_id IN ({placeholders})',
                list(disappeared_ids)
            ).fetchall()
        }
        new_closes = disappeared_ids - already_recorded

        if not new_closes:
            print(f'{len(disappeared_ids)} closed position(s) already recorded — nothing new')
            conn.close()
        else:
            # Step 5: Fetch live rate, compute P&L, infer reason, write to DB
            from src.market.data import get_rate

            for pid in new_closes:
                pos = snapshot_by_id[pid]
                symbol      = pos['symbol']
                open_rate   = pos.get('open_rate') or 0
                sl_rate     = pos.get('stop_loss_rate') or 0
                tp_rate     = pos.get('take_profit_rate') or 0
                direction   = pos.get('direction', 'BUY')
                amount      = pos.get('amount') or 0
                instrument_id = pos.get('instrument_id')

                # Fetch live rate (fall back to last snapshot rate)
                live_rate = None
                if instrument_id:
                    try:
                        rate_obj = get_rate(instrument_id)
                        if rate_obj:
                            live_rate = rate_obj.mid
                    except Exception:
                        pass
                if not live_rate:
                    live_rate = pos.get('current_rate') or pos.get('live_price') or open_rate

                # Compute approximate P&L
                pnl = None
                if open_rate and open_rate > 0 and live_rate:
                    units = amount / open_rate
                    pnl = units * (live_rate - open_rate) if direction == 'BUY' \
                          else units * (open_rate - live_rate)

                # Infer close reason
                reason = 'external'
                if live_rate and sl_rate > 0 and abs(live_rate - sl_rate) / live_rate < 0.005:
                    reason = 'SL'
                elif live_rate and tp_rate > 0 and abs(live_rate - tp_rate) / live_rate < 0.005:
                    reason = 'TP'
                elif pnl is not None and pnl > 0:
                    reason = 'TSL_or_manual'
                else:
                    reason = 'manual'

                conn.execute(
                    'INSERT INTO position_closes (position_id, symbol, pnl, reason) VALUES (?, ?, ?, ?)',
                    (pid, symbol, round(pnl, 2) if pnl is not None else None, reason)
                )
                pnl_str = f'${pnl:.2f}' if pnl is not None else 'N/A'
                print(f'Recorded external close: {symbol} (pos {pid}) P&L={pnl_str} reason={reason}')

            conn.commit()
            conn.close()
            print(f'Done — {len(new_closes)} new external close(s) recorded')
```

**Step 1: Run the script in dry-run mode first (no commits) — just verify it doesn't crash**

```bash
cd /Users/michalprusek/PycharmProjects/etoro && python3 -c "
import sqlite3, json, os
os.environ.setdefault('TRADING_MODE', 'real')
conn = sqlite3.connect('data/etoro.db')
conn.row_factory = sqlite3.Row
snap = conn.execute('SELECT positions_json FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1').fetchone()
if snap:
    positions = json.loads(snap['positions_json'])
    snapshot_ids = {p['position_id'] for p in positions if p.get('position_id')}
    from src.portfolio.manager import get_portfolio
    portfolio = get_portfolio()
    live_ids = {p.position_id for p in portfolio.positions}
    disappeared = snapshot_ids - live_ids
    print(f'Snapshot positions: {len(snapshot_ids)}')
    print(f'Live positions: {len(live_ids)}')
    print(f'Disappeared (potential external closes): {len(disappeared)}')
    if disappeared:
        print(f'Position IDs: {disappeared}')
else:
    print('No snapshot found')
conn.close()
"
```

Expected output (no errors): counts printed, no exceptions.

**Step 2: Verify `position_closes` table has required columns**

```bash
cd /Users/michalprusek/PycharmProjects/etoro && python3 -c "
import sqlite3
conn = sqlite3.connect('data/etoro.db')
cols = [r[1] for r in conn.execute('PRAGMA table_info(position_closes)').fetchall()]
print('position_closes columns:', cols)
assert 'position_id' in cols
assert 'symbol' in cols
assert 'pnl' in cols
assert 'reason' in cols
print('Schema OK')
conn.close()
"
```

Expected: `Schema OK`

---

### Task 2: Update trade-journal agent

**Files:**
- Modify: `.claude/agents/trade-journal.md` — prepend reconciliation step before Step 1

**Step 1: Read the current file to find the exact insertion point**

```bash
head -30 /Users/michalprusek/PycharmProjects/etoro/.claude/agents/trade-journal.md
```

The insertion goes after the opening description paragraph and before `## Your Process`.

**Step 2: Insert the reconciliation step**

Insert this block between the opening paragraph and `## Your Process`:

```markdown
## Step 0 — Reconcile external closes first

Before querying for any specific symbol, always run this reconciliation to catch
positions closed by SL/TP/TSL or manually since the last snapshot:

    import sqlite3, json, os
    os.environ.setdefault('TRADING_MODE', 'real')
    conn = sqlite3.connect('data/etoro.db')
    conn.row_factory = sqlite3.Row
    snap = conn.execute(
        'SELECT positions_json FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1'
    ).fetchone()
    if not snap:
        print('No snapshot — skipping reconciliation')
        conn.close()
    else:
        snapshot_by_id = {p['position_id']: p for p in json.loads(snap['positions_json']) if p.get('position_id')}
        from src.portfolio.manager import get_portfolio
        live_ids = {p.position_id for p in get_portfolio().positions}
        disappeared = set(snapshot_by_id.keys()) - live_ids
        if not disappeared:
            print('No new external closes')
            conn.close()
        else:
            placeholders = ','.join('?' * len(disappeared))
            already = {r[0] for r in conn.execute(
                f'SELECT position_id FROM position_closes WHERE position_id IN ({placeholders})',
                list(disappeared)).fetchall()}
            new_closes = disappeared - already
            if not new_closes:
                print(f'{len(disappeared)} close(s) already recorded')
                conn.close()
            else:
                from src.market.data import get_rate
                for pid in new_closes:
                    pos = snapshot_by_id[pid]
                    symbol, open_rate = pos['symbol'], pos.get('open_rate') or 0
                    sl_rate, tp_rate = pos.get('stop_loss_rate') or 0, pos.get('take_profit_rate') or 0
                    direction, amount = pos.get('direction', 'BUY'), pos.get('amount') or 0
                    live_rate = None
                    try:
                        r = get_rate(pos.get('instrument_id'))
                        live_rate = r.mid if r else None
                    except Exception:
                        pass
                    live_rate = live_rate or pos.get('current_rate') or open_rate
                    pnl = None
                    if open_rate and live_rate:
                        units = amount / open_rate
                        pnl = units * (live_rate - open_rate) if direction == 'BUY' else units * (open_rate - live_rate)
                    reason = 'SL' if (live_rate and sl_rate > 0 and abs(live_rate - sl_rate)/live_rate < 0.005) \
                        else 'TP' if (live_rate and tp_rate > 0 and abs(live_rate - tp_rate)/live_rate < 0.005) \
                        else ('TSL_or_manual' if (pnl and pnl > 0) else 'manual')
                    conn.execute(
                        'INSERT INTO position_closes (position_id, symbol, pnl, reason) VALUES (?, ?, ?, ?)',
                        (pid, symbol, round(pnl, 2) if pnl is not None else None, reason))
                    print(f'Recorded: {symbol} pos={pid} P&L={"${:.2f}".format(pnl) if pnl else "N/A"} reason={reason}')
                conn.commit()
                conn.close()
                print(f'{len(new_closes)} external close(s) recorded')
```

**Step 3: Verify the file looks correct**

```bash
python3 -c "
content = open('.claude/agents/trade-journal.md').read()
assert 'Step 0' in content, 'Missing Step 0'
assert 'reconcil' in content.lower(), 'Missing reconciliation'
assert 'snapshot_by_id' in content, 'Missing snapshot comparison'
assert 'INSERT INTO position_closes' in content, 'Missing INSERT'
print('trade-journal.md OK')
"
```

---

### Task 3: Update morning-check Phase 0

**Files:**
- Modify: `.claude/commands/morning-check.md` — add reconciliation block after the portfolio JSON is loaded but before Portfolio Health Quick Checks

**Step 1: Find the exact insertion point**

```bash
grep -n "Portfolio Health Quick Checks\|Also load watchlist" /Users/michalprusek/PycharmProjects/etoro/.claude/commands/morning-check.md | head -5
```

The reconciliation block goes **before** `### Portfolio Health Quick Checks` (around line 37 in the current file).

**Step 2: Insert this block before `### Portfolio Health Quick Checks`**

```markdown
### Reconcile External Closes (SL/TP/TSL/Manual)

Before health checks, detect any positions closed since the last snapshot and record them:

```python
import sqlite3, json, os
os.environ['TRADING_MODE'] = '{mode}'
conn = sqlite3.connect('data/etoro.db')
conn.row_factory = sqlite3.Row
snap = conn.execute(
    'SELECT positions_json FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1'
).fetchone()
if not snap:
    print('No snapshot — skipping external close detection')
    conn.close()
else:
    snapshot_by_id = {p['position_id']: p for p in json.loads(snap['positions_json']) if p.get('position_id')}
    from src.portfolio.manager import get_portfolio as _gp
    _live_ids = {p.position_id for p in _gp().positions}
    _disappeared = set(snapshot_by_id.keys()) - _live_ids
    if not _disappeared:
        print('External close check: no new closes')
        conn.close()
    else:
        _ph = ','.join('?' * len(_disappeared))
        _already = {r[0] for r in conn.execute(
            f'SELECT position_id FROM position_closes WHERE position_id IN ({_ph})',
            list(_disappeared)).fetchall()}
        _new = _disappeared - _already
        if not _new:
            print(f'External close check: {len(_disappeared)} close(s) already recorded')
            conn.close()
        else:
            from src.market.data import get_rate as _gr
            for _pid in _new:
                _pos = snapshot_by_id[_pid]
                _sym, _or = _pos['symbol'], _pos.get('open_rate') or 0
                _sl, _tp = _pos.get('stop_loss_rate') or 0, _pos.get('take_profit_rate') or 0
                _dir, _amt = _pos.get('direction', 'BUY'), _pos.get('amount') or 0
                _lr = None
                try:
                    _ro = _gr(_pos.get('instrument_id'))
                    _lr = _ro.mid if _ro else None
                except Exception:
                    pass
                _lr = _lr or _pos.get('current_rate') or _or
                _pnl = None
                if _or and _lr:
                    _u = _amt / _or
                    _pnl = _u * (_lr - _or) if _dir == 'BUY' else _u * (_or - _lr)
                _rsn = 'SL' if (_lr and _sl > 0 and abs(_lr - _sl)/_lr < 0.005) \
                    else 'TP' if (_lr and _tp > 0 and abs(_lr - _tp)/_lr < 0.005) \
                    else ('TSL_or_manual' if (_pnl and _pnl > 0) else 'manual')
                conn.execute(
                    'INSERT INTO position_closes (position_id, symbol, pnl, reason) VALUES (?, ?, ?, ?)',
                    (_pid, _sym, round(_pnl, 2) if _pnl is not None else None, _rsn))
                _pnl_s = f'${_pnl:.2f}' if _pnl is not None else 'N/A'
                print(f'  External close: {_sym} (pos {_pid}) P&L={_pnl_s} reason={_rsn}')
            conn.commit()
            conn.close()
            print(f'External close check: {len(_new)} new close(s) recorded')
\```

Announce any detected closes prominently in the dashboard under **External Closes Detected** if count > 0.
```

Note: variable names prefixed with `_` to avoid colliding with existing morning-check variables.

**Step 3: Verify**

```bash
python3 -c "
content = open('.claude/commands/morning-check.md').read()
assert 'Reconcile External Closes' in content, 'Missing section header'
assert 'snapshot_by_id' in content, 'Missing snapshot comparison'
assert 'INSERT INTO position_closes' in content, 'Missing INSERT'
assert 'External close check' in content, 'Missing status print'
print('morning-check.md OK')
"
```

---

### Task 4: Verify end-to-end dry run

**Step 1: Run the reconciliation script standalone to confirm no errors**

```bash
cd /Users/michalprusek/PycharmProjects/etoro && python3 -c "
import sqlite3, json, os
os.environ.setdefault('TRADING_MODE', 'real')
conn = sqlite3.connect('data/etoro.db')
conn.row_factory = sqlite3.Row
snap = conn.execute('SELECT positions_json FROM portfolio_snapshots ORDER BY timestamp DESC LIMIT 1').fetchone()
if not snap:
    print('No snapshot found — cannot test')
    conn.close()
else:
    snapshot_by_id = {p['position_id']: p for p in json.loads(snap['positions_json']) if p.get('position_id')}
    from src.portfolio.manager import get_portfolio
    live_ids = {p.position_id for p in get_portfolio().positions}
    disappeared = set(snapshot_by_id.keys()) - live_ids
    if not disappeared:
        placeholders = ','.join('?' * len(snapshot_by_id))
        already = {r[0] for r in conn.execute(
            f'SELECT position_id FROM position_closes WHERE position_id IN ({placeholders})',
            list(snapshot_by_id.keys())).fetchall()}
        print(f'All {len(snapshot_by_id)} snapshot positions still live (or already recorded)')
        print(f'Already in position_closes: {len(already)}')
    else:
        print(f'Would record {len(disappeared)} external close(s): {disappeared}')
    conn.close()
    print('Dry run OK — no writes performed')
"
```

Expected: No exceptions, summary printed.

**Step 2: Run full test suite to confirm nothing is broken**

```bash
cd /Users/michalprusek/PycharmProjects/etoro && python3 -m pytest tests/ -q
```

Expected: 143 passed.

---

### Task 5: Commit

```bash
cd /Users/michalprusek/PycharmProjects/etoro
git add .claude/agents/trade-journal.md .claude/commands/morning-check.md
git status
git commit -m "feat: detect and record external closes (SL/TP/TSL/manual) in trade-journal and morning-check

Agent-side reconciliation: compare live portfolio vs last portfolio_snapshots entry.
Disappeared positions get recorded in position_closes with inferred reason
(SL/TP within 0.5% of stored rate, TSL_or_manual if profitable, manual otherwise).
P&L computed from live rate at detection time via get_rate().

Runs automatically in morning-check Phase 0 and on-demand via trade-journal agent.

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"
```
