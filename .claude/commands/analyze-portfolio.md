Perform a comprehensive multi-agent portfolio analysis with **screening**, **deep research**, and **user-approved trade execution**. You will orchestrate a team of specialized agents that work in parallel, synthesize their results, present a trade plan for user approval, and only then execute approved trades with post-trade verification. Follow these phases exactly.

**Usage**: `/analyze-portfolio` or `/analyze-portfolio --mode real`

---

## Mode Setup (parse from arguments)

Check `$ARGUMENTS` for `--mode`:
- `--mode real` → set `TRADING_MODE=real` — **⚠️ REAL ACCOUNT — trades will use real money**
- `--mode demo` or no argument → set `TRADING_MODE=demo` (default, safe)

Announce the mode prominently before Phase 0: `🔵 Mode: DEMO` or `🔴 Mode: REAL — ALL TRADE EXECUTIONS WILL USE YOUR REAL eToro ACCOUNT`.

**Apply the mode to every command in this workflow:**
- All `python3 cli.py ...` calls → prepend `TRADING_MODE={mode}` (e.g. `TRADING_MODE=real python3 cli.py portfolio --format json`)
- All inline Python snippets → add `import os; os.environ['TRADING_MODE'] = '{mode}'` as the **very first line**, before any other imports
- Also pass `--mode {mode}` to all subagent prompts so they can use the correct environment

---

## Phase 0: Initialize

Save a portfolio snapshot to the database for historical tracking:

```python
from src.portfolio.manager import save_snapshot
snapshot_id = save_snapshot()
print(f"Portfolio snapshot saved (ID: {snapshot_id})")
```

---

## Phase 1: Load History + Gather Portfolio Data + Build Universe

### Step 1.1: Get Current Portfolio

Run this command to get the current portfolio state:
```bash
python3 cli.py portfolio --format json
```
Parse the JSON output. Note total value, invested amount, P&L, cash available, and all open positions with their symbols, directions, amounts, P&L, and leverage. Save this as `portfolio_data` for use in agent prompts.

### Step 1.2: Load History

Spawn the **History Agent** using the Task tool:
- `subagent_type: "general-purpose"`
- `model: "sonnet"`
- `description: "Load analysis history"`
- Prompt: Read the file `/Users/michalprusek/.claude/projects/-Users-michalprusek-PycharmProjects-etoro/memory/portfolio_changelog.md` and provide a structured summary containing: (1) date of last analysis, (2) decisions made last time, (3) open watch items / themes still relevant, (4) any recurring patterns across analyses. If the changelog is empty or has no entries yet, say "No prior analysis found — this is the first run."

Wait for the History Agent to return before proceeding.

### Step 1.3: Build Instrument Universe

After getting portfolio data and watchlists, build the **instrument universe** for screening:

1. Start with the hardcoded list of ~200 symbols below
2. Add symbols from eToro watchlists:
```python
from src.portfolio.manager import get_watchlists
watchlists = get_watchlists()
watchlist_symbols = []
for wl in watchlists:
    for item in wl.get("items", []):
        sym = item.get("symbol", "")
        if sym:
            watchlist_symbols.append(sym)
print(f"Watchlist symbols: {watchlist_symbols}")
```
3. Add all symbols from the current portfolio
4. Deduplicate the combined list
5. Split into **3 roughly equal batches** for the screening agents

#### Hardcoded Universe (~200 symbols)

