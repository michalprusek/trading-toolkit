Perform a lightweight morning portfolio check — monitor existing holdings, check overnight news, flag alerts, and optionally execute position changes with user approval. NO universe screening — this is a daily health check focused on current holdings + watchlist, not a full analysis.

**Usage**: `/morning-check` or `/morning-check --mode real`

---

## Mode Setup (parse from arguments)

Check `$ARGUMENTS` for `--mode`:
- `--mode real` → set `TRADING_MODE=real` — **⚠️ REAL ACCOUNT — trades use real money**
- `--mode demo` or no argument → set `TRADING_MODE=demo` (default, safe)

Announce the mode at the start: `🔵 Mode: DEMO` or `🔴 Mode: REAL — trades will use your real eToro account`.

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
- Prompt: `Trading mode: {mode} — prepend TRADING_MODE={mode} to all CLI commands. For inline Python: import os; os.environ['TRADING_MODE'] = '{mode}' as the first line. Watchlist symbols to screen: {paste ALL merged watchlist symbols from Phase 0, excluding portfolio positions}`

---

## Phase 2: Morning Dashboard

After ALL THREE subagents return, present a consolidated morning dashboard.

### Format:

```markdown
# Morning Check — {date}

## Market Pulse
- **Market**: [bull/bear/neutral] — [1-line summary from News Agent]
- **SPY**: [trend] | RSI [value]
- **Today's Calendar**: [key events or "No major events"]

## Portfolio Overview
| Metric | Value |
|--------|-------|
| Total Value | $X |
| Cash | $X (X%) |
| Invested | $X |
| Exposure | X% |
| Daily P&L | $X (X%) |
| Positions | N |

## Position Status
| # | Symbol | P&L | Trend | RSI | Near S/R | News | Status |
|---|--------|-----|-------|-----|----------|------|--------|
(sort: ALERTs first, then WATCHes, then HOLDs)

## Alerts & Watch Items
🔴 **ALERT** (action may be needed):
- SYMBOL: [reason — e.g., "RSI 78 overbought + price at resistance $XXX"]
- SYMBOL: [reason — e.g., "Earnings in 3 days, negative analyst revision"]

🟡 **WATCH** (monitor today):
- SYMBOL: [reason — e.g., "RSI 72 approaching overbought, trend still bullish"]
- SYMBOL: [reason — e.g., "Price 1.5% from support at $XXX"]

(If no alerts/watches: "All positions stable. No action items today.")

## Watchlist Opportunities
| # | Symbol | CSS | Trend | RSI | Price | Signal | Note |
|---|--------|-----|-------|-----|-------|--------|------|
(Only OPPORTUNITY symbols from watchlist screener. If none: "No actionable setups in watchlist today.")

## Upcoming Catalysts (this week)
- [Date]: [Event] — affects [SYMBOL(s)]
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
- Watchlist symbol with ALERT-level bullish setup (RSI oversold bounce, breakout above resistance, strong positive catalyst)
- Only if portfolio has sufficient cash and exposure < 90%
- Must have clear technical entry with definable ATR stop

**No trades if:**
- All positions are HOLD/WATCH with no actionable signals
- Market conditions are too uncertain (VIX spike, pre-FOMC)
- Daily loss approaching circuit breaker

### If trades are suggested, present:

```markdown
## Proposed Actions

### SELL
| # | Symbol | Position ID | Amount | Current P&L | Reason |
|---|--------|-------------|--------|-------------|--------|

### BUY (from watchlist)
| # | Symbol | Amount | Conviction | ATR SL | ATR TP | Trail | Reason |
|---|--------|--------|------------|--------|--------|-------|--------|

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

Update the portfolio changelog with this morning check. Use the Edit tool to add a new entry to `/Users/michalprusek/.claude/projects/-Users-michalprusek-PycharmProjects-etoro/memory/portfolio_changelog.md`.

Insert right after `<!-- New entries are prepended below this line -->`:

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
- Keep it fast — minimize API calls, short WebSearches
- Focus on **changes and anomalies**, not comprehensive data
- Always check ALL portfolio positions — never skip any holding
- Always check ALL watchlist symbols — they are potential BUY candidates
- If a position triggers ALERT status, explain clearly WHY and what to watch for
- **NEVER execute trades without user approval** — Phase 3 is a hard gate
- Use **AggressiveRiskLimits** for all trades
- Always use **ATR-based SL/TP** with trailing stop enabled
- Always use **conviction-based position sizing** via `calculate_position_size()`
- Respect daily loss circuit breaker (5%)
- Be conservative — morning check should mostly result in HOLD. Only suggest trades for clear, high-conviction setups.
