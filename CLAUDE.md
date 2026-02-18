# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
# Run all tests
python3 -m pytest tests/

# Run a single test file
python3 -m pytest tests/test_risk.py

# Run with verbose output
python3 -m pytest tests/ -v

# CLI usage
python3 cli.py portfolio              # Portfolio overview
python3 cli.py market analyze AAPL    # Technical analysis
python3 cli.py market price AAPL BTC  # Current prices
python3 cli.py trade check AAPL 500   # Risk dry-run
python3 cli.py trade buy AAPL 500     # Open position (demo)
python3 cli.py trade close <id>       # Close position
python3 cli.py market fundamentals AAPL # Fundamental data (valuation, analysts, sentiment, ESG)
python3 cli.py trade fees AAPL 500     # Fee estimation
python3 cli.py trade fees BTC 500 --direction SELL --leverage 2
python3 cli.py config show            # View configuration
python3 cli.py market news AAPL       # News, sentiment, analyst grades, price targets
python3 cli.py market news AAPL --format json
```

**Use `python3`, not `python`** (Python 3.12.2).

## Architecture

### Request Flow

CLI commands (Typer) → domain modules → API client → eToro REST API, with SQLite for local persistence.

**Trade execution**: `cli.py` → `trading/engine.py` (resolve symbol → risk check → get rate → execute order → log to DB)

**Market analysis**: `cli.py` → `market/data.py` (resolve symbol → fetch candles → compute indicators → generate signals/trend). Extended mode adds stochastic, ADX, OBV, support/resistance, Fibonacci.

**Fundamental analysis**: `cli.py` → `market/fundamentals.py` (search API → extract valuation, profitability, analyst ratings, sentiment, earnings, dividends, ESG)

**Fee estimation**: `cli.py` → `trading/fees.py` (resolve symbol → get spread → estimate spread cost, crypto fees, overnight fees)

**News aggregation**: `cli.py` → `market/news.py` (Finnhub articles + sentiment, FMP analyst grades + price targets, Marketaux multi-symbol news). Hybrid approach: structured APIs first, WebSearch fills gaps.

**Portfolio view**: `cli.py` → `portfolio/manager.py` (fetch from API → enrich positions with cached instrument data)

### Key Patterns

- **Synchronous everywhere** — all API calls use `httpx.Client` (not AsyncClient), no async/await in codebase
- **Module-level singletons** — `client.py`, `data.py`, `manager.py`, `news.py` use lazy `_get_client()` pattern with global `_client`
- **Lazy imports in CLI** — command functions import modules at call time for faster startup
- **Repository pattern** — `storage/repositories.py` provides CRUD classes (`PortfolioRepo`, `TradeLogRepo`, `MemoryRepo`, `InstrumentRepo`) that each manage their own connection lifecycle and return dicts (not ORM objects)
- **Result objects** — `TradeResult` (success/failure + message) and `RiskCheckResult` (passed + violations/warnings) used for structured outcomes
- **Pydantic models** — all API responses validated via models in `src/api/models.py`; config via `pydantic-settings`
- **Raw SQL** — no ORM, schema defined as inline string in `database.py`, parameterized queries throughout
- **Rate limiting + retry** — token bucket (5 req/s) in client; tenacity retry with `retry_if_exception` on `httpx.HTTPStatusError` (not `retry_if_status_code`) for 429/5xx errors

### eToro Platform Constraints & Fees

- **No partial position closes** — can only close entire position. Rebalancing must use future sizing instead of trim.
- **Trailing SL** — supported via `IsTslEnabled: True` in order payload
- **Stocks (unleveraged BUY)**: $1-2 commission, NO overnight fees
- **ETFs (unleveraged BUY)**: $0 commission, NO overnight fees
- **Crypto**: 1% buy + 0.6-1% sell spread, no overnight fees if unleveraged
- **CFDs (leveraged/short)**: overnight fees ~$0.22/day per $1K (~8%/year), 3x on weekends
- **Rule**: never hold leveraged CFDs >1-2 weeks; avoid trades where fees >2% of expected gain

### Configuration

Settings in `.env` read by `config.py` (Pydantic Settings). Two trading modes: `demo` (default, uses `ETORO_USER_KEY_DEMO`) and `real` (uses `ETORO_USER_KEY_REAL`). The `api_base` is `https://public-api.etoro.com`. Auth uses `x-api-key` + `x-user-key` headers. Demo/real is controlled by path prefix (`/demo/` for demo mode) rather than account headers.

Optional external API keys for news/data: `FINNHUB_API_KEY`, `MARKETAUX_API_KEY`, `FMP_API_KEY` — all default to `""`, module skips APIs without keys.

### Database

SQLite with WAL mode, 6 tables: `portfolio_snapshots`, `trade_log`, `position_closes`, `memories`, `instruments`, `daily_pnl`. Schema in `storage/database.py`, auto-created on CLI startup.

### Risk Limits (defaults in config.py)

$10–$1000 per trade, max 10% concentration, max 90% exposure, max 20 positions, 3% daily loss circuit breaker, 1.0x max leverage.

**AggressiveRiskLimits** (used by `/analyze-portfolio` autonomous execution): $50–$3000 per trade, max 20% concentration, max 95% exposure, 5% daily loss circuit breaker, 1.0x max leverage.

### ATR-Based Stops & Position Sizing (`src/trading/atr_stops.py`)

- `calculate_atr_stops(price, atr, direction)` — dynamic SL/TP based on volatility (2x ATR for SL, 3x ATR for TP, clamped to 1-15% SL range)
- `calculate_position_size(portfolio_value, cash, atr, price, conviction)` — conviction-based sizing: strong (3% risk, $3K max), moderate (2%, $1.5K), weak (1%, $500). ATR-adjusted, $200 cash buffer, halved if exposure >80%.
- `open_position()` accepts `atr_value`, `trailing_sl`, `limits_override` params for ATR stops + trailing SL + custom risk limits

### Custom Commands

- `/analyze-portfolio` — Multi-agent portfolio analysis with **screening**, **deep research**, and **user-approved trade execution**. 7 phases: (0) Save snapshot, (1) Load history + portfolio + build ~160-symbol universe, (1.5) 3 parallel screening agents with CSS scoring → top 25-30 candidates, (2) 4 parallel deep research agents (Technical, Fundamental, News, Risk) with enhanced outputs, (3) Synthesis + trade plan table + **HARD GATE requiring user approval**, (4) Execute only approved trades with post-trade verification, (5) Extended changelog with screening summary + approval status + verification. Respects daily loss circuit breaker (5%). Fee-aware. Uses AggressiveRiskLimits, ATR stops + trailing SL, conviction-based sizing.

### Technical Indicators

6 core (SMA, EMA, RSI, MACD, Bollinger Bands, ATR) + 5 extended (Stochastic, ADX, OBV, Support/Resistance, Fibonacci Retracement). Extended indicators available via `analyze_instrument(symbol, extended=True)`.
