Perform a lightweight morning portfolio check — monitor existing holdings, check overnight news, flag alerts, and optionally execute position changes with user approval. NO universe screening — this is a daily health check focused on current holdings + watchlist, not a full analysis.

**Usage**: `/morning-check` or `/morning-check --mode demo`

---

## Mode Setup (parse from arguments)

Check `$ARGUMENTS` for `--mode`:
- `--mode demo` → set `TRADING_MODE=demo` — safe sandbox, no real money
- `--mode real` or no argument → set `TRADING_MODE=real` (default) — **⚠️ REAL ACCOUNT — trades use real money**

Announce the mode at the start: `🔴 Mode: REAL — trades will use your real eToro account` or `🔵 Mode: DEMO`.

**Apply the mode to every command in this workflow:**
- All `python3 cli.py ...` calls → prepend `TRADING_MODE={mode}` (e.g. `TRADING_MODE=real python3 cli.py portfolio --format json`)
- All inline Python snippets → add `import os; os.environ['TRADING_MODE'] = '{mode}'` as the **very first line**, before any other imports

---

## Phase 0: Get Portfolio State

Run this command to get the current portfolio:
```bash
python3 cli.py portfolio --format json
```

Parse the JSON output. Extract:
- Total value, invested amount, cash available, overall P&L ($ and %)
- All open positions: symbol, direction, amount invested, current P&L ($ and %), leverage
- Calculate exposure % (invested / total value)

Save the list of portfolio symbols for the agents below.

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
    print('External close check: no snapshot found — skipping')
    conn.close()
else:
    snapshot_by_id = {p['position_id']: p for p in json.loads(snap['positions_json']) if p.get('position_id')}
    from src.portfolio.manager import get_portfolio as _gp
    _live_ids = {p.position_id for p in _gp().positions}
    _disappeared = set(snapshot_by_id.keys()) - _live_ids
    if not _disappeared:
        print('External close check: no new closes detected')
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
```

Announce any detected closes prominently before the dashboard under **External Closes Detected** if count > 0.

### Fundamental Flash Data (per-holding loop)

Quick fundamental scan for analyst price targets and 52-week positioning:

```python
import os, json, time
os.environ['TRADING_MODE'] = '{mode}'
from src.market.fundamentals import get_instrument_fundamentals

import httpx
_yf = httpx.Client(timeout=8, headers={"User-Agent": "Mozilla/5.0"})

def _yf_52w(ticker):
    """Fetch 52-week high/low from Yahoo Finance as fallback."""
    try:
        r = _yf.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                    params={"interval": "1d", "range": "1y"})
        if r.status_code == 200:
            meta = r.json().get("chart", {}).get("result", [{}])[0].get("meta", {})
            hi = meta.get("fiftyTwoWeekHigh")
            lo = meta.get("fiftyTwoWeekLow")
            if hi and lo:
                return hi, lo
    except Exception:
        pass
    return None, None

fund_flash = {}   # symbol -> {'pt_upside': float, 'consensus': str, 'days_till_earnings': int, 'w52_pct': float}
for sym in list(dict.fromkeys(p['symbol'] for p in positions)):  # deduplicated, order preserved
    try:
        f = get_instrument_fundamentals(sym)
        ar = f.get('analyst_ratings', {})
        ea = f.get('earnings', {})
        pp = f.get('price_performance', {})
        price = next((pos.get('current_rate') or pos.get('open_rate', 0) for pos in positions if pos['symbol'] == sym), 0)
        hi, lo = pp.get('high_52w'), pp.get('low_52w')
        # Yahoo Finance fallback when fundamentals API returns null
        if (not hi or not lo) and sym != 'BTC':
            hi, lo = _yf_52w(sym)
        w52_pct = round((price - lo) / (hi - lo) * 100, 0) if hi and lo and hi != lo else None
        fund_flash[sym] = {
            'pt_upside': ar.get('target_upside'),     # e.g. 14.5 = analyst PT is 14.5% above current price
            'consensus': ar.get('consensus', ''),      # "BUY" / "HOLD" / "SELL"
            'days_till_earnings': ea.get('days_till_earnings'),
            'w52_pct': w52_pct,                        # 100% = at 52w high, 0% = at 52w low
        }
        time.sleep(0.2)
    except Exception:
        fund_flash[sym] = {}

_yf.close()
print(json.dumps(fund_flash, indent=2, default=str))
```

Save `fund_flash` dict — used in Phase 2 Position Status table for PT Upside and 52w% columns.

**Immediately flag:**
- `pt_upside < 0`: ⚠️ analyst PT BELOW current price — analysts expect decline
- `w52_pct > 95`: ⚠️ near 52-WEEK HIGH — momentum extended
- `consensus == 'SELL'`: ⚠️ analyst consensus is SELL

### Portfolio Health Quick Checks

Run immediately after parsing the portfolio JSON. This surfaces structural problems before agents are launched.

```python
import os
os.environ['TRADING_MODE'] = '{mode}'

