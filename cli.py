from __future__ import annotations

import json
import os
import sys
from typing import Optional

# Early mode detection — must happen before src.storage.database is imported,
# which triggers config.py to call Settings() as a module-level singleton.
_mode_idx = next((i for i, a in enumerate(sys.argv) if a == "--mode"), None)
if _mode_idx is not None and _mode_idx + 1 < len(sys.argv):
    os.environ["TRADING_MODE"] = sys.argv[_mode_idx + 1]
del _mode_idx

import typer
from rich.console import Console
from rich.table import Table

from src.storage.database import init_db

console = Console()
app = typer.Typer(help="eToro Trading Toolkit CLI")

# Sub-apps
portfolio_app = typer.Typer(help="Portfolio management")
market_app = typer.Typer(help="Market data & analysis")
trade_app = typer.Typer(help="Trading operations")
history_app = typer.Typer(help="Trade history")
memory_app = typer.Typer(help="Persistent memories")
watchlist_app = typer.Typer(help="Watchlists")
config_app = typer.Typer(help="Configuration")

app.add_typer(portfolio_app, name="portfolio")
app.add_typer(market_app, name="market")
app.add_typer(trade_app, name="trade")
app.add_typer(history_app, name="history")
app.add_typer(memory_app, name="memory")
app.add_typer(watchlist_app, name="watchlist")
app.add_typer(config_app, name="config")


# ── Portfolio ───────────────────────────────────────────────────────────

@portfolio_app.callback(invoke_without_command=True)
def portfolio_overview(
    ctx: typer.Context,
    format: str = typer.Option("table", help="Output format: table or json"),
):
    if ctx.invoked_subcommand is not None:
        return
    from src.portfolio.manager import get_portfolio, get_positions_with_symbols

    portfolio = get_portfolio()
    positions = get_positions_with_symbols()

    if format == "json":
        data = {
            "total_value": portfolio.total_value,
            "total_invested": portfolio.total_invested,
            "total_pnl": portfolio.total_pnl,
            "cash_available": portfolio.cash_available,
            "positions": positions,
        }
        console.print_json(json.dumps(data, default=str))
        return

    console.print(f"\n[bold]Portfolio Overview[/bold]")
    console.print(f"  Total Value:    ${portfolio.total_value:,.2f}")
    console.print(f"  Invested:       ${portfolio.total_invested:,.2f}")
    console.print(f"  P&L:            ${portfolio.total_pnl:,.2f}")
    console.print(f"  Cash Available: ${portfolio.cash_available:,.2f}")
    console.print(f"  Positions:      {len(positions)}\n")

    if not positions:
        console.print("  No open positions.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Symbol")
    table.add_column("Direction")
    table.add_column("Amount", justify="right")
    table.add_column("Open Rate", justify="right")
    table.add_column("P&L ($)", justify="right")
    table.add_column("P&L (%)", justify="right")
    table.add_column("Leverage")

    for p in positions:
        pnl_color = "green" if p["net_profit"] >= 0 else "red"
        table.add_row(
            p["symbol"],
            p["direction"],
            f"${p['amount']:,.2f}",
            f"${p['open_rate']:,.4f}",
            f"[{pnl_color}]${p['net_profit']:,.2f}[/{pnl_color}]",
            f"[{pnl_color}]{p['pnl_pct']:,.2f}%[/{pnl_color}]",
            f"{p['leverage']}x",
        )
    console.print(table)


@portfolio_app.command("snapshot")
def portfolio_snapshot():
    """Save current portfolio state to database."""
    from src.portfolio.manager import save_snapshot
    sid = save_snapshot()
    console.print(f"Snapshot saved (id={sid})")


@portfolio_app.command("history")
def portfolio_history(limit: int = typer.Option(20, help="Number of snapshots")):
    """Show portfolio snapshot history."""
    from src.portfolio.manager import get_snapshot_history
    snapshots = get_snapshot_history(limit)
    if not snapshots:
        console.print("No snapshots yet.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Time")
    table.add_column("Value", justify="right")
    table.add_column("Invested", justify="right")
    table.add_column("P&L", justify="right")
    table.add_column("Cash", justify="right")
    table.add_column("Pos")

    for s in snapshots:
        table.add_row(
            s["timestamp"],
            f"${s['total_value']:,.2f}",
            f"${s['total_invested']:,.2f}",
            f"${s['total_pnl']:,.2f}",
            f"${s['cash_available']:,.2f}",
            str(s["num_positions"]),
        )
    console.print(table)


