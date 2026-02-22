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
            sl_above_price.append(sym)   # chandelier above price = bearish SuperTrend

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

Parse and save:
- **SPY**: trend, RSI, above/below 20 SMA, above/below 50 SMA, MA alignment
- **QQQ**: trend, RSI, above/below 20 SMA, above/below 50 SMA
- **VIX**: value, regime (VERY_LOW/LOW/NORMAL/ELEVATED/HIGH/EXTREME), sizing_adjustment
- **Overall Bias**: RISK_ON / CAUTIOUS / RISK_OFF

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
- **Today's Calendar**: [key events with impact tags: 🔴 RED FLAG / 🟡 YELLOW, or "No major events"]
- **Market Mood**: [1-line summary from News Agent]

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

## Position Status

**Consolidate same-symbol positions into one row** (e.g., NVDA×2 = combined invested + blended P&L%, single technical analysis). Use `×N` notation.

| # | Symbol | P&L | P&L% | Trend | MA Align | RSI | RVOL | Chandelier | Chan.✓? | Portfolio SL | SL Type | Earnings | News | Status |
|---|--------|-----|------|-------|----------|-----|------|-----------|--------|--------------|---------|----------|------|--------|

`Chan.✓?` = ✅ chandelier < price (bullish ST, TSL valid) | ❌ chandelier > price (bearish ST, Fixed SL only)
`SL Type` = TSL if ✅ | Fixed if ❌ | flag `⚠️ Legacy TP` if TP is set >50% above current price
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
    time.sleep(2)
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
)

if sizing.get("amount", 0) >= 50:
    result = open_position(
        symbol="SYMBOL",
        amount=sizing["amount"],
        direction="BUY",
        atr_value=ATR_VALUE,
        trailing_sl=True,
        limits_override=AggressiveRiskLimits(),
        reason="morning-check: [brief reason]"
    )
    print(f"BUY {SYMBOL} ${sizing['amount']}: {result.message}")

    if result.success:
        time.sleep(2)
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
    print(f"SKIP {SYMBOL}: calculated amount ${sizing.get('amount', 0):.0f} below $50 minimum")
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