SEMICONDUCTOR_SYMBOLS = {
    'NVDA','AMD','ASML','AMAT','MU','TSM','QCOM','MRVL','ARM','SMCI',
    'INTC','KLAC','LRCX','ON','TXN'
}

no_sl, loose_sl, sl_above_price, legacy_tp = [], [], [], []
chip_invested = 0
chip_symbols = set()

for p in positions:   # positions = list of dicts from portfolio JSON
    sym    = p['symbol']
    price  = p.get('current_rate') or p.get('open_rate', 0)
    sl     = p.get('stop_loss_rate', 0)
    tp     = p.get('take_profit_rate', 0)
    amount = p.get('amount', 0)

    # SL checks
    if sl == 0:
        no_sl.append(sym)
    elif price > 0:
        dist_pct = abs(price - sl) / price * 100
        if dist_pct > 15:
            loose_sl.append(f"{sym} ({dist_pct:.0f}%)")
        if p.get('direction') == 'BUY' and sl > price:
            sl_above_price.append(sym)   # existing SL is above current price (likely stale)

    # Legacy TP (stale artifact from old entry price)
    if tp > 0 and price > 0 and (tp / price - 1) > 0.5:
        legacy_tp.append(f"{sym} (TP {((tp/price-1)*100):.0f}% above price)")

    # Sector concentration
    if sym in SEMICONDUCTOR_SYMBOLS:
        chip_invested += amount
        chip_symbols.add(sym)

# Print warnings
if no_sl:
    print(f"❌ NO SL SET: {', '.join(sorted(set(no_sl)))}")
if loose_sl:
    print(f"⚠️ LOOSE SL (>15% from price): {', '.join(loose_sl)}")
if sl_above_price:
    print(f"⚠️ SL ABOVE PRICE (bearish SuperTrend — use Fixed SL, not TSL): {', '.join(sorted(set(sl_above_price)))}")
if legacy_tp:
    print(f"⚠️ LEGACY TP (>50% above current price — likely stale): {', '.join(legacy_tp)}")

chip_pct = chip_invested / total_invested * 100 if total_invested > 0 else 0
if chip_pct > 30:
    print(f"🔴 CHIP SECTOR CONCENTRATION: {chip_pct:.0f}% in semiconductors")
    print(f"   Symbols: {', '.join(sorted(chip_symbols))}")
    print(f"   Risk: single earnings miss or tariff shock can gap ALL chip positions simultaneously.")

# Cash threshold — determines whether watchlist BUYs are executable
WATCHLIST_INFORMATIONAL_ONLY = cash_available < 300
if WATCHLIST_INFORMATIONAL_ONLY:
    print(f"⚠️ CASH CRITICAL (${cash_available:.0f}) — watchlist screener runs informational only. No BUY execution without closing a position first.")
```

Announce any findings prominently before proceeding. Chip concentration > 30% should be highlighted in the morning dashboard header.

### Also load watchlist symbols:
```python
from src.portfolio.manager import get_watchlists
watchlists = get_watchlists()
watchlist_symbols = []
for wl in watchlists:
    for item in wl.get("items", []):
        sym = item.get("symbol", "")
        if sym:
            watchlist_symbols.append(sym)
# Deduplicate and remove symbols already in portfolio
watchlist_symbols = [s for s in set(watchlist_symbols) if s not in portfolio_symbols]
print(f"Watchlist symbols (excluding portfolio): {watchlist_symbols}")
```

Additionally, combine with the **hardcoded morning watchlist** below:

#### Morning Watchlist (~45 tech + growth + fintech favorites)

```
# Mega-Cap Tech
AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA, AVGO, ORCL, CRM, AMD, ADBE, NFLX

# Large-Cap Tech / Growth
NOW, UBER, SHOP, XYZ, PLTR, PANW, CRWD, DDOG, NET, ANET, MRVL, MU

# Semiconductors
ASML, TSM, QCOM

# AI / Cloud
SMCI, ARM, DELL

# Fintech
PYPL, COIN, SOFI

# Crypto (top 5)
BTC, ETH, SOL, ADA, XRP
```

Merge eToro watchlist symbols + hardcoded morning watchlist, deduplicate, and remove symbols already in portfolio. The final watchlist is what Agent 3 will screen.

Print: `Watchlist for screening: N symbols (M from eToro + K hardcoded, P already in portfolio excluded)`

---

## Phase 0.5: Market Regime Check (Top-Down — Run Before Agents)

Before launching any agents, get the market "weather" to inform all subsequent analysis:

```python
from src.market.data import analyze_market_regime
import json

