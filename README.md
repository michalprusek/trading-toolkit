# Trading Toolkit

CLI toolkit for the eToro public API — portfolio monitoring, technical & fundamental analysis, news aggregation, risk management, and AI-assisted trade execution.

## Features

- **Portfolio** — live positions, P&L, cash, exposure
- **Market analysis** — 11 technical indicators (RSI, MACD, Bollinger Bands, ATR, ADX, Stochastic, OBV, Fibonacci, support/resistance)
- **Fundamental analysis** — valuation, profitability, analyst ratings, ESG, earnings, dividends
- **News** — aggregated from Finnhub, Marketaux, FMP with sentiment and analyst grades
- **Fee estimation** — spread cost, crypto fees, overnight CFD fees
- **Risk management** — pre-trade checks, concentration limits, daily circuit breaker
- **ATR-based position sizing** — conviction-weighted (strong/moderate/weak) with trailing stop-loss
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
python3 cli.py market analyze AAPL         # Technical analysis (6 core indicators)
python3 cli.py market analyze AAPL --extended  # + Stochastic, ADX, OBV, Fibonacci, S/R
python3 cli.py market fundamentals AAPL    # Valuation, analysts, ESG, earnings
python3 cli.py market news AAPL            # News, sentiment, analyst grades
python3 cli.py market news AAPL --format json
```

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

## Claude Code Commands

With [Claude Code](https://claude.ai/code) installed:

```
/analyze-portfolio    # Full multi-agent analysis: screening → research → user-approved execution
/morning-check        # Daily health check: holdings + overnight news + watchlist opportunities
```

Both commands use parallel subagents for technical, fundamental, news, and risk research, then present a trade plan that requires explicit user approval before executing anything.

## Risk Limits

Two profiles available in `config.py`:

| Limit | Default | Aggressive |
|---|---|---|
| Trade size | $10 – $1,000 | $50 – $3,000 |
| Max concentration | 10% | 20% |
| Max exposure | 90% | 95% |
| Daily loss circuit breaker | 3% | 5% |
| Max leverage | 1x | 1x |

The `/analyze-portfolio` command uses AggressiveRiskLimits. Manual trades use the default profile.

## Architecture

```
cli.py                      # Typer CLI entry point
config.py                   # Pydantic Settings + risk limit profiles
src/
  api/                      # eToro HTTP client, endpoints, Pydantic models
  market/                   # Prices, candles, indicators, fundamentals, news
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
- **ETFs in demo** — eToro's demo API accepts ETF orders but never creates positions; use individual stocks instead
- **No partial closes** — eToro only supports closing entire positions; rebalance through sizing of new trades
- **Leveraged CFDs** — overnight fees apply (~8%/year); avoid holding leveraged positions more than 1–2 weeks