```
# US Mega-Cap Tech (15)
AAPL, MSFT, GOOGL, AMZN, META, NVDA, TSLA, AVGO, ORCL, CRM, AMD, ADBE, NFLX, INTC, CSCO

# US Large-Cap Tech / Growth (15)
NOW, UBER, SHOP, XYZ, SNOW, PLTR, PANW, CRWD, DDOG, NET, ZS, TEAM, MRVL, MU, ANET

# Semiconductors (7)
ASML, TSM, KLAC, LRCX, QCOM, TXN, ON

# AI / Cloud (4)
SMCI, ARM, DELL, WDAY

# Financials (10)
JPM, BAC, GS, MS, V, MA, BLK, AXP, C, SCHW

# Fintech (4)
PYPL, COIN, SOFI, HOOD

# Healthcare (10)
UNH, JNJ, LLY, PFE, ABBV, MRK, TMO, ABT, AMGN, ISRG

# Biotech (4)
GILD, REGN, VRTX, MRNA

# Defense & Aerospace (8)
LMT, RTX, NOC, GD, LHX, HII, BA, LDOS

# Consumer Discretionary (8)
HD, NKE, SBUX, MCD, TJX, BKNG, ABNB, CMG

# Consumer Staples (6)
PG, KO, PEP, COST, WMT, CL

# Energy (8)
XOM, CVX, COP, SLB, EOG, MPC, PSX, OXY

# Industrials (6)
CAT, DE, GE, HON, UNP, MMM

# Materials (4)
LIN, APD, FCX, NEM

# Commodities / Mining (4)
VALE, BHP, RIO, GOLD

# Real Estate (4)
PLD, AMT, EQIX, SPG

# Utilities (3)
NEE, DUK, SO

# Communication (4)
DIS, CMCSA, T, VZ

# China ADRs (5)
BABA, JD, PDD, BIDU, LI

# European ADRs (4)
SAP, NVO, AZN, SHEL

# US Broad ETFs (8) — demo-restricted, used for benchmarking only
SPY, QQQ, IWM, DIA, VTI, VOO, ARKK, XLK

# Sector ETFs (10) — demo-restricted
XLE, XLF, XLV, XLI, XLP, XLY, XLU, XLB, XLRE, XLC

# International ETFs (6) — demo-restricted
EFA, EEM, FXI, EWJ, EWG, EWZ

# Bond / Income ETFs (5) — demo-restricted
TLT, HYG, LQD, BND, SCHD

# Commodity ETFs (4) — demo-restricted
GLD, SLV, USO, UNG

# Crypto (11)
BTC, ETH, SOL, ADA, XRP, DOGE, DOT, AVAX, LINK, UNI, NEAR
```

Print the total universe size and batch sizes before proceeding to Phase 1.5.

---

## Phase 1.5: Technical Screening

Spawn **3 parallel batch-screener agents** in a SINGLE message with multiple Task tool calls. Each agent gets one batch of ~50 symbols.

### Screening Agent Setup
- `subagent_type: "batch-screener"`
- `model: "sonnet"`
- `description: "Screen batch N of 3"`

Each screening agent prompt should include ONLY the dynamic data:

> **Trading mode**: {mode} — prepend `TRADING_MODE={mode}` to all CLI commands. For inline Python: `import os; os.environ['TRADING_MODE'] = '{mode}'` as the first line.
> **Your batch of symbols**: {paste batch N symbols}
> **Portfolio positions in this batch** (MUST always include in results): {paste any portfolio symbols that fall in this batch}

The agent's system prompt already contains the full CSS formula, Section A/B output format, and quality standards.

### After all 3 screening agents return:

1. **Collect all portfolio positions first** — gather ALL symbols marked [PORTFOLIO] from Section A of each screening agent's output. These are **MANDATORY** and will ALWAYS be included in deep analysis regardless of CSS score.
2. **Merge** all top-15 new candidate lists from Section B (up to 45 symbols total)
3. **Sort** new candidates by CSS descending
4. **Take top 25-30** new candidates for deep analysis
5. **Combine**: portfolio positions + top new candidates = final candidate list for Phase 2
6. Deduplicate — if a portfolio position already appears in the top candidates, keep it once but mark it as [PORTFOLIO]
7. Print a **Screening Summary** table to the user:

```markdown
## Screening Summary
- Universe scanned: N symbols across M batches
- Symbols with data: X / N
- Failed/skipped: Y symbols
- Portfolio positions (always included): P symbols

### Portfolio Positions (mandatory deep analysis)
| # | Symbol | CSS | Trend | RSI | ATR% | Price | Status |
|---|--------|-----|-------|-----|------|-------|--------|
(All current holdings — these are ALWAYS analyzed regardless of CSS score)

### Top New Candidates (sorted by CSS)
| # | Symbol | CSS | Trend | RSI | ATR% | Price |
|---|--------|-----|-------|-----|------|-------|
```

This combined list (portfolio positions + top new candidates, typically ~30-45 symbols) is what Phase 2 agents will analyze in depth. **Every single portfolio holding MUST appear in the Phase 2 analysis.**

---

## Phase 2: Deep Research (4 Parallel Agents)

Spawn ALL FOUR agents simultaneously in a SINGLE message with multiple Task tool calls. Each agent gets the **filtered candidate list** from Phase 1.5 (NOT the full universe). Also embed the portfolio positions from Phase 1.

**CRITICAL**: Every agent MUST analyze ALL current portfolio positions. Portfolio positions are mandatory — they need HOLD/SELL verdicts regardless of their screening score. When passing symbols to agents, clearly mark portfolio positions with [PORTFOLIO] tag so agents prioritize them.