regime = analyze_market_regime()
print(json.dumps(regime, indent=2, default=str))
```

**Macro Context (10Y yield + DXY via Yahoo Finance):**

```python
import httpx, json
_mc = httpx.Client(timeout=8, headers={"User-Agent": "Mozilla/5.0"})
def _yf_last2(ticker):
    try:
        r = _mc.get(f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}",
                    params={"interval": "1d", "range": "5d"})
        if r.status_code == 200:
            closes = r.json().get("chart", {}).get("result", [{}])[0].get(
                "indicators", {}).get("quote", [{}])[0].get("close", [])
            valid = [c for c in closes if c is not None]
            if len(valid) >= 2:
                return {"current": round(valid[-1], 3), "change": round(valid[-1] - valid[-2], 3),
                        "direction": "RISING" if valid[-1] > valid[-2] else "FALLING"}
    except Exception:
        pass
    return None

tnx = _yf_last2("%5ETNX")   # 10-Year Treasury yield
dxy = _yf_last2("DX-Y.NYB") # US Dollar Index
print(json.dumps({"10y_yield": tnx, "dxy": dxy}, indent=2))
```

**Sector Rotation Scan (20-day Relative Strength vs SPX500):**

Uses 20-day returns instead of 1-day gap% — always meaningful regardless of time-of-day (pre-market, intraday, or after-hours).

```python
import os, json, time
os.environ['TRADING_MODE'] = '{mode}'
from src.market.data import get_candles, resolve_symbol

SECTOR_MAP = {
    'XLK':'Technology','XLF':'Financials','XLV':'Healthcare','XLE':'Energy',
    'XLI':'Industrials','XLC':'Communication','XLY':'ConsDiscr',
    'XLP':'ConsStaples','XLB':'Materials','XLU':'Utilities','XLRE':'RealEstate'
}

def _get_20d_return(symbol):
    """Get 20-day return for a symbol. Returns float % or None."""
    iid = resolve_symbol(symbol)
    iid = iid['instrument_id'] if isinstance(iid, dict) else iid
    if not iid:
        return None
    candles = get_candles(iid, 'OneDay', 25)
    if candles is not None and len(candles) >= 21:
        return round((candles['close'].iloc[-1] / candles['close'].iloc[-21] - 1) * 100, 2)
    return None

# SPX500 20-day return (used as benchmark for both sectors and portfolio)
spx_20d = _get_20d_return('SPX500') or 0.0
print(f"SPX500 20d return: {spx_20d:+.2f}%")

sector_rs = {}
for etf, name in SECTOR_MAP.items():
    try:
        ret = _get_20d_return(etf)
        if ret is not None:
            vs_spx = round(ret - spx_20d, 2)
            sector_rs[etf] = {'name': name, 'ret_20d': ret, 'vs_spx500': vs_spx}
        time.sleep(0.15)
    except Exception:
        pass

ranked = sorted(sector_rs.items(), key=lambda x: x[1].get('vs_spx500', -99), reverse=True)
for etf, d in ranked:
    sig = '🟢 IN ROTATION' if d['vs_spx500'] > 1.0 else ('🔴 LAGGING' if d['vs_spx500'] < -1.0 else '⬜ NEUTRAL')
    print(f"{sig} {d['name']} ({etf}): 20d {d['ret_20d']:+.1f}% | vs SPX500 {d['vs_spx500']:+.1f}%")