# ── Market ──────────────────────────────────────────────────────────────

@market_app.command("price")
def market_price(symbols: list[str] = typer.Argument(..., help="Symbols to check")):
    """Get current prices for instruments."""
    from src.market.data import resolve_symbol, get_rates

    instrument_ids = []
    symbol_map = {}
    for sym in symbols:
        info = resolve_symbol(sym)
        if info:
            iid = info["instrument_id"]
            instrument_ids.append(iid)
            symbol_map[iid] = sym
        else:
            console.print(f"  [red]'{sym}' not found[/red]")

    if not instrument_ids:
        return

    rates = get_rates(instrument_ids)
    table = Table(show_header=True, header_style="bold")
    table.add_column("Symbol")
    table.add_column("Bid", justify="right")
    table.add_column("Ask", justify="right")
    table.add_column("Mid", justify="right")
    table.add_column("Spread %", justify="right")

    for r in rates:
        table.add_row(
            symbol_map.get(r.instrument_id, str(r.instrument_id)),
            f"${r.bid:,.4f}",
            f"${r.ask:,.4f}",
            f"${r.mid:,.4f}",
            f"{r.spread_pct:.4f}%",
        )
    console.print(table)


@market_app.command("analyze")
def market_analyze(
    symbols: list[str] = typer.Argument(None, help="Symbols to analyze"),
    all: bool = typer.Option(False, "--all", help="Analyze all portfolio positions"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Technical analysis of instruments."""
    from src.market.data import analyze_instrument

    if all:
        from src.portfolio.manager import get_positions_with_symbols
        positions = get_positions_with_symbols()
        symbols = list({p["symbol"] for p in positions})
        if not symbols:
            console.print("No positions in portfolio.")
            return

    if not symbols:
        console.print("Specify symbols or use --all")
        raise typer.Exit(1)

    results = []
    for sym in symbols:
        console.print(f"  Analyzing {sym}...", style="dim")
        result = analyze_instrument(sym)
        results.append(result)

    if format == "json":
        console.print_json(json.dumps(results, default=str))
        return

    for r in results:
        if "error" in r and not r.get("price"):
            console.print(f"\n[red]{r.get('symbol', '?')}: {r['error']}[/red]")
            continue

        trend_color = {"BULLISH": "green", "BEARISH": "red", "NEUTRAL": "yellow"}.get(
            r.get("trend", ""), "white"
        )
        console.print(f"\n[bold]{r['symbol']}[/bold] - {r.get('name', '')}")
        console.print(f"  Price:   ${r['price']:,.4f}")
        if r.get("spread_pct") is not None:
            console.print(f"  Spread:  {r['spread_pct']:.4f}%")
        console.print(f"  Trend:   [{trend_color}]{r['trend']}[/{trend_color}]")
        console.print(f"  RSI:     {r['rsi']}")
        console.print(f"  MACD:    line={r['macd']['line']}  signal={r['macd']['signal']}  hist={r['macd']['histogram']}")
        console.print(f"  BB:      upper={r['bollinger']['upper']}  mid={r['bollinger']['middle']}  lower={r['bollinger']['lower']}")
        console.print(f"  SMA:     20={r['sma_20']}  50={r['sma_50']}")
        console.print(f"  EMA:     12={r['ema_12']}  26={r['ema_26']}")
        console.print(f"  ATR:     {r['atr']}")
        if r.get("signals"):
            console.print(f"  Signals: {', '.join(r['signals'])}")


@market_app.command("search")
def market_search(query: str = typer.Argument(..., help="Search query")):
    """Search for instruments."""
    from src.market.data import search_instrument
    results = search_instrument(query)
    if not results:
        console.print("No results found.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Symbol")
    table.add_column("Name")
    table.add_column("Type")

    for r in results:
        table.add_row(
            str(r.get("instrument_id", "")),
            r.get("symbol", ""),
            r.get("name", ""),
            str(r.get("type", "")),
        )
    console.print(table)


@market_app.command("fundamentals")
def market_fundamentals(
    symbol: str = typer.Argument(..., help="Instrument symbol"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Fundamental analysis of an instrument."""
    from src.market.fundamentals import get_instrument_fundamentals

    data = get_instrument_fundamentals(symbol)
    if "error" in data:
        console.print(f"[red]{data['error']}[/red]")
        raise typer.Exit(1)

    if format == "json":
        console.print_json(json.dumps(data, default=str))
        return

    console.print(f"\n[bold]{data['symbol']}[/bold] - {data.get('name', '')}")

    # Valuation
    v = data.get("valuation", {})
    console.print(f"\n[bold]Valuation[/bold]")
    if v.get("pe_ratio") is not None:
        console.print(f"  P/E Ratio:      {v['pe_ratio']:.2f}")
    if v.get("price_to_book") is not None:
        console.print(f"  Price/Book:     {v['price_to_book']:.2f}")
    if v.get("price_to_sales") is not None:
        console.print(f"  Price/Sales:    {v['price_to_sales']:.2f}")
    if v.get("market_cap") is not None:
        mc = v["market_cap"]
        if mc >= 1e12:
            console.print(f"  Market Cap:     ${mc/1e12:.2f}T")
        elif mc >= 1e9:
            console.print(f"  Market Cap:     ${mc/1e9:.2f}B")
        else:
            console.print(f"  Market Cap:     ${mc/1e6:.0f}M")

    # Profitability
    p = data.get("profitability", {})
    console.print(f"\n[bold]Profitability[/bold]")
    if p.get("eps") is not None:
        console.print(f"  EPS (TTM):      ${p['eps']:.2f}")
    if p.get("eps_growth_1y") is not None:
        console.print(f"  EPS Growth 1Y:  {p['eps_growth_1y']:.1f}%")
    if p.get("net_profit_margin") is not None:
        console.print(f"  Net Margin:     {p['net_profit_margin']:.1f}%")
    if p.get("return_on_equity") is not None:
        console.print(f"  ROE:            {p['return_on_equity']:.1f}%")

    # Analyst Ratings
    a = data.get("analyst_ratings", {})
    console.print(f"\n[bold]Analyst Ratings[/bold]")
    if a.get("consensus"):
        console.print(f"  Consensus:      {a['consensus']}")
    if a.get("target_price") is not None:
        upside = a.get("target_upside")
        upside_str = f" ({upside:+.1f}%)" if upside is not None else ""
        console.print(f"  Target Price:   ${a['target_price']:.2f}{upside_str}")
    if a.get("buy_count") is not None:
        console.print(f"  Buy/Hold/Sell:  {a.get('buy_count', 0)}/{a.get('hold_count', 0)}/{a.get('sell_count', 0)}")

    # Sentiment
    s = data.get("sentiment", {})
    console.print(f"\n[bold]eToro Sentiment[/bold]")
    if s.get("buy_pct") is not None:
        console.print(f"  Buy:            {s['buy_pct']:.1f}%")
    if s.get("sell_pct") is not None:
        console.print(f"  Sell:           {s['sell_pct']:.1f}%")

    # Dividends
    d = data.get("dividends", {})
    if d.get("dividend_yield") is not None:
        console.print(f"\n[bold]Dividends[/bold]")
        console.print(f"  Yield:          {d['dividend_yield']:.2f}%")
        if d.get("ex_date"):
            console.print(f"  Ex-Date:        {d['ex_date']}")

    # Earnings
    e = data.get("earnings", {})
    if e.get("next_earnings_date"):
        console.print(f"\n[bold]Earnings[/bold]")
        console.print(f"  Next Report:    {e['next_earnings_date']}")
        if e.get("days_till_earnings") is not None:
            console.print(f"  Days Until:     {e['days_till_earnings']}")

    # ESG
    esg = data.get("esg", {})
    if esg.get("total") is not None:
        console.print(f"\n[bold]ESG Scores[/bold]")
        console.print(f"  Total:          {esg['total']:.1f}")
        if esg.get("environment") is not None:
            console.print(f"  Environment:    {esg['environment']:.1f}")
        if esg.get("social") is not None:
            console.print(f"  Social:         {esg['social']:.1f}")
        if esg.get("governance") is not None:
            console.print(f"  Governance:     {esg['governance']:.1f}")


@market_app.command("news")
def market_news(
    symbol: str = typer.Argument(..., help="Instrument symbol"),
    limit: int = typer.Option(10, help="Max articles to show"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Get news, analyst grades, and price targets for an instrument."""
    from src.market.news import get_all_news

    data = get_all_news(symbol)
    if "error" in data and len(data) == 1:
        console.print(f"[red]{data['error']}[/red]")
        raise typer.Exit(1)

    if format == "json":
        console.print_json(json.dumps(data, default=str))
        return

    console.print(f"\n[bold]News: {data.get('symbol', symbol)}[/bold]")

    # Articles
    articles = data.get("articles", [])
    if articles:
        console.print(f"\n[bold]Recent Articles[/bold] ({data.get('article_count', len(articles))} total)")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Date", width=12)
        table.add_column("Source", width=15)
        table.add_column("Headline")

        for a in articles[:limit]:
            dt = (a.get("datetime") or "")[:10]
            table.add_row(dt, a.get("source", ""), a.get("headline", ""))
        console.print(table)

    # Sentiment
    sentiment = data.get("sentiment")
    if sentiment and "error" not in sentiment:
        console.print(f"\n[bold]Sentiment[/bold]")
        bull = sentiment.get("bullish_percent", 0)
        bear = sentiment.get("bearish_percent", 0)
        score = sentiment.get("company_news_score", 0)
        console.print(f"  Bullish: {bull:.0%}  Bearish: {bear:.0%}  News Score: {score:.2f}")
        console.print(f"  Articles last week: {sentiment.get('articles_in_last_week', 0)}")

    # Analyst grades
    grades = data.get("analyst_grades", [])
    if grades:
        console.print(f"\n[bold]Analyst Grades[/bold]")
        table = Table(show_header=True, header_style="bold")
        table.add_column("Date", width=12)
        table.add_column("Firm")
        table.add_column("Action")
        table.add_column("From")
        table.add_column("To")

        for g in grades[:limit]:
            table.add_row(
                (g.get("date") or "")[:10],
                g.get("firm", ""),
                g.get("action", ""),
                g.get("from_grade", ""),
                g.get("to_grade", ""),
            )
        console.print(table)

    # Price targets
    targets = data.get("price_targets")
    if targets and "error" not in targets:
        console.print(f"\n[bold]Price Target Consensus[/bold]")
        console.print(f"  Average: ${targets.get('target_average', 0):,.2f}")
        console.print(f"  Median:  ${targets.get('target_median', 0):,.2f}")
        console.print(f"  High:    ${targets.get('target_high', 0):,.2f}")
        console.print(f"  Low:     ${targets.get('target_low', 0):,.2f}")

    # Marketaux articles
    mx_articles = data.get("marketaux_articles", [])
    if mx_articles:
        console.print(f"\n[bold]Additional News (Marketaux)[/bold]")
        for a in mx_articles[:5]:
            entities_str = ", ".join(
                f"{e['symbol']}({e.get('sentiment_score', '?')})"
                for e in a.get("entities", [])
            )
            console.print(f"  - {a.get('title', '')} [{entities_str}]")

    # Show errors for APIs that failed
    for key in ("articles_error", "sentiment_error", "grades_error",
                "targets_error", "marketaux_error"):
        if key in data:
            console.print(f"\n[dim]{key}: {data[key]}[/dim]")


@market_app.command("candles")
def market_candles(
    symbol: str = typer.Argument(..., help="Instrument symbol"),
    interval: str = typer.Option("D1", help="Interval: M1,M5,M15,M30,H1,H4,D1,W1"),
    count: int = typer.Option(20, help="Number of candles"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Fetch OHLCV candles."""
    from src.market.data import resolve_symbol, get_candles, INTERVAL_MAP

    info = resolve_symbol(symbol)
    if not info:
        console.print(f"[red]'{symbol}' not found[/red]")
        raise typer.Exit(1)

    api_interval = INTERVAL_MAP.get(interval.upper(), interval)
    df = get_candles(info["instrument_id"], api_interval, count)

    if df.empty:
        console.print("No candle data.")
        return

    if format == "json":
        console.print_json(df.to_json(orient="records", date_format="iso"))
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Date")
    table.add_column("Open", justify="right")
    table.add_column("High", justify="right")
    table.add_column("Low", justify="right")
    table.add_column("Close", justify="right")
    table.add_column("Volume", justify="right")

    for _, row in df.iterrows():
        table.add_row(
            str(row["timestamp"])[:16],
            f"{row['open']:,.4f}",
            f"{row['high']:,.4f}",
            f"{row['low']:,.4f}",
            f"{row['close']:,.4f}",
            f"{row['volume']:,.0f}",
        )
    console.print(table)


# ── Trading ─────────────────────────────────────────────────────────────

@trade_app.command("buy")
def trade_buy(
    symbol: str = typer.Argument(..., help="Instrument symbol"),
    amount: float = typer.Argument(..., help="Amount in USD"),
    sl: float = typer.Option(None, help="Stop loss %"),
    tp: float = typer.Option(None, help="Take profit %"),
    leverage: float = typer.Option(1.0, help="Leverage"),
    reason: str = typer.Option(None, help="Trade reason"),
):
    """Open a BUY position."""
    from src.trading.engine import open_position
    result = open_position(symbol, amount, "BUY", sl, tp, leverage, reason)
    if result.success:
        console.print(f"[green]{result.message}[/green]")
        if result.position_id:
            console.print(f"  Position ID: {result.position_id}")
    else:
        console.print(f"[red]FAILED: {result.message}[/red]")


@trade_app.command("sell")
def trade_sell(
    symbol: str = typer.Argument(..., help="Instrument symbol"),
    amount: float = typer.Argument(..., help="Amount in USD"),
    sl: float = typer.Option(None, help="Stop loss %"),
    tp: float = typer.Option(None, help="Take profit %"),
    leverage: float = typer.Option(1.0, help="Leverage"),
    reason: str = typer.Option(None, help="Trade reason"),
):
    """Open a SELL (short) position."""
    from src.trading.engine import open_position
    result = open_position(symbol, amount, "SELL", sl, tp, leverage, reason)
    if result.success:
        console.print(f"[green]{result.message}[/green]")
        if result.position_id:
            console.print(f"  Position ID: {result.position_id}")
    else:
        console.print(f"[red]FAILED: {result.message}[/red]")


@trade_app.command("close")
def trade_close(
    position_id: int = typer.Argument(..., help="Position ID to close"),
    instrument_id: int = typer.Option(None, help="Instrument ID (auto-detected from portfolio if omitted)"),
    reason: str = typer.Option(None, help="Close reason"),
):
    """Close an open position."""
    from src.trading.engine import close_position
    result = close_position(position_id, instrument_id=instrument_id, reason=reason)
    if result.success:
        console.print(f"[green]{result.message}[/green]")
    else:
        console.print(f"[red]FAILED: {result.message}[/red]")


@trade_app.command("limit")
def trade_limit(
    direction: str = typer.Argument(..., help="BUY or SELL"),
    symbol: str = typer.Argument(..., help="Instrument symbol"),
    amount: float = typer.Argument(..., help="Amount in USD"),
    price: float = typer.Option(..., help="Limit price"),
    sl: float = typer.Option(None, help="Stop loss %"),
    tp: float = typer.Option(None, help="Take profit %"),
    leverage: float = typer.Option(1.0, help="Leverage"),
    reason: str = typer.Option(None, help="Trade reason"),
):
    """Create a limit order."""
    from src.trading.engine import create_limit_order
    result = create_limit_order(symbol, amount, price, direction.upper(), sl, tp, leverage, reason)
    if result.success:
        console.print(f"[green]{result.message}[/green]")
        if result.order_id:
            console.print(f"  Order ID: {result.order_id}")
    else:
        console.print(f"[red]FAILED: {result.message}[/red]")


@trade_app.command("check")
def trade_check(
    symbol: str = typer.Argument(..., help="Instrument symbol"),
    amount: float = typer.Argument(..., help="Amount in USD"),
    direction: str = typer.Option("BUY", help="BUY or SELL"),
    leverage: float = typer.Option(1.0, help="Leverage"),
):
    """Risk check without executing (dry run)."""
    from src.trading.risk import check_trade
    result = check_trade(symbol, amount, direction.upper(), leverage)

    if result.passed:
        console.print(f"[green]PASSED[/green]")
    else:
        console.print(f"[red]REJECTED[/red]")

    if result.violations:
        console.print("\n[red]Violations:[/red]")
        for v in result.violations:
            console.print(f"  - {v}")

    if result.warnings:
        console.print("\n[yellow]Warnings:[/yellow]")
        for w in result.warnings:
            console.print(f"  - {w}")


@trade_app.command("fees")
def trade_fees(
    symbol: str = typer.Argument(..., help="Instrument symbol"),
    amount: float = typer.Argument(..., help="Amount in USD"),
    direction: str = typer.Option("BUY", help="BUY or SELL"),
    leverage: float = typer.Option(1.0, help="Leverage"),
    format: str = typer.Option("table", help="Output format: table or json"),
):
    """Estimate trading fees for an instrument."""
    from src.trading.fees import estimate_trade_fees

    data = estimate_trade_fees(symbol, amount, direction.upper(), leverage)
    if "error" in data:
        console.print(f"[red]{data['error']}[/red]")
        raise typer.Exit(1)

    if format == "json":
        console.print_json(json.dumps(data, default=str))
        return

    console.print(f"\n[bold]Fee Estimate: {data['symbol']}[/bold]")
    console.print(f"  Amount:         ${data['amount']:,.2f}")
    console.print(f"  Direction:      {data['direction']}")
    console.print(f"  Leverage:       {data['leverage']}x")
    console.print(f"  Asset Class:    {data['asset_class']}")
    console.print(f"  Price:          ${data['price']:,.4f}" if data.get("price") else "  Price:          N/A")
    console.print(f"  Spread:         {data['spread_pct']:.4f}%")

    console.print(f"\n[bold]Costs[/bold]")
    console.print(f"  Spread Cost:    ${data['spread_cost']:,.2f}")
    if data["crypto_fee"] > 0:
        console.print(f"  Crypto Fee:     ${data['crypto_fee']:,.2f}")
    if data["overnight_daily"] > 0:
        console.print(f"  Overnight/Day:  ${data['overnight_daily']:,.2f}")
        console.print(f"  Overnight/Week: ${data['overnight_weekly']:,.2f}")
        console.print(f"  Overnight/Mo:   ${data['overnight_monthly']:,.2f}")

    console.print(f"\n[bold]Summary[/bold]")
    console.print(f"  Entry Cost:     ${data['total_entry_cost']:,.2f}")
    console.print(f"  1-Month Cost:   ${data['total_1month_cost']:,.2f}")
    console.print(f"  Cost %:         {data['cost_pct']:.4f}%")


# ── History ─────────────────────────────────────────────────────────────

@history_app.command("trades")
def history_trades(limit: int = typer.Option(50, help="Number of records")):
    """Show trade history."""
    from src.storage.repositories import TradeLogRepo
    repo = TradeLogRepo()
    trades = repo.get_trades(limit)
    if not trades:
        console.print("No trade history.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Time")
    table.add_column("Symbol")
    table.add_column("Dir")
    table.add_column("Amount", justify="right")
    table.add_column("Status")
    table.add_column("Reason")

    for t in trades:
        status_color = {"executed": "green", "rejected": "red", "error": "red"}.get(
            t["status"], "white"
        )
        table.add_row(
            t["timestamp"],
            t["symbol"],
            t["direction"],
            f"${t['amount']:,.2f}",
            f"[{status_color}]{t['status']}[/{status_color}]",
            (t.get("reason") or "")[:40],
        )
    console.print(table)


@history_app.command("runs")
def history_runs(limit: int = typer.Option(20, help="Number of records")):
    """Show portfolio snapshot history (analysis runs)."""
    from src.storage.repositories import PortfolioRepo
    repo = PortfolioRepo()
    snaps = repo.get_snapshots(limit)
    if not snaps:
        console.print("No snapshots.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("Time")
    table.add_column("Value", justify="right")
    table.add_column("P&L", justify="right")
    table.add_column("Positions")

    for s in snaps:
        table.add_row(
            s["timestamp"],
            f"${s['total_value']:,.2f}",
            f"${s['total_pnl']:,.2f}",
            str(s["num_positions"]),
        )
    console.print(table)


# ── Memory ──────────────────────────────────────────────────────────────

@memory_app.command("list")
def memory_list(limit: int = typer.Option(50, help="Number of records")):
    """List all memories."""
    from src.storage.repositories import MemoryRepo
    repo = MemoryRepo()
    memories = repo.list_all(limit)
    if not memories:
        console.print("No memories stored.")
        return

    table = Table(show_header=True, header_style="bold")
    table.add_column("ID")
    table.add_column("Time")
    table.add_column("Category")
    table.add_column("Content")

    for m in memories:
        table.add_row(
            str(m["id"]),
            m["timestamp"],
            m["category"],
            m["content"][:80],
        )
    console.print(table)


@memory_app.command("add")
def memory_add(
    category: str = typer.Argument(..., help="Category: lesson, pattern, market_note"),
    content: str = typer.Argument(..., help="Memory content"),
    relevance: float = typer.Option(1.0, help="Relevance score"),
):
    """Add a new memory."""
    from src.storage.repositories import MemoryRepo
    repo = MemoryRepo()
    mid = repo.add(category, content, relevance)
    console.print(f"Memory saved (id={mid})")


@memory_app.command("search")
def memory_search(query: str = typer.Argument(..., help="Search query")):
    """Search memories."""
    from src.storage.repositories import MemoryRepo
    repo = MemoryRepo()
    results = repo.search(query)
    if not results:
        console.print("No matching memories.")
        return

    for m in results:
        console.print(f"  [{m['category']}] {m['content']}")


@memory_app.command("delete")
def memory_delete(memory_id: int = typer.Argument(..., help="Memory ID to delete")):
    """Delete a memory."""
    from src.storage.repositories import MemoryRepo
    repo = MemoryRepo()
    repo.delete(memory_id)
    console.print(f"Memory {memory_id} deleted.")


# ── Watchlist ───────────────────────────────────────────────────────────

@watchlist_app.callback(invoke_without_command=True)
def watchlist_show(ctx: typer.Context):
    if ctx.invoked_subcommand is not None:
        return
    from src.portfolio.manager import get_watchlists
    wls = get_watchlists()
    if not wls:
        console.print("No watchlists found.")
        return

    for wl in wls:
        name = wl.get("name", wl.get("Name", wl.get("WatchlistName", "Unnamed")))
        items = wl.get("items", wl.get("Items", wl.get("InstrumentIDs", [])))
        console.print(f"\n[bold]{name}[/bold] ({len(items)} items)")
        for item in items[:20]:
            if isinstance(item, dict):
                sym = (item.get("market", {}).get("symbolName", "")
                       or item.get("SymbolFull", "")
                       or item.get("itemId", ""))
                console.print(f"  - {sym}")
            else:
                console.print(f"  - ID: {item}")


# ── Config ──────────────────────────────────────────────────────────────

@config_app.command("show")
def config_show():
    """Show current configuration."""
    from config import settings
    console.print(f"\n[bold]Configuration[/bold]")
    console.print(f"  Trading Mode:   {settings.trading_mode}")
    console.print(f"  API Base:       {settings.api_base}")
    console.print(f"  DB Path:        {settings.db_path}")
    console.print(f"\n[bold]Risk Limits[/bold]")
    console.print(f"  Max position:       {settings.risk.max_position_pct:.0%}")
    console.print(f"  Max exposure:       {settings.risk.max_total_exposure_pct:.0%}")
    console.print(f"  Max daily loss:     {settings.risk.max_daily_loss_pct:.0%}")
    console.print(f"  Max single trade:   ${settings.risk.max_single_trade_usd:,.0f}")
    console.print(f"  Min trade:          ${settings.risk.min_trade_usd:,.0f}")
    console.print(f"  Max open positions: {settings.risk.max_open_positions}")
    console.print(f"  Default SL:         {settings.risk.default_stop_loss_pct}%")
    console.print(f"  Default TP:         {settings.risk.default_take_profit_pct}%")
    console.print(f"  Max leverage:       {settings.risk.max_leverage}x")


@config_app.command("set")
def config_set(
    key: str = typer.Argument(..., help="Config key (e.g. trading_mode)"),
    value: str = typer.Argument(..., help="New value"),
):
    """Update a configuration value in .env file."""
    from pathlib import Path
    env_path = Path(__file__).parent / ".env"
    if not env_path.exists():
        console.print("[red].env file not found[/red]")
        raise typer.Exit(1)

    key_upper = key.upper()
    if key_upper == "TRADING_MODE":
        if value not in ("demo", "real"):
            console.print("[red]trading_mode must be 'demo' or 'real'[/red]")
            raise typer.Exit(1)

    lines = env_path.read_text().splitlines()
    found = False
    for i, line in enumerate(lines):
        if line.strip().startswith(f"{key_upper}"):
            lines[i] = f"{key_upper} = {value}"
            found = True
            break

    if not found:
        lines.append(f"{key_upper} = {value}")

    env_path.write_text("\n".join(lines) + "\n")
    console.print(f"Set {key_upper} = {value}")


# ── Init DB on startup ─────────────────────────────────────────────────

@app.callback()
def main_callback(
    mode: Optional[str] = typer.Option(None, "--mode", help="Trading mode: demo or real"),
):
    if mode is not None and mode not in ("demo", "real"):
        console.print("[red]--mode must be 'demo' or 'real'[/red]")
        raise typer.Exit(1)
    init_db()


if __name__ == "__main__":
    app()