### Agent 1: Technical Agent
- `subagent_type: "technical-deep-analysis"`
- `model: "sonnet"`
- `description: "Technical analysis"`
- Prompt (dynamic data only — the agent's system prompt already defines the full analysis process):

> **Trading mode**: {mode} — prepend `TRADING_MODE={mode}` to all CLI commands. For inline Python: `import os; os.environ['TRADING_MODE'] = '{mode}'` as the first line.
> **Filtered candidates** (from screening): {paste the filtered symbol list with CSS scores}
> **Current portfolio positions [PORTFOLIO — MANDATORY]**: {paste position symbols and directions from Phase 1}

### Agent 2: Fundamental Agent
- `subagent_type: "fundamental-analysis"`
- `model: "sonnet"`
- `description: "Fundamental analysis"`
- Prompt (dynamic data only):

> **Trading mode**: {mode} — prepend `TRADING_MODE={mode}` to all CLI commands. For inline Python: `import os; os.environ['TRADING_MODE'] = '{mode}'` as the first line.
> **Filtered candidates**: {paste symbols from screening}
> **Current portfolio positions [PORTFOLIO — MANDATORY]**: {paste symbols, directions, invested amounts from Phase 1}

### Agent 3: News Agent
- `subagent_type: "market-news-research"`
- `model: "sonnet"`
- `description: "Market news research"`
- Prompt (dynamic data only):

> **Trading mode**: {mode} — prepend `TRADING_MODE={mode}` to all CLI commands. For inline Python: `import os; os.environ['TRADING_MODE'] = '{mode}'` as the first line.
> **Filtered candidates**: {paste symbols from screening with CSS scores}
> **Current portfolio positions [PORTFOLIO — MANDATORY]**: {paste symbols from Phase 1}

### Agent 4: Risk Agent
- `subagent_type: "risk-assessment"`
- `model: "sonnet"`
- `description: "Risk assessment"`
- Prompt (dynamic data only):

> **Trading mode**: {mode} — prepend `TRADING_MODE={mode}` to all CLI commands. For inline Python: `import os; os.environ['TRADING_MODE'] = '{mode}'` as the first line.
> **Current portfolio positions**: {paste full position details — symbols, amounts, P&L, leverage, direction}
> **Portfolio totals**: {paste total value, invested, cash, overall P&L from Phase 1}
> **Filtered candidates for potential ADD**: {paste candidate symbols}

---

## Phase 3: Synthesis + Trade Plan

After ALL Phase 2 agents return, synthesize their results.

### Step 3.1: Portfolio Health Summary

Combine insights from all 4 agents + history:
- Overall allocation assessment
- Risk exposure analysis (from Risk Agent)
- Market environment context (from News Agent)
- Changes since last analysis (from History Agent)
- Diversification score and correlation risk
- Fee drag assessment (total overnight/CFD fees across portfolio)
- Circuit breaker headroom

### Step 3.2: Position-by-Position Analysis Cards

For EACH position in portfolio AND each new candidate with a BUY recommendation, create an analysis card:

- **Technical** (from Technical Agent): trend, weekly alignment, key signals, S/R levels, pattern, relative strength vs SPY, ATR value
- **Fundamental** (from Fundamental Agent): valuation, sector P/E comparison, analysts, earnings risk level, estimated fair value
- **News** (from News Agent): recent developments, sentiment score (-5 to +5), upcoming catalysts
- **Cost** (from Fundamental Agent): spread + overnight fee impact + fee drag assessment
- **Risk** (from Risk Agent): concentration, correlation group, scenario impact
- **History** (from History Agent): what was said about this position last time
- **Verdict**: **HOLD** / **SELL** / **ADD** with specific rationale synthesizing all dimensions
- **Conviction**: **strong** (3-4 agents agree) / **moderate** (2 agents agree) / **weak** (mixed signals)

### Step 3.3: Present Trade Plan Table

```markdown
## Proposed Trade Plan

### SELL Orders
| # | Symbol | Position ID | Amount | Current P&L | Reason |
|---|--------|-------------|--------|-------------|--------|

### BUY Orders
| # | Symbol | Amount | Conviction | ATR SL | ATR TP | Trail | Reason |
|---|--------|--------|------------|--------|--------|-------|--------|

### HOLD (no action)
| # | Symbol | Amount | P&L | Note |
|---|--------|--------|-----|------|

### Summary
- Total SELL: $X (freeing capital)
- Total BUY: $Y (new deployment)
- Net cash change: +/-$Z
- Post-trade exposure: X%
- Estimated total spread/commission cost: $W
```

### Step 3.4: HARD GATE — WAIT FOR USER APPROVAL

**STOP HERE. DO NOT PROCEED TO PHASE 4 UNTIL THE USER EXPLICITLY APPROVES.**

Present the trade plan above and say to the user:

> **Review the proposed trade plan above.** You can:
> - **Approve all**: reply `approve` or `ano`
> - **Approve with exceptions**: reply `approve except SYMBOL1, SYMBOL2`
> - **Modify a trade**: reply `modify SYMBOL amount=XXX` or `modify SYMBOL conviction=strong`
> - **Cancel all trades**: reply `cancel` or `zrusit`
> - **Ask questions**: ask anything about the analysis before deciding
>
> I will NOT execute any trades until you explicitly approve.

**DO NOT CONTINUE. WAIT FOR USER RESPONSE.**

---

## Phase 4: Execute Approved Trades

**Only execute trades that the user approved in Step 3.4.** If the user said "cancel", skip this entire phase and go to Phase 5.

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
        # STOP — do not execute any trades, go to Phase 5
```

### Execution Order
1. **SELL approved verdicts first** (frees capital)
2. **Rebalancing** (note oversized positions for future sizing — eToro doesn't support partial closes)
3. **BUY approved verdicts last** (uses freed capital)

### For SELL verdicts:
```python
from src.trading.engine import close_position
import time

result = close_position(
    position_id=POSITION_ID,
    instrument_id=INSTRUMENT_ID,
    reason="analyze-portfolio: [brief reason from synthesis]"
)
print(f"SELL {SYMBOL}: {result.message}")

# Post-trade verification
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

### For BUY verdicts:
```python
from config import AggressiveRiskLimits
from src.trading.engine import open_position
from src.trading.atr_stops import calculate_position_size
from src.portfolio.manager import get_portfolio
from src.market.data import resolve_symbol
import time

# Refresh portfolio after any SELLs
portfolio = get_portfolio()
_total_value = portfolio.total_value

# 1. Calculate position size (use ATR + conviction from synthesis)
sizing = calculate_position_size(
    portfolio_value=_total_value,
    cash_available=portfolio.cash_available,
    atr=ATR_VALUE,                    # from Technical Agent
    price=CURRENT_PRICE,              # from Technical Agent
    conviction="strong|moderate|weak", # from Phase 3 consensus
    current_exposure_pct=portfolio.total_invested / portfolio.total_value if portfolio.total_value > 0 else 0,
)

if sizing.get("amount", 0) >= 50:
    # 2. Execute trade with ATR stops + trailing SL
    result = open_position(
        symbol="SYMBOL",
        amount=sizing["amount"],
        direction="BUY",
        atr_value=ATR_VALUE,
        trailing_sl=True,
        limits_override=AggressiveRiskLimits(),
        reason="analyze-portfolio: [brief reason]"
    )
    print(f"BUY {SYMBOL} ${sizing['amount']}: {result.message}")

    # 3. Post-trade verification
    if result.success:
        time.sleep(2)
        portfolio = get_portfolio()
        # resolve_symbol returns a dict {'instrument_id': int, ...}, NOT a bare int
        iid_data = resolve_symbol("SYMBOL")
        iid = iid_data['instrument_id'] if isinstance(iid_data, dict) else iid_data

        if result.position_id:
            found = any(
                getattr(p, 'position_id', None) == result.position_id
                for p in portfolio.positions
            )
        else:
            # position_id is None — search by instrument_id
            found = any(
                getattr(p, 'instrument_id', None) == iid
                for p in portfolio.positions
            )

        if found:
            print(f"  VERIFIED: {SYMBOL} confirmed in portfolio")
        else:
            print(f"  WARNING: {SYMBOL} NOT found in portfolio after trade!")
else:
    print(f"SKIP {SYMBOL}: calculated amount ${sizing.get('amount', 0):.0f} below $50 minimum")
```

### Rebalancing Note

After SELLs and before BUYs, check for oversized positions. Since eToro doesn't support partial closes, note any positions exceeding 1.5x their target weight in the changelog for future adjustment through sizing.

### After All Trades — Batch Verification

```python
from src.portfolio.manager import get_portfolio
portfolio = get_portfolio()
print(f"\n=== Final Portfolio State ===")
print(f"Total: ${portfolio.total_value:.2f}")
print(f"Cash: ${portfolio.cash_available:.2f}")
print(f"Invested: ${portfolio.total_invested:.2f}")
print(f"Positions: {len(portfolio.positions)}")
print(f"Exposure: {(portfolio.total_invested / portfolio.total_value * 100):.1f}%" if portfolio.total_value > 0 else "Exposure: 0%")
```

---

## Phase 5: Update Changelog

After presenting the analysis AND executing approved trades (or noting cancellation), update the portfolio changelog. Use the Edit tool to add a new entry to `/Users/michalprusek/.claude/projects/-Users-michalprusek-PycharmProjects-etoro/memory/portfolio_changelog.md`.

Insert the new entry right after the `<!-- New entries are prepended below this line -->` marker. Format:

```markdown
## YYYY-MM-DD — Analysis #N
### Screening Summary
- Universe scanned: N symbols across 3 batches
- Symbols with data: X / N
- Top CSS scores: SYMBOL1 (XX), SYMBOL2 (XX), SYMBOL3 (XX)
- Bottom CSS scores: SYMBOL1 (XX), SYMBOL2 (XX)
- Candidates passed to deep analysis: M symbols
### Market Snapshot
- S&P 500: [direction/level], VIX: [level], Overall sentiment: [bullish/neutral/bearish]
- Key macro theme: [brief]
- Catalyst calendar: [upcoming events]
### Portfolio State (Before Trades)
- Total: $X, Cash: $Y, Positions: N, Overall P&L: $Z (X%)
- Exposure: X%, Circuit breaker headroom: X%
### Positions Analyzed
- SYMBOL: VERDICT (conviction) — [1-line reasoning combining technical + fundamental + news] — sentiment: X/5
(repeat for each position)
### Proposed Trade Plan
- [full trade plan as presented in Phase 3]
### Approval Status
- User response: "approved all" / "approved with exceptions: SYMBOL1, SYMBOL2 excluded" / "modified: SYMBOL amount changed to $X" / "cancelled — no trades executed"
### Trades Executed
| # | Action | Symbol | Amount | Result | Verified |
|---|--------|--------|--------|--------|----------|
| 1 | BUY    | SYMBOL | $XXX   | success (ID: XXX) | YES/NO |
| 2 | SELL   | SYMBOL | $XXX   | success | YES/NO |
- ... or "No trades executed" / "Circuit breaker triggered" / "User cancelled"
### Rebalancing Actions
- [List any rebalancing notes or "No rebalancing needed"]
- [Note oversized positions flagged for future adjustment]
### Fee Assessment
- Total estimated overnight fee drag across portfolio: $X/week
- Positions with highest fee impact: [list]
- Recommendation: [any fee-related actions]
### Decisions / Recommendations Made
- [Each specific recommendation with reasoning]
### Key Observations
- [2-3 most important insights from the analysis]
### Open Themes / Watch Items
- [Items to monitor before next analysis — earnings dates, price levels, macro events]
### Portfolio State (After Trades)
- Total: $X, Cash: $Y, Positions: N, Overall P&L: $Z (X%)
- Exposure: X%
```

Increment the analysis number based on how many entries already exist. Use today's date.

---

## Rules
- Use **AggressiveRiskLimits** for all trades: $50-$3000 per trade, max 20% concentration, max 95% exposure, 1x leverage only
- **Always use ATR-based SL/TP** with trailing stop enabled (`trailing_sl=True`)
- **Always use conviction-based position sizing** via `calculate_position_size()` — never hardcode amounts
- Respect daily loss circuit breaker (5%) — halt ALL execution if triggered
- Factor in fees — avoid trades where fees eat >2% of expected gain. Pay special attention to:
  - Overnight/weekend fees on CFD positions (SELL direction or leveraged)
  - 1% crypto buy/sell fee
  - Spread costs on frequent trading
- Be conservative with SELL verdicts — prefer HOLD over unnecessary churning (spread cost of closing + re-opening)
- **NO leverage** — always 1x. Reject any leveraged trade suggestions.
- Flag any positions approaching earnings dates (risk of gap)
- Note dividend ex-dates for income-oriented positions
- Reference prior analysis decisions from changelog when relevant
- Log EVERY trade execution result in the changelog (success or failure, verified or not)
- **NEVER execute trades without user approval** — Phase 3.4 is a hard gate
- **eToro ETF restriction (CONFIRMED)**: ETFs (SPY, QQQ, EFA, XLB, EWJ, TLT, GLD, etc.) are NOT tradeable in eToro demo mode — API accepts the order but no position is ever created. Do NOT recommend ETF BUYs. Use individual stocks for sector/international diversification instead. (Confirmed: SPY Analysis #1, EFA/XLB/EWJ Analysis #2)