```

Note: Sector RS thresholds use ±1.0% for 20-day window (vs ±0.3% for 1-day gap).

Parse and save:
- **SPY**: trend, RSI, above/below 20 SMA, above/below 50 SMA, MA alignment
- **QQQ**: trend, RSI, above/below 20 SMA, above/below 50 SMA
- **VIX**: value, regime (VERY_LOW/LOW/NORMAL/ELEVATED/HIGH/EXTREME), sizing_adjustment
- **Overall Bias**: RISK_ON / CAUTIOUS / RISK_OFF
- **10Y Yield**: current value and direction (RISING/FALLING)
- **DXY**: current value and direction (RISING/FALLING)
- **Sector RS**: ranked list of all 11 sector ETFs by 20-day return vs SPX500
- **spx_20d**: save the 20-day SPX500 return for Phase 2 portfolio benchmark

**Pass VIX regime + sizing adjustment to ALL agents** in their prompts.

**VIX-Based Position Sizing Rule** (applies to ALL BUY suggestions):
- VIX < 20 (NORMAL): Standard sizing (sizing_adjustment = 1.0)
- VIX 20-25 (ELEVATED): Reduce all new positions by 25% (sizing_adjustment = 0.75)
- VIX 25-30 (HIGH): Reduce by 50% (sizing_adjustment = 0.5). Only strongest setups.
- VIX > 30 (EXTREME): Reduce by 75% (sizing_adjustment = 0.25). Capital preservation mode. Prefer no new longs.

**If bias is RISK_OFF**: Announce prominently: "⚠️ Market regime is RISK_OFF — unfavorable for new long positions. Morning check will focus on protecting existing positions."

---

## Phase 1: Parallel Research (3 Subagents)

Spawn ALL THREE subagents simultaneously in a SINGLE message with multiple Task tool calls.

### Agent 1: Technical Quick Check
- `subagent_type: "technical-quick-check"`
- `description: "Technical check holdings"`
- Prompt: `Trading mode: {mode} — prepend TRADING_MODE={mode} to all CLI commands. For inline Python: import os; os.environ['TRADING_MODE'] = '{mode}' as the first line. Portfolio positions to check: {paste ALL portfolio symbols with their directions, invested amounts, and current P&L}`

### Agent 2: News & Events Check
- `subagent_type: "news-events-check"`
- `description: "News and events check"`
- Prompt: `Trading mode: {mode} — prepend TRADING_MODE={mode} to all CLI commands. For inline Python: import os; os.environ['TRADING_MODE'] = '{mode}' as the first line. Portfolio positions to check: {paste ALL portfolio symbols}. Today's date: {current date}`

### Agent 3: Watchlist Screener
- `subagent_type: "watchlist-screener"`
- `description: "Screen watchlist symbols"`
- Prompt: `Trading mode: {mode} — prepend TRADING_MODE={mode} to all CLI commands. For inline Python: import os; os.environ['TRADING_MODE'] = '{mode}' as the first line. Watchlist symbols to screen: {paste ALL merged watchlist symbols from Phase 0, excluding portfolio positions}. Portfolio cash available: ${cash_available:.0f}. If cash < $300, mark all OPPORTUNITY results as INFORMATIONAL ONLY — no BUY execution without closing an existing position first.`

---

## Phase 2: Morning Dashboard

After ALL THREE subagents return, present a consolidated morning dashboard.

### Format:

```markdown
# Morning Check — {date}

## Market Regime (Top-Down)
- **Bias**: [RISK_ON / CAUTIOUS / RISK_OFF] — [1-line guidance]
- **SPY**: [trend] | RSI [value] | [above/below] 20 SMA | [above/below] 50 SMA | MA: [alignment]
- **QQQ**: [trend] | RSI [value] | [above/below] 20 SMA | [above/below] 50 SMA
- **VIX**: [value] | [regime] — [sizing guidance, e.g., "Standard sizing" or "Reduce by 25%"]
- **10Y Yield**: [value]% [[RISING/FALLING]] — [headwind for growth if >4.5% and rising | neutral]
- **DXY**: [value] [[RISING/FALLING]] — [dollar strength if >105 rising — headwind for crypto/commodities | neutral]
- **Today's Calendar**: [key events with impact tags: 🔴 RED FLAG / 🟡 YELLOW, or "No major events"]
- **Market Mood**: [1-line summary from News Agent]

## Sector Rotation (20-day RS vs SPX500)
| # | Sector | ETF | 20d Return | vs SPX500 | Status |
|---|--------|-----|-----------|-----------|--------|
(from Phase 0.5 sector scan; sorted best→worst; 🟢 IN ROTATION if vs_spx500 > +1.0% / ⬜ NEUTRAL / 🔴 LAGGING if < −1.0%)

## Portfolio Overview
| Metric | Value |
|--------|-------|
| Total Value | $X |
| Cash | $X (X%) |
| Invested | $X |
| Exposure | X% |
| Daily P&L | $X (X%) |
| Positions | N |
| VIX Sizing Adj | X.Xx |
| vs SPX500 (20d) | Portfolio [pf_return]% \| SPX500 [spx_20d]% \| Alpha [alpha]% |

Before presenting this table, compute portfolio benchmark (mode-filtered, rolling 20-day):
```python
import sqlite3, os
os.environ['TRADING_MODE'] = '{mode}'
conn = sqlite3.connect('data/etoro.db')
# Filter by current mode — prevents demo snapshots from polluting real benchmark
snaps = conn.execute(
    "SELECT timestamp, total_value FROM portfolio_snapshots WHERE mode = ? ORDER BY timestamp ASC",
    ('{mode}',)
).fetchall()
conn.close()

