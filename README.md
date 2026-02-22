# Trading Toolkit

CLI toolkit for the eToro public API — portfolio monitoring, technical & fundamental analysis, news aggregation, risk management, and AI-assisted swing-trade execution.

## Features

- **Portfolio** — live positions, P&L, cash, exposure
- **Market analysis** — 13 technical indicators (RSI, MACD, Bollinger Bands, ATR, ADX, Stochastic, OBV, Fibonacci, support/resistance) + 5 swing-trading indicators (RVOL, MA Alignment, Chandelier Exit, SuperTrend, Gap%)
- **Market Regime** — SPY + QQQ + VIX top-down analysis with RISK_ON/CAUTIOUS/RISK_OFF bias and VIX-adjusted position sizing
- **Fundamental analysis** — valuation, profitability, analyst ratings, ESG, earnings, dividends
- **News** — aggregated from Finnhub, Marketaux, FMP with sentiment and analyst grades
- **Fee estimation** — spread cost, crypto fees, overnight CFD fees
- **Risk management** — pre-trade checks, concentration limits, daily circuit breaker
- **ATR-based stops** — Chandelier Exit (primary TSL) + SuperTrend gate; legacy scalar ATR stops as fallback
- **Conviction-based sizing** — strong/moderate/weak conviction with VIX-adjusted amounts and ATR risk sizing
- **Multi-agent analysis** — `/analyze-portfolio` and `/morning-check` Claude Code commands that spawn parallel research agents and execute approved trades

## Requirements

