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
- **Trailing SL (new positions only)** — set via `IsTslEnabled: True` in open-order payload; **no API endpoint exists to modify SL/TP/TSL on existing positions** — must be done manually in eToro UI
- **eToro UI SL format (existing positions)** — field "Částka zisku/ztráty" = minimum P&L in $, not stock price. Formula: `SL_$ = (SL_price / open_rate - 1) × invested`. To protect X% trail: `SL_$ = current_value × (1 - X%) - invested`
- **Position close verification** — after `close_position()`, wait 8s before re-checking (not 3s); crypto closes may show position still present at 3s even when order succeeded (statusID=1 = placed)
- **Always recommend SL/TSL values** — for every WATCH/ALERT position without stops, always tell the user what specific values to set manually in eToro (SL price or TSL $amount via "Částka zisku/ztráty"). Don't just flag missing stops — give exact numbers.
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

### Chandelier Exit + SuperTrend Stops (`src/trading/atr_stops.py`, `src/market/indicators.py`)

- `calculate_chandelier_stops(df, price, direction)` — **primary TSL method**. Stop = `Highest_High(22) - 3×ATR` for BUY (retreats more slowly than a simple ATR trailing stop, but can still decrease when ATR expands sharply). SuperTrend (14/3) provides trend-state gate. Returns `sl_rate`, `sl_pct`, `trend_up`, `supertrend_value`, `method="chandelier"`.
- `calculate_atr_stops(price, atr, direction)` — legacy scalar fallback (2x ATR for SL, 3x ATR for TP, clamped 1-15%). Used when OHLC df not available.
- `calculate_position_size(portfolio_value, cash, atr, price, conviction)` — conviction-based sizing: strong (3% risk, $3K max), moderate (2%, $1.5K), weak (1%, $500). ATR-adjusted, $200 cash buffer, halved if exposure >80%.
- `open_position()` accepts `df` (OHLCV DataFrame for Chandelier stops), `atr_value` (scalar fallback), `trailing_sl`, `limits_override`. **TSL auto-enabled for BUY positions when df is provided and SuperTrend is bullish** (`chandelier["trend_up"] == True`). TSL is never auto-enabled for SELL direction.
- `analyze_instrument()` returns `chandelier.long_stop`, `chandelier.short_stop`, `chandelier.trend_up`, `chandelier.supertrend` in every analysis result.

**TSL recommendation for existing positions (eToro UI manual entry):**
1. Run `python3 cli.py market analyze SYMBOL` → get `chandelier.long_stop` value.
2. Compute TSL amount: `SL_$ = (chandelier_long_stop / open_rate - 1) × invested`
3. Enter in eToro UI field "Částka zisku/ztráty". Negative = accept loss, positive = protect profit.
4. **Only activate TSL** (`IsTslEnabled`) when `chandelier.trend_up == True`. In bearish SuperTrend, prefer tighter fixed SL or consider closing position instead.

### Custom Commands

- `/morning-check` — Lightweight daily portfolio health check. Phases: (0) Get portfolio + watchlist, (0.5) **Market Regime Check** (SPY + QQQ + VIX → bias + sizing adjustment), (1) 3 parallel agents (Technical Quick Check, News & Events, Watchlist Screener), (2) Consolidated morning dashboard with VIX regime, MA alignment, RVOL, earnings calendar, (3) Trade suggestions with entry zones + R:R ratios + hard approval gate, (4) Execute approved trades, (5) Changelog. Enforces earnings block (<5 days), R:R >= 1:2, VIX-adjusted sizing.

- `/analyze-portfolio` — Comprehensive multi-agent portfolio analysis. Phases: (0) Save snapshot, (1) **Market Regime Check** + load history + portfolio + build ~200-symbol universe, (1.5) 3 parallel CSS screeners (with RVOL + MA alignment bonuses), (2) 4 parallel deep research agents (Technical with entry/SL/TP/R:R + setup score, Fundamental with earnings block, News with insider/short interest/options, Risk with VIX-aware scenarios), (3) Synthesis + trade plan with entry zones + R:R ratios + setup scores + **HARD GATE**, (4) Execute with VIX-adjusted sizing + post-trade verification, (5) Extended changelog. Enforces R:R >= 1:2, earnings block, VIX sizing, sector RS.

### Technical Indicators

6 core (SMA, EMA, RSI, MACD, Bollinger Bands, ATR) + 5 extended (Stochastic, ADX, OBV, Support/Resistance, Fibonacci Retracement — all require `extended=True`) + 6 swing-trading (ema_8, ema_21, sma_200, rvol, ma_alignment, gap_pct — always computed).

**Swing-Trading Indicators** (always included in `analyze_instrument()` output):
- `ema_8`, `ema_21`: Short-term momentum MAs for swing entry/exit timing
- `sma_200`: Long-term trend MA (None if < 200 bars of data)
- `rvol`: Relative Volume — today's volume vs 30-day average. > 1.5 = institutional interest, < 0.5 = weak conviction
- `ma_alignment`: Golden alignment check — `{"status": "GOLDEN|MOSTLY_BULLISH|MIXED|MOSTLY_BEARISH|DEATH", "bullish_layers": 0-3, ...}`. GOLDEN = Price > EMA21 > SMA50 > SMA200.
- `gap_pct`: Pre-market/intraday gap vs last candle close (%)

**Market Regime Analysis** (`analyze_market_regime()`):
- Returns SPY + QQQ trends, VIX level/regime, overall bias (RISK_ON/CAUTIOUS/RISK_OFF)
- VIX-based position sizing: < 20 = 1.0x, 20-25 = 0.75x, 25-30 = 0.5x, > 30 = 0.25x
- Used by morning-check and analyze-portfolio as first step (top-down approach)

### Swing Trading Rules (enforced by agents)

- **Earnings block**: Never open new positions < 5 days before earnings (gap risk)
- **R:R filter**: Reject BUY setups with Risk:Reward ratio < 1:2
- **Volume confirmation**: Prefer entries with RVOL > 1.0
- **MA alignment**: Prefer entries with GOLDEN or MOSTLY_BULLISH alignment
- **VIX sizing**: Adjust all new position sizes by VIX sizing_adjustment factor
- **Sector RS**: Check if the stock's sector is in rotation (outperforming SPY)
- **Smart money**: Check insider trading, short interest, unusual options activity via WebSearch