if len(snaps) >= 2:
    # Use rolling 20-day window: find the snapshot closest to 20 days ago
    from datetime import datetime, timedelta
    now = datetime.utcnow()
    cutoff = now - timedelta(days=20)
    # Find oldest snapshot within the 20-day window (or the absolute oldest if all are recent)
    baseline = snaps[0]  # fallback: oldest snapshot
    for ts, val in snaps:
        snap_dt = datetime.fromisoformat(ts.replace('Z', '+00:00')) if 'Z' in ts else datetime.fromisoformat(ts)
        snap_dt = snap_dt.replace(tzinfo=None)
        if snap_dt <= cutoff:
            baseline = (ts, val)
    pf_return = round((snaps[-1][1] / baseline[1] - 1) * 100, 1)
    alpha = round(pf_return - spx_20d, 1)
    period = baseline[0][:10]
    print(f"Portfolio return: {pf_return:+.1f}% (since {period}) | SPX500 20d: {spx_20d:+.1f}% | Alpha: {alpha:+.1f}%")
else:
    print("Portfolio benchmark: not enough snapshots yet — run 'python3 cli.py portfolio snapshot' first")
```

## Historical Performance (Last 30 Days)

Before presenting this section, run this DB query:

```python
import sqlite3, os
os.environ.setdefault('TRADING_MODE', 'real')
conn = sqlite3.connect('data/etoro.db')
conn.row_factory = sqlite3.Row
closes = conn.execute(
    "SELECT pnl, reason, symbol, timestamp FROM position_closes ORDER BY timestamp DESC"
).fetchall()
daily = conn.execute(
    "SELECT date, realized_pnl FROM daily_pnl ORDER BY date DESC LIMIT 30"
).fetchall()
conn.close()
profits = [c['pnl'] for c in closes if c['pnl'] is not None]
wins = [p for p in profits if p > 0]
losses = [p for p in profits if p <= 0]
win_rate = len(wins) / len(profits) * 100 if profits else 0
total_realized = sum(d['realized_pnl'] for d in daily if d['realized_pnl'])
print(f"Closed trades total: {len(profits)} | Win rate: {win_rate:.0f}%")
print(f"Total realized P&L (30d): ${total_realized:.2f}")
for c in closes[:3]:
    sign = '+' if c['pnl'] >= 0 else ''
    print(f"  {c['symbol']}: {sign}${c['pnl']:.2f} [{c['timestamp'][:10]}] ({c['reason']})")
```

Format output:

| Metric | Value |
|--------|-------|
| Closed Trades | N |
| Win Rate | X% |
| Realized P&L (30d) | $X |
| Last Close | SYMBOL ±$X |

## Position Status

**Consolidate same-symbol positions into one row** (e.g., NVDA×2 = combined invested + blended P&L%, single technical analysis). Use `×N` notation.

| # | Symbol | P&L | P&L% | Trend | MA Align | RSI | RVOL | Gap% | PT Upside | 52w% | Chandelier | Chan.✓? | SL Type | Earnings | Status |
|---|--------|-----|------|-------|----------|-----|------|------|-----------|------|-----------|--------|---------|----------|--------|

`Chan.✓?` = ✅ chandelier < price (bullish ST, TSL valid) | ❌ chandelier > price (bearish ST, Fixed SL only)
`SL Type` = TSL if ✅ | Fixed if ❌ | flag `⚠️ Legacy TP` if TP is set >50% above current price
`Gap%` = pre-market/intraday gap from `result["gap_pct"]`. Flag ≥ ±1%.
`PT Upside` = analyst consensus price target upside from `fund_flash[sym]["pt_upside"]`. ⚠️ if negative (analysts expect decline).
`52w%` = position in 52-week range from `fund_flash[sym]["w52_pct"]`. ⚠️ if > 95% (extended). 🟢 if < 15% (potential value zone).
(sort: ALERTs first, then WATCHes, then HOLDs)

## Alerts & Watch Items
🔴 **ALERT** (action may be needed):
- SYMBOL: [reason — e.g., "RSI 78 overbought + price at resistance $XXX + RVOL 2.3x selling pressure"]
- SYMBOL: [reason — e.g., "Earnings in 3 days 🔴 BLOCK + negative analyst revision"]

🟡 **WATCH** (monitor today):
- SYMBOL: [reason — e.g., "RSI 72 approaching overbought, MA alignment flipping to MIXED"]
- SYMBOL: [reason — e.g., "Price 1.5% from support at $XXX, RVOL 0.3x low conviction"]

(If no alerts/watches: "All positions stable. No action items today.")

## Watchlist Opportunities
| # | Symbol | CSS | Trend | MA Align | RSI | RVOL | R:R | Price | Signal | Note |
|---|--------|-----|-------|----------|-----|------|-----|-------|--------|------|
(Only OPPORTUNITY symbols with R:R >= 1:2 from watchlist screener. If none: "No actionable setups in watchlist today.")

## Upcoming Catalysts (this week)
- [Date]: [Event] [impact tag] — affects [SYMBOL(s)]
- Earnings: [list portfolio positions with earnings this week]
```

