import pytest
from unittest.mock import patch, MagicMock
import httpx

import src.market.news as news_mod


@pytest.fixture(autouse=True)
def reset_clients():
    """Reset module-level singleton clients between tests."""
    news_mod._finnhub = None
    news_mod._marketaux = None
    news_mod._fmp = None
    yield
    news_mod._finnhub = None
    news_mod._marketaux = None
    news_mod._fmp = None


def _mock_response(json_data, status_code=200):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.json.return_value = json_data
    resp.raise_for_status.return_value = None
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            "error", request=MagicMock(), response=resp
        )
    return resp


# ── Skip when key is empty ─────────────────────────────────────────


class TestSkipNoKey:
    @patch.object(news_mod.settings, "finnhub_api_key", "")
    def test_company_news_skip(self):
        result = news_mod.get_company_news("AAPL")
        assert "error" in result
        assert "not configured" in result["error"]

    @patch.object(news_mod.settings, "finnhub_api_key", "")
    def test_news_sentiment_skip(self):
        result = news_mod.get_news_sentiment("AAPL")
        assert "error" in result

    @patch.object(news_mod.settings, "finnhub_api_key", "")
    def test_market_news_skip(self):
        result = news_mod.get_market_news()
        assert "error" in result

    @patch.object(news_mod.settings, "fmp_api_key", "")
    def test_analyst_grades_skip(self):
        result = news_mod.get_analyst_grades("AAPL")
        assert "error" in result

    @patch.object(news_mod.settings, "fmp_api_key", "")
    def test_price_target_skip(self):
        result = news_mod.get_price_target_consensus("AAPL")
        assert "error" in result

    @patch.object(news_mod.settings, "marketaux_api_key", "")
    def test_multi_news_skip(self):
        result = news_mod.get_multi_news(["AAPL"])
        assert "error" in result


# ── Successful responses ───────────────────────────────────────────


class TestCompanyNews:
    @patch.object(news_mod.settings, "finnhub_api_key", "test-key")
    def test_success(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {
                "headline": "Apple releases new product",
                "summary": "Summary here",
                "source": "Reuters",
                "url": "https://example.com/1",
                "datetime": 1700000000,
                "category": "company",
            }
        ])
        news_mod._finnhub = mock_client

        result = news_mod.get_company_news("AAPL", days=7)
        assert "error" not in result
        assert result["symbol"] == "AAPL"
        assert result["count"] == 1
        assert len(result["articles"]) == 1
        assert result["articles"][0]["headline"] == "Apple releases new product"
        assert result["articles"][0]["source"] == "Reuters"


class TestNewsSentiment:
    @patch.object(news_mod.settings, "finnhub_api_key", "test-key")
    def test_success(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response({
            "buzz": {"articlesInLastWeek": 50, "buzz": 1.5, "weeklyAverage": 40},
            "sentiment": {"bullishPercent": 0.7, "bearishPercent": 0.3},
            "companyNewsScore": 0.8,
            "sectorAverageBullishPercent": 0.55,
            "sectorAverageNewsScore": 0.6,
        })
        news_mod._finnhub = mock_client

        result = news_mod.get_news_sentiment("AAPL")
        assert "error" not in result
        assert result["bullish_percent"] == 0.7
        assert result["bearish_percent"] == 0.3
        assert result["company_news_score"] == 0.8


class TestMarketNews:
    @patch.object(news_mod.settings, "finnhub_api_key", "test-key")
    def test_success(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {
                "headline": "Market rallies",
                "summary": "S&P 500 up",
                "source": "CNBC",
                "url": "https://example.com/2",
                "datetime": 1700000000,
                "category": "general",
            },
            {
                "headline": "Fed holds rates",
                "summary": "Rates unchanged",
                "source": "Bloomberg",
                "url": "https://example.com/3",
                "datetime": 1700001000,
                "category": "general",
            },
        ])
        news_mod._finnhub = mock_client

        result = news_mod.get_market_news(limit=5)
        assert "error" not in result
        assert result["count"] == 2
        assert len(result["articles"]) == 2


