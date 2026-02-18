"""News aggregation from Finnhub, Marketaux, and FMP APIs."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import httpx

from config import settings


# Lazy singleton clients
_finnhub: httpx.Client | None = None
_marketaux: httpx.Client | None = None
_fmp: httpx.Client | None = None


def _get_finnhub() -> httpx.Client | None:
    global _finnhub
    if not settings.finnhub_api_key:
        return None
    if _finnhub is None:
        _finnhub = httpx.Client(
            base_url="https://finnhub.io/api/v1",
            params={"token": settings.finnhub_api_key},
            timeout=15.0,
        )
    return _finnhub


def _get_marketaux() -> httpx.Client | None:
    global _marketaux
    if not settings.marketaux_api_key:
        return None
    if _marketaux is None:
        _marketaux = httpx.Client(
            base_url="https://api.marketaux.com/v1",
            params={"api_token": settings.marketaux_api_key},
            timeout=15.0,
        )
    return _marketaux


def _get_fmp() -> httpx.Client | None:
    global _fmp
    if not settings.fmp_api_key:
        return None
    if _fmp is None:
        _fmp = httpx.Client(
            base_url="https://financialmodelingprep.com/api/v3",
            params={"apikey": settings.fmp_api_key},
            timeout=15.0,
        )
    return _fmp


# ── Finnhub ────────────────────────────────────────────────────────────


def get_company_news(symbol: str, days: int = 7) -> dict[str, Any]:
    """Get recent company news articles from Finnhub."""
    client = _get_finnhub()
    if client is None:
        return {"error": "FINNHUB_API_KEY not configured"}

    try:
        to_date = datetime.now().strftime("%Y-%m-%d")
        from_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")
        resp = client.get(
            "/company-news",
            params={"symbol": symbol, "from": from_date, "to": to_date},
        )
        resp.raise_for_status()
        articles = resp.json()
        return {
            "symbol": symbol,
            "count": len(articles),
            "articles": [
                {
                    "headline": a.get("headline", ""),
                    "summary": a.get("summary", ""),
                    "source": a.get("source", ""),
                    "url": a.get("url", ""),
                    "datetime": datetime.fromtimestamp(a["datetime"]).isoformat()
                    if a.get("datetime")
                    else None,
                    "category": a.get("category", ""),
                }
                for a in articles[:50]
            ],
        }
    except Exception as e:
        return {"error": f"Finnhub company news failed: {e}"}


def get_news_sentiment(symbol: str) -> dict[str, Any]:
    """Get news sentiment data from Finnhub."""
    client = _get_finnhub()
    if client is None:
        return {"error": "FINNHUB_API_KEY not configured"}

    try:
        resp = client.get("/news-sentiment", params={"symbol": symbol})
        resp.raise_for_status()
        data = resp.json()
        buzz = data.get("buzz", {})
        sentiment = data.get("sentiment", {})
        return {
            "symbol": symbol,
            "articles_in_last_week": buzz.get("articlesInLastWeek", 0),
            "buzz_score": buzz.get("buzz", 0),
            "weekly_average": buzz.get("weeklyAverage", 0),
            "bullish_percent": sentiment.get("bullishPercent", 0),
            "bearish_percent": sentiment.get("bearishPercent", 0),
            "company_news_score": data.get("companyNewsScore", 0),
            "sector_average_bullish": data.get("sectorAverageBullishPercent", 0),
            "sector_average_news_score": data.get("sectorAverageNewsScore", 0),
        }
    except Exception as e:
        return {"error": f"Finnhub sentiment failed: {e}"}


def get_market_news(limit: int = 20) -> dict[str, Any]:
    """Get general market news from Finnhub."""
    client = _get_finnhub()
    if client is None:
        return {"error": "FINNHUB_API_KEY not configured"}

    try:
        resp = client.get("/news", params={"category": "general"})
        resp.raise_for_status()
        articles = resp.json()
        return {
            "count": min(len(articles), limit),
            "articles": [
                {
                    "headline": a.get("headline", ""),
                    "summary": a.get("summary", ""),
                    "source": a.get("source", ""),
                    "url": a.get("url", ""),
                    "datetime": datetime.fromtimestamp(a["datetime"]).isoformat()
                    if a.get("datetime")
                    else None,
                    "category": a.get("category", ""),
                }
                for a in articles[:limit]
            ],
        }
    except Exception as e:
        return {"error": f"Finnhub market news failed: {e}"}


# ── FMP (Financial Modeling Prep) ──────────────────────────────────────


def get_analyst_grades(symbol: str, limit: int = 10) -> dict[str, Any]:
    """Get recent analyst upgrades/downgrades from FMP."""
    client = _get_fmp()
    if client is None:
        return {"error": "FMP_API_KEY not configured"}

    try:
        resp = client.get(f"/upgrades-downgrades", params={"symbol": symbol})
        resp.raise_for_status()
        grades = resp.json()
        return {
            "symbol": symbol,
            "count": min(len(grades), limit),
            "grades": [
                {
                    "date": g.get("publishedDate", g.get("date", "")),
                    "firm": g.get("gradingCompany", ""),
                    "action": g.get("action", g.get("newGrade", "")),
                    "from_grade": g.get("previousGrade", ""),
                    "to_grade": g.get("newGrade", ""),
                }
                for g in grades[:limit]
            ],
        }
    except Exception as e:
        return {"error": f"FMP analyst grades failed: {e}"}


def get_price_target_consensus(symbol: str) -> dict[str, Any]:
    """Get analyst price target consensus from FMP."""
    client = _get_fmp()
    if client is None:
        return {"error": "FMP_API_KEY not configured"}

    try:
        resp = client.get(f"/price-target-consensus", params={"symbol": symbol})
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, list) and data:
            data = data[0]
        if not data:
            return {"symbol": symbol, "error": "No price target data"}
        return {
            "symbol": symbol,
            "target_high": data.get("targetHigh"),
            "target_low": data.get("targetLow"),
            "target_median": data.get("targetMedian"),
            "target_average": data.get("targetConsensus", data.get("targetAverage")),
        }
    except Exception as e:
        return {"error": f"FMP price targets failed: {e}"}


# ── Marketaux ──────────────────────────────────────────────────────────


def get_multi_news(symbols: list[str], limit: int = 20) -> dict[str, Any]:
    """Get news for multiple symbols from Marketaux with entity sentiment."""
    client = _get_marketaux()
    if client is None:
        return {"error": "MARKETAUX_API_KEY not configured"}

    try:
        resp = client.get(
            "/news/all",
            params={"symbols": ",".join(symbols), "limit": limit, "language": "en"},
        )
        resp.raise_for_status()
        data = resp.json()
        articles = data.get("data", [])
        return {
            "symbols": symbols,
            "count": len(articles),
            "articles": [
                {
                    "title": a.get("title", ""),
                    "description": a.get("description", ""),
                    "source": a.get("source", ""),
                    "url": a.get("url", ""),
                    "published_at": a.get("published_at", ""),
                    "entities": [
                        {
                            "symbol": e.get("symbol", ""),
                            "sentiment_score": e.get("sentiment_score"),
                            "type": e.get("type", ""),
                        }
                        for e in a.get("entities", [])
                    ],
                }
                for a in articles
            ],
        }
    except Exception as e:
        return {"error": f"Marketaux news failed: {e}"}


# ── Combined ───────────────────────────────────────────────────────────


def get_all_news(symbol: str, days: int = 7) -> dict[str, Any]:
    """Get combined news from all configured sources.

    Returns articles, sentiment, analyst grades, and price targets.
    Skips any API whose key is not configured.
    """
    has_any_key = any([
        settings.finnhub_api_key,
        settings.marketaux_api_key,
        settings.fmp_api_key,
    ])
    if not has_any_key:
        return {
            "error": (
                "No news API keys configured. "
                "Set FINNHUB_API_KEY, MARKETAUX_API_KEY, or FMP_API_KEY in .env"
            )
        }

    result: dict[str, Any] = {"symbol": symbol}

    # Finnhub: company news + sentiment
    if settings.finnhub_api_key:
        news = get_company_news(symbol, days)
        if "error" not in news:
            result["articles"] = news.get("articles", [])
            result["article_count"] = news.get("count", 0)
        else:
            result["articles_error"] = news["error"]

        sentiment = get_news_sentiment(symbol)
        if "error" not in sentiment:
            result["sentiment"] = sentiment
        else:
            result["sentiment_error"] = sentiment["error"]

    # FMP: analyst grades + price targets
    if settings.fmp_api_key:
        grades = get_analyst_grades(symbol)
        if "error" not in grades:
            result["analyst_grades"] = grades.get("grades", [])
        else:
            result["grades_error"] = grades["error"]

        targets = get_price_target_consensus(symbol)
        if "error" not in targets:
            result["price_targets"] = targets
        else:
            result["targets_error"] = targets["error"]

    # Marketaux: multi-symbol news with entity sentiment
    if settings.marketaux_api_key:
        multi = get_multi_news([symbol])
        if "error" not in multi:
            result["marketaux_articles"] = multi.get("articles", [])
        else:
            result["marketaux_error"] = multi["error"]

    return result