### Decision Guidance:
- If there are **ALERT** positions: propose specific trade actions in Phase 3
- If all positions are **HOLD** and no watchlist opportunities: confirm "Portfolio stable, next full analysis recommended on [day based on weekly schedule]"
- If market conditions are unusual (VIX spike, major gap): suggest bringing forward the next `/analyze-portfolio` run

---

## Phase 3: Trade Suggestions + Approval Gate

Based on the dashboard results, evaluate whether any position changes are warranted.

### When to suggest trades:

**SELL suggestions** (for existing positions):
- ALERT status with bearish confluence (trend reversal + negative news + RSI overbought)
- Position breaking below key support with volume
- Materially negative news (earnings miss, downgrade, regulatory issue)
- Trailing SL should handle most exits automatically — only suggest manual SELL for fundamental deterioration

**BUY suggestions** (from watchlist only):
- Watchlist symbol with OPPORTUNITY signal (CSS >= 65, bullish trend, R:R >= 1:2)
- Only if portfolio has sufficient cash and exposure < 90%
- Must have clear technical entry with definable ATR stop
- **BLOCK if earnings < 5 days** — never open new position near earnings
- **R:R must be >= 1:2** — reject any setup with insufficient reward potential
- **RVOL > 1.0 preferred** — volume must confirm the move
- **Apply VIX sizing adjustment** — multiply position size by regime.sizing_adjustment

**No trades if:**
- All positions are HOLD/WATCH with no actionable signals
- Market bias is RISK_OFF (VIX > 25, broad market bearish)
- Market conditions are too uncertain (VIX spike, pre-FOMC, RED FLAG macro day)
- Daily loss approaching circuit breaker

### Partial Profit-Taking Signals (eToro has no partial close — flag for user awareness only)

- If `fund_flash[sym]["pt_upside"] < 5` AND position P&L > 0: flag "⚠️ NEAR ANALYST PT — price approaching analyst target, thesis complete"
- If `fund_flash[sym]["w52_pct"] > 95` AND RSI > 70: flag "⚠️ EXTENDED at 52w high with overbought RSI — momentum likely pausing"
- Suggest full close only when fundamentally justified — not purely technical extension

**Analyst PT as secondary TP for BUY suggestions:**
When presenting watchlist BUY recommendations, always add:
- TP2 = analyst consensus PT (from fund_flash or watchlist screener agent output)
- Add note: "Analyst consensus: [BUY/HOLD/SELL] | PT: +X% upside"

**Also include the Sector Rotation mini-table in Phase 2 Market Regime section:**
```
## Sector Rotation (20-day RS vs SPX500)
| # | Sector | ETF | 20d Return | vs SPX500 | Status |
|---|--------|-----|-----------|-----------|--------|
(sorted best→worst; 🟢 IN ROTATION if vs_spx500 > +1.0%, 🔴 LAGGING if < −1.0%, ⬜ NEUTRAL otherwise)
```
**Only recommend BUY candidates from IN ROTATION sectors** (unless setup is extremely compelling for a NEUTRAL sector).

### Always include SL Adjustment Recommendations

Even when no API trades are needed, present this section. eToro has no edit-position API endpoint — these are manual actions in the eToro app.

```markdown
## SL Adjustment Recommendations (manual in eToro UI — price levels only)

| # | Symbol | Current SL | Recommended SL | SL Type | Reason |
|---|--------|-----------|----------------|---------|--------|
(SL Type = TSL if Chan.✓ = ✅, Fixed SL if ❌)
(Report PRICE LEVEL only — not P&L amounts. User converts if needed.)
(Include positions where: SL is >3% looser than Chandelier stop AND position is profitable,
 or SL is >10% from price in a bearish trend, or SL is missing entirely)
```

If all SLs are correctly calibrated: "All SLs correctly set — no adjustments needed."

### If API trades are suggested, present:

```markdown
## Proposed Actions

### SELL
| # | Symbol | Position ID | Amount | Current P&L | Reason |
|---|--------|-------------|--------|-------------|--------|

### BUY (from watchlist)
| # | Symbol | Amount | Conviction | Entry Zone | Hard SL | TP1 | R:R | Trail | Setup Score | Reason |
|---|--------|--------|------------|------------|---------|-----|-----|-------|-------------|--------|
(Amount already adjusted for VIX sizing. Entry zone = price range for optimal entry. R:R must be >= 1:2.)

### No Action
(All other positions — HOLD)
```