class TestAnalystGrades:
    @patch.object(news_mod.settings, "fmp_api_key", "test-key")
    def test_success(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([
            {
                "publishedDate": "2026-02-15",
                "gradingCompany": "Morgan Stanley",
                "action": "upgrade",
                "previousGrade": "Equal-Weight",
                "newGrade": "Overweight",
            }
        ])
        news_mod._fmp = mock_client

        result = news_mod.get_analyst_grades("AAPL", limit=10)
        assert "error" not in result
        assert result["count"] == 1
        assert result["grades"][0]["firm"] == "Morgan Stanley"
        assert result["grades"][0]["to_grade"] == "Overweight"


class TestPriceTargetConsensus:
    @patch.object(news_mod.settings, "fmp_api_key", "test-key")
    def test_success(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response([{
            "targetHigh": 250.0,
            "targetLow": 180.0,
            "targetMedian": 220.0,
            "targetConsensus": 215.0,
        }])
        news_mod._fmp = mock_client

        result = news_mod.get_price_target_consensus("AAPL")
        assert "error" not in result
        assert result["target_high"] == 250.0
        assert result["target_low"] == 180.0
        assert result["target_median"] == 220.0
        assert result["target_average"] == 215.0


class TestMultiNews:
    @patch.object(news_mod.settings, "marketaux_api_key", "test-key")
    def test_success(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response({
            "data": [
                {
                    "title": "Tech stocks rise",
                    "description": "AAPL and MSFT lead gains",
                    "source": "MarketWatch",
                    "url": "https://example.com/4",
                    "published_at": "2026-02-16T10:00:00Z",
                    "entities": [
                        {"symbol": "AAPL", "sentiment_score": 0.8, "type": "equity"},
                    ],
                }
            ]
        })
        news_mod._marketaux = mock_client

        result = news_mod.get_multi_news(["AAPL", "MSFT"], limit=20)
        assert "error" not in result
        assert result["count"] == 1
        assert result["articles"][0]["entities"][0]["symbol"] == "AAPL"
        assert result["articles"][0]["entities"][0]["sentiment_score"] == 0.8


# ── Error handling ─────────────────────────────────────────────────


class TestErrorHandling:
    @patch.object(news_mod.settings, "finnhub_api_key", "test-key")
    def test_company_news_http_error(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response({}, status_code=429)
        news_mod._finnhub = mock_client

        result = news_mod.get_company_news("AAPL")
        assert "error" in result

    @patch.object(news_mod.settings, "fmp_api_key", "test-key")
    def test_analyst_grades_http_error(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response({}, status_code=500)
        news_mod._fmp = mock_client

        result = news_mod.get_analyst_grades("AAPL")
        assert "error" in result

    @patch.object(news_mod.settings, "marketaux_api_key", "test-key")
    def test_multi_news_http_error(self):
        mock_client = MagicMock(spec=httpx.Client)
        mock_client.get.return_value = _mock_response({}, status_code=403)
        news_mod._marketaux = mock_client

        result = news_mod.get_multi_news(["AAPL"])
        assert "error" in result


# ── get_all_news combined ──────────────────────────────────────────


class TestGetAllNews:
    @patch.object(news_mod.settings, "finnhub_api_key", "")
    @patch.object(news_mod.settings, "marketaux_api_key", "")
    @patch.object(news_mod.settings, "fmp_api_key", "")
    def test_no_keys_configured(self):
        result = news_mod.get_all_news("AAPL")
        assert "error" in result
        assert "No news API keys configured" in result["error"]

    @patch.object(news_mod.settings, "finnhub_api_key", "test-key")
    @patch.object(news_mod.settings, "marketaux_api_key", "")
    @patch.object(news_mod.settings, "fmp_api_key", "test-key")
    def test_partial_keys(self):
        # Mock Finnhub
        mock_finnhub = MagicMock(spec=httpx.Client)
        mock_finnhub.get.return_value = _mock_response([
            {"headline": "News", "summary": "S", "source": "R",
             "url": "u", "datetime": 1700000000, "category": "c"}
        ])
        news_mod._finnhub = mock_finnhub

        # Mock FMP
        mock_fmp = MagicMock(spec=httpx.Client)
        mock_fmp.get.return_value = _mock_response([])
        news_mod._fmp = mock_fmp

        result = news_mod.get_all_news("AAPL")
        assert result["symbol"] == "AAPL"
        # Should have articles from Finnhub
        assert "articles" in result or "articles_error" in result
        # Should NOT have marketaux (key is empty)
        assert "marketaux_articles" not in result
        assert "marketaux_error" not in result