- Python 3.12+
- eToro account with API access ([public-api.etoro.com](https://public-api.etoro.com))

## Setup

```bash
# 1. Clone and install dependencies
git clone https://github.com/michalprusek/trading-toolkit.git
cd trading-toolkit
pip install -r requirements.txt

# 2. Configure credentials
cp .env.example .env
# Edit .env and fill in your API keys

# 3. Verify setup
python3 cli.py config show
```

## Configuration

Copy `.env.example` to `.env` and set your credentials:

| Variable | Required | Description |
|---|---|---|
| `ETORO_API_KEY` | Yes | eToro API key |
| `ETORO_USER_KEY_DEMO` | Yes | Demo account user key |
| `ETORO_USER_KEY_REAL` | Yes | Real account user key |
| `TRADING_MODE` | No | `demo` (default) or `real` |
| `FINNHUB_API_KEY` | No | News articles & sentiment |
| `MARKETAUX_API_KEY` | No | Additional news source |
| `FMP_API_KEY` | No | Analyst grades & price targets |

News APIs are optional and independent — the toolkit works without them.

## CLI Reference

### Portfolio

```bash
python3 cli.py portfolio                    # Overview: positions, P&L, cash
python3 cli.py portfolio --format json      # JSON output
```

### Market

```bash
python3 cli.py market price AAPL MSFT BTC  # Current prices
python3 cli.py market analyze AAPL         # Technical analysis (core indicators)
python3 cli.py market analyze AAPL --extended  # + Stochastic, ADX, OBV, Fibonacci, S/R
python3 cli.py market fundamentals AAPL    # Valuation, analysts, ESG, earnings
python3 cli.py market news AAPL            # News, sentiment, analyst grades
python3 cli.py market news AAPL --format json
```

`market analyze` always returns swing-trading fields: `rvol`, `ma_alignment`, `chandelier`, `gap_pct`, `ema_8`, `ema_21`, `sma_200`.

### Trade

```bash
python3 cli.py trade check AAPL 500        # Risk dry-run (no order placed)
python3 cli.py trade buy AAPL 500          # Open long position
python3 cli.py trade close <position_id>   # Close position
python3 cli.py trade fees AAPL 500         # Fee estimate for a trade
python3 cli.py trade fees BTC 500 --direction SELL --leverage 2
```

### History & Memory

```bash
python3 cli.py history trades --limit 20   # Recent trade log
python3 cli.py history runs                # Analysis run history
python3 cli.py memory list                 # Stored lessons
python3 cli.py memory add lesson "..."     # Save a lesson
python3 cli.py memory search "stop loss"   # Search memories
```

### Watchlist & Config

```bash
python3 cli.py watchlist list              # eToro watchlists
python3 cli.py config show                 # Active configuration
```

## Swing-Trading Indicators

All returned by `market analyze` without `--extended`:

| Field | Description |
|---|---|
| `rvol` | Relative Volume — today vs 30-day average. >1.5 = institutional interest, <0.5 = weak conviction |
| `ma_alignment` | MA stack check: `GOLDEN` (Price>EMA21>SMA50>SMA200), `MOSTLY_BULLISH`, `MIXED`, `MOSTLY_BEARISH`, `DEATH` |
| `chandelier.long_stop` | Chandelier Exit trailing stop for long positions — `Highest_High(22) − 3×ATR(22)` |
| `chandelier.trend_up` | `true` if SuperTrend is bullish → TSL valid; `false` → use Fixed SL instead |
| `gap_pct` | Pre-market/intraday gap vs last candle close (%) |
| `ema_8`, `ema_21` | Short-term momentum MAs for swing entry/exit timing |
| `sma_200` | Long-term trend MA (`null` if < 200 bars of data) |

### Chandelier Exit + SuperTrend Stops

The Chandelier Exit is the primary trailing stop method for new positions. It anchors the stop to the highest high over the lookback window, so the stop retreats more slowly than a simple ATR trailing stop — but it can still decrease when ATR expands sharply.

```
long_stop  = Highest_High(22) − 3 × ATR(22)
short_stop = Lowest_Low(22)  + 3 × ATR(22)
```

SuperTrend (14/3) acts as a trend-state gate:
- `trend_up = true` → Trailing SL (TSL) recommended. Set in eToro UI with TSL toggle enabled.
- `trend_up = false` → SuperTrend bearish. Use Fixed SL below nearest support instead.

**Never set a TSL when SuperTrend is bearish** — the chandelier stop will be above the current price and would trigger immediately.

**Manual SL in eToro UI (existing positions):**
1. Run `python3 cli.py market analyze SYMBOL` → get `chandelier.long_stop`
2. Enter that price level in eToro UI field "Částka zisku/ztráty" (converted to P&L amount)
3. Enable the TSL toggle only if `chandelier.trend_up == true`

## Market Regime Analysis

```python
from src.market.data import analyze_market_regime
import json

regime = analyze_market_regime()
print(json.dumps(regime, indent=2, default=str))
```

Returns SPY trend, QQQ trend, VIX level/regime, overall bias (RISK_ON / CAUTIOUS / RISK_OFF), and a `sizing_adjustment` factor for new positions:

| VIX | Regime | Sizing Adjustment |
|---|---|---|
| < 20 | NORMAL | 1.0x — standard sizes |
| 20–25 | ELEVATED | 0.75x — reduce by 25% |
| 25–30 | HIGH | 0.5x — reduce by 50% |
| > 30 | EXTREME | 0.25x — capital preservation |

VIX is fetched from Yahoo Finance (free, no API key required) with Finnhub as fallback.

## Claude Code Commands

With [Claude Code](https://claude.ai/code) installed:

```
/analyze-portfolio    # Full multi-agent analysis: screening → research → user-approved execution
/morning-check        # Daily health check: holdings + overnight news + watchlist opportunities
```

### What the commands do

Both commands follow a **top-down** workflow: market regime first, then individual stocks.

**`/morning-check`** — 5-phase lightweight daily check:
1. Portfolio state + health checks (missing SLs, loose SLs, chip concentration, legacy TPs)
2. Market regime check (SPY/QQQ/VIX bias)
3. Three parallel agents: Technical Quick Check, News & Events, Watchlist Screener
4. Consolidated dashboard with position status table (HOLD/WATCH/ALERT) + watchlist opportunities
5. Trade suggestions with SL adjustment recommendations → **hard approval gate** → execute → changelog

**`/analyze-portfolio`** — 7-phase comprehensive analysis:
1. Portfolio snapshot + market regime + build ~200-symbol universe
2. CSS screening: 3 parallel screeners score all symbols (0–100), top 25–30 pass to research
3. Deep research: 4 parallel agents (Technical with Entry/SL/TP/R:R, Fundamental, News, Risk)
4. Synthesis: trade plan table with setup scores + **hard approval gate** (requires explicit `approve`)
5. Execute approved trades with post-trade verification
6. Extended changelog

**Swing-trading rules enforced by both commands:**
- Earnings block: never open new positions within 5 days of earnings
- R:R gate: reject BUY setups with Risk:Reward < 1:2
- VIX sizing: multiply all new position sizes by `sizing_adjustment`
- Volume confirmation: prefer RVOL > 1.0
- MA alignment: prefer GOLDEN or MOSTLY_BULLISH entries
- Sector RS: check if the sector is in rotation (outperforming SPY)

### CSS Scoring (Composite Screening Score)

Used by the screener agents to rank candidates 0–100:

```
CSS = Trend(30%) + Momentum(25%) + Volatility(20%) + Signals(25%)

Post-adjustments:
  +5 if RVOL > 1.5  (volume confirms institutional interest)
  −5 if RVOL < 0.5  (no conviction behind price move)
  +5 if MA = GOLDEN (all MAs perfectly stacked)
  −10 if MA = DEATH (all MAs bearish)
  Cap CSS at 40 if ADX > 35 AND trend BEARISH (falling knife protection)
```

Threshold: CSS ≥ 65 + bullish trend + R:R ≥ 1:2 = OPPORTUNITY signal.

## Risk Limits

Two profiles available in `config.py`:

| Limit | Default | Aggressive |
|---|---|---|
| Trade size | $10 – $1,000 | $50 – $3,000 |
| Max concentration | 10% | 20% |
| Max exposure | 90% | 95% |
| Daily loss circuit breaker | 3% | 5% |
| Max leverage | 1x | 1x |

The `/analyze-portfolio` and `/morning-check` commands use `AggressiveRiskLimits`. Manual trades use the default profile.

### eToro Platform Constraints

- **No partial closes** — eToro only supports closing entire positions; rebalance through sizing of new trades
- **No API for SL/TP modification** — existing positions' stops must be set manually in the eToro UI
- **ETFs in demo** — eToro's demo API accepts ETF orders but never creates positions; use individual stocks instead
- **Leveraged CFDs** — overnight fees ~$0.22/day per $1K (~8%/year, 3× on weekends); avoid holding more than 1–2 weeks
- **Stocks/ETFs (unleveraged BUY)** — $0–2 commission, no overnight fees; best for long-term holds

## Architecture

```
cli.py                      # Typer CLI entry point
config.py                   # Pydantic Settings + risk limit profiles
src/
  api/                      # eToro HTTP client, endpoints, Pydantic models
  market/
    data.py                 # Prices, candles, analyze_instrument(), analyze_market_regime()
    indicators.py           # SMA, EMA, RSI, MACD, BB, ATR, Chandelier, SuperTrend, RVOL, MA Alignment
    hours.py                # Market hours utility
    fundamentals.py         # Valuation, analysts, ESG, earnings
    news.py                 # Finnhub, Marketaux, FMP aggregation
  portfolio/                # Portfolio fetch and position enrichment
  trading/                  # Order execution, risk checks, fee estimation, ATR sizing
  storage/                  # SQLite (WAL mode): snapshots, trade log, instruments, memories
.claude/
  agents/                   # Subagent definitions (technical, fundamental, news, risk, screener)
  commands/                 # Slash commands (analyze-portfolio, morning-check)
```

All API calls are synchronous (`httpx.Client`). Rate limiting: 5 req/s token bucket with tenacity retry on 429/5xx.

## Tests

```bash
python3 -m pytest tests/ -v
```

## Notes

- **Demo mode by default** — set `TRADING_MODE=real` only when you intend to trade with real money
- **Always approve trades manually** — both commands stop at a hard gate and wait for explicit `approve` before executing
- **ETFs in demo** — eToro's demo API accepts ETF orders but never creates positions; use individual stocks instead
- **No partial closes** — eToro only supports closing entire positions; rebalance through sizing of new trades
- **Leveraged CFDs** — overnight fees apply (~8%/year); avoid holding leveraged positions more than 1–2 weeks