### HARD GATE — WAIT FOR USER APPROVAL

**STOP HERE. DO NOT PROCEED TO PHASE 4 UNTIL THE USER EXPLICITLY APPROVES.**

> **Review the proposed actions above.** You can:
> - **Approve all**: reply `approve` or `ano`
> - **Approve with exceptions**: reply `approve except SYMBOL1, SYMBOL2`
> - **Modify**: reply `modify SYMBOL amount=XXX`
> - **Skip trades**: reply `skip` — no trades, just log the morning check to changelog
> - **Cancel**: reply `cancel` or `zrusit` — no trades, no changelog
>
> I will NOT execute any trades until you explicitly approve.

**If no trades are suggested**: Skip Phase 4 entirely and go directly to Phase 5 (Changelog). Tell the user: "No trade actions needed today. Logging morning check to changelog."

---

## Phase 4: Execute Approved Trades

**Only execute trades that the user approved.** If the user said "skip" or "cancel", skip this phase.

### Pre-Execution Safety Check

```python
from src.storage.repositories import TradeLogRepo
from src.portfolio.manager import get_portfolio

portfolio = get_portfolio()
trade_repo = TradeLogRepo()
daily_stats = trade_repo.get_today_stats()
daily_loss = daily_stats.get("realized_pnl", 0)
total_value = portfolio.total_value

if total_value > 0 and daily_loss < 0:
    daily_loss_pct = abs(daily_loss) / total_value
    if daily_loss_pct >= 0.05:
        print("CIRCUIT BREAKER: Daily loss exceeds 5%. ALL TRADES HALTED.")
        # STOP — go to Phase 5
```

### For SELL orders:
```python
from src.trading.engine import close_position
import time

result = close_position(
    position_id=POSITION_ID,
    instrument_id=INSTRUMENT_ID,
    reason="morning-check: [brief reason]"
)
print(f"SELL {SYMBOL}: {result.message}")

if result.success:
    time.sleep(8)
    portfolio = get_portfolio()
    still_exists = any(
        getattr(p, 'position_id', None) == POSITION_ID
        for p in portfolio.positions
    )
    if not still_exists:
        print(f"  VERIFIED: {SYMBOL} position closed successfully")
    else:
        print(f"  WARNING: {SYMBOL} position still appears in portfolio!")
```

### For BUY orders:
```python
from config import AggressiveRiskLimits
from src.trading.engine import open_position
from src.trading.atr_stops import calculate_position_size
from src.portfolio.manager import get_portfolio
from src.market.data import resolve_symbol
import time

portfolio = get_portfolio()

sizing = calculate_position_size(
    portfolio_value=portfolio.total_value,
    cash_available=portfolio.cash_available,
    atr=ATR_VALUE,
    price=CURRENT_PRICE,
    conviction="strong|moderate|weak",
    current_exposure_pct=portfolio.total_invested / portfolio.total_value if portfolio.total_value > 0 else 0,
    sl_distance_pct=SL_DISTANCE_PCT,  # from Chandelier stop: (price - sl_rate) / price
)

# Apply VIX sizing adjustment (computed in Phase 0.5)
vix_adj = VIX_SIZING_ADJUSTMENT  # e.g. 1.0, 0.75, 0.5, or 0.25
final_amount = round(sizing.get("amount", 0) * vix_adj, 2)
print(f"  Sizing: ${sizing.get('amount',0):.0f} × VIX adj {vix_adj} = ${final_amount:.0f}")

if final_amount >= 50:
    result = open_position(
        symbol="SYMBOL",
        amount=final_amount,
        direction="BUY",
        atr_value=ATR_VALUE,
        trailing_sl=True,
        limits_override=AggressiveRiskLimits(),
        reason="morning-check: [brief reason]"
    )
    print(f"BUY {SYMBOL} ${sizing['amount']}: {result.message}")

    if result.success:
        time.sleep(8)
        portfolio = get_portfolio()
        iid_data = resolve_symbol("SYMBOL")
        iid = iid_data['instrument_id'] if isinstance(iid_data, dict) else iid_data
        if result.position_id:
            found = any(getattr(p, 'position_id', None) == result.position_id for p in portfolio.positions)
        else:
            found = any(getattr(p, 'instrument_id', None) == iid for p in portfolio.positions)
        if found:
            print(f"  VERIFIED: {SYMBOL} confirmed in portfolio")
        else:
            print(f"  WARNING: {SYMBOL} NOT found in portfolio after trade!")
else:
    print(f"SKIP {SYMBOL}: VIX-adjusted amount ${final_amount:.0f} below $50 minimum (raw: ${sizing.get('amount', 0):.0f})")
```

### Post-Execution Portfolio State
```python
from src.portfolio.manager import get_portfolio
portfolio = get_portfolio()
print(f"\n=== Portfolio After Trades ===")
print(f"Total: ${portfolio.total_value:.2f}")
print(f"Cash: ${portfolio.cash_available:.2f}")
print(f"Positions: {len(portfolio.positions)}")
print(f"Exposure: {(portfolio.total_invested / portfolio.total_value * 100):.1f}%")
```

---

## Phase 5: Update Changelog

Update the portfolio changelog with this morning check.

**CRITICAL: Always use the Edit tool — NEVER Python inline code.** Python string manipulation with `content.find()` + slicing corrupts the file when markdown contains backtick characters. The Edit tool handles this safely.

**Steps:**
1. Use the **Read tool** to read the first 15 lines of the changelog to see the current marker and top entry header
2. Use the **Edit tool** with:
   - `old_string` = the exact marker line + blank line + the **first line of the current top entry** (e.g., `<!-- New entries are prepended below this line -->\n\n## 2026-02-21 Morning Check`)
   - `new_string` = marker + blank line + your **new full entry** + blank line + that same first line of the existing entry
3. Verify by reading the first 20 lines of the updated file — confirm your new entry appears at the top

File: `/Users/michalprusek/.claude/projects/-Users-michalprusek-PycharmProjects-etoro/memory/portfolio_changelog.md`

New entry format (insert after marker):

```markdown
## YYYY-MM-DD Morning Check

### Market Pulse
- Market: [direction] — [1-line summary]
- SPY: [trend] | RSI [value]
- Today's Calendar: [events or "None"]

### Portfolio State
- Total: $X, Cash: $Y, Exposure: X%, Positions: N
- Daily P&L: $X (X%)

### Position Status
| Symbol | P&L | Trend | RSI | Status | Note |
|--------|-----|-------|-----|--------|------|
(all positions)

### Watchlist Opportunities
| Symbol | CSS | Trend | RSI | Signal | Note |
|--------|-----|-------|-----|--------|------|
(watchlist items with notable setups, or "No actionable setups")

### Alerts
- [List of ALERT/WATCH items, or "None — all stable"]

### Trades Executed
| # | Action | Symbol | Amount | Result | Verified |
|---|--------|--------|--------|--------|----------|
(or "No trades" / "User skipped" / "User cancelled")

### Notes
- [Any observations, pattern changes, or items to watch]
```

---

## Rules
- **NO universe screening** — check only existing holdings + watchlist
- **Always run Market Regime Check FIRST** (Phase 0.5) — know the weather before trading
- Keep it fast — minimize API calls, short WebSearches
- Focus on **changes and anomalies**, not comprehensive data
- Always check ALL portfolio positions — never skip any holding
- Always check ALL watchlist symbols — they are potential BUY candidates
- If a position triggers ALERT status, explain clearly WHY and what to watch for
- **NEVER execute trades without user approval** — Phase 3 is a hard gate
- Use **AggressiveRiskLimits** for all trades
- Always use **ATR-based SL/TP** with trailing stop enabled
- Always use **conviction-based position sizing** via `calculate_position_size()`
- **Apply VIX sizing adjustment** to all new BUY positions (multiply amount by regime.sizing_adjustment)
- **BLOCK new BUYs if earnings < 5 days** — never hold through earnings in swing trading
- **REJECT BUY setups with R:R < 1:2** — insufficient reward for the risk
- **Prefer BUYs with RVOL > 1.0** — volume must confirm the setup
- **If market bias is RISK_OFF**: do not suggest new BUY positions unless extreme oversold bounce
- **If RED FLAG macro day** (CPI, FOMC, NFP, PCE): recommend reducing position sizes
- Respect daily loss circuit breaker (5%)
- Be conservative — morning check should mostly result in HOLD. Only suggest trades for clear, high-conviction setups.
- **Always run SL health check** (Phase 0) — flag missing SLs, loose SLs (>15%), SLs above price (bearish SuperTrend), legacy TPs
- **Chip sector concentration**: if semiconductors >30% of invested capital, flag prominently — earnings/tariff shock affects all chip positions simultaneously
- **Consolidate multi-position symbols** in Phase 2 — show NVDA×2 as one row with combined P&L, not two separate rows
- **TSL only when Chandelier valid** (chandelier < current price). Always recommend Fixed SL when chandelier > price
- **Always present SL Adjustment Recommendations** in Phase 3, even when no API trades are suggested
- **Use Edit tool for changelog** — never Python inline string manipulation (causes file corruption from backtick collisions)
