from datetime import datetime, timedelta, timezone

import pytest

from backend.server import observe_approved_markets, run_paper_dry_run
from market.observation import observe_market
from market.providers import YahooPublicChartProvider


class ReadOnlyQuoteProvider:
    source_name = "injected-read-only-provider"
    source_classification = "test-observation"
    max_age_seconds = 5 * 60

    def __init__(self, price: float):
        self.price = price

    async def get_market_data(self, symbol: str) -> dict:
        return {
            "symbol": symbol,
            "price": self.price,
            "bid": self.price - 0.1,
            "ask": self.price + 0.1,
            "timestamp": datetime.now(timezone.utc),
        }


class StaleQuoteProvider(ReadOnlyQuoteProvider):
    max_age_seconds = 60

    async def get_market_data(self, symbol: str) -> dict:
        data = await super().get_market_data(symbol)
        data["timestamp"] = datetime.now(timezone.utc) - timedelta(minutes=10)
        return data


@pytest.mark.asyncio
async def test_approved_market_universe_is_observed_read_only():
    result = await observe_approved_markets(ReadOnlyQuoteProvider(120.0))

    assert result["status"] == "ok"
    assert result["approved_symbols"] == ["AAPL", "MSFT", "VTI"]
    assert [market["symbol"] for market in result["markets"]] == ["AAPL", "MSFT", "VTI"]
    assert all(market["price"] == 120.0 for market in result["markets"])
    assert all(market["read_only"] is True for market in result["markets"])
    assert all(market["authority"] == "none" for market in result["markets"])
    assert all(market["source"] == "injected-read-only-provider" for market in result["markets"])
    assert all(market["freshness"] == "fresh" for market in result["markets"])
    assert all(len(market["fingerprint"]) == 64 for market in result["markets"])
    assert all(market["continuity_cookie"].startswith("sw-market-v1:") for market in result["markets"])
    assert result["live_execution"] is False
    assert result["truth"] == "watching markets and continuity markers do not grant execution authority"


@pytest.mark.asyncio
async def test_backend_uses_observed_price_for_evaluation_and_paper_fill(tmp_path):
    result = await run_paper_dry_run(
        "AAPL",
        0.04,
        "buy",
        str(tmp_path / "audit.log"),
        market_provider=ReadOnlyQuoteProvider(120.0),
    )
    assert result["status"] == "executed"
    assert result["market_observation"]["price"] == 120.0
    assert result["market_observation"]["read_only"] is True
    assert result["evaluation"]["estimated_cost"] == pytest.approx(4.8)
    assert result["evaluation"]["observed_price"] == 120.0
    assert result["evaluation"]["symbol_scope"] == "observable-market"
    assert result["execution"]["filled_price"] == 120.0
    assert result["execution"]["fill_classification"] == "SIMULATED_AT_OBSERVED_PRICE"
    assert result["account_after"]["cash"] == pytest.approx(9995.2)
    assert result["continuity"]["input_market_fingerprint"] == result["market_observation"]["fingerprint"]
    assert result["continuity"]["input_market_cookie"] == result["market_observation"]["continuity_cookie"]
    assert len(result["continuity"]["decision_fingerprint"]) == 64
    assert result["continuity"]["decision_cookie"].startswith("sw-decision-v1:")
    assert len(result["continuity"]["outcome_fingerprint"]) == 64
    assert result["continuity"]["outcome_cookie"].startswith("sw-outcome-v1:")
    assert result["continuity"]["authority"] == "none"
    assert result["approved_symbols"] == ["AAPL", "MSFT", "VTI"]
    assert result["broker"] == "mock"
    assert result["live_execution"] is False


@pytest.mark.asyncio
async def test_observable_market_scope_allows_non_featured_symbol_in_paper_mode(tmp_path):
    result = await run_paper_dry_run(
        "IBM",
        0.01,
        "buy",
        str(tmp_path / "audit.log"),
        market_provider=ReadOnlyQuoteProvider(120.0),
    )
    assert result["status"] == "executed"
    assert result["order"]["symbol"] == "IBM"
    assert "IBM" not in result["approved_symbols"]
    assert result["evaluation"]["symbol_scope"] == "observable-market"
    assert result["market_observation"]["symbol"] == "IBM"
    assert result["live_execution"] is False
    assert result["broker"] == "mock"


@pytest.mark.asyncio
async def test_observed_price_can_block_order_even_when_old_assumption_would_pass(tmp_path):
    result = await run_paper_dry_run(
        "AAPL",
        0.04,
        "buy",
        str(tmp_path / "audit.log"),
        market_provider=ReadOnlyQuoteProvider(130.0),
    )
    assert result["status"] == "blocked"
    assert result["stage"] == "evaluator"
    assert "exceeds ceiling $5.00" in result["reason"]
    assert result["evaluation"]["estimated_cost"] == pytest.approx(5.2)
    assert result["continuity"]["decision_cookie"].startswith("sw-decision-v1:")
    assert "outcome_cookie" not in result["continuity"]
    assert "execution" not in result


@pytest.mark.asyncio
async def test_stale_observation_fails_closed():
    with pytest.raises(ValueError, match="is stale"):
        await observe_market(StaleQuoteProvider(120.0), "AAPL")


@pytest.mark.asyncio
async def test_yahoo_public_provider_parses_latest_usable_close():
    timestamp = int(datetime.now(timezone.utc).timestamp())

    def fake_fetch(url: str) -> dict:
        assert "query1.finance.yahoo.com" in url
        assert "/AAPL?" in url
        return {
            "chart": {
                "result": [
                    {
                        "meta": {"symbol": "AAPL", "currency": "USD"},
                        "timestamp": [timestamp - 86400, timestamp],
                        "indicators": {"quote": [{"close": [118.5, 121.25]}]},
                    }
                ],
                "error": None,
            }
        }

    provider = YahooPublicChartProvider(fetch_json=fake_fetch)
    data = await provider.get_market_data("AAPL")
    assert data["symbol"] == "AAPL"
    assert data["price"] == pytest.approx(121.25)
    assert data["source_name"] == "yahoo-public-chart"
    assert data["source_classification"] == "external-public-delayed"


@pytest.mark.asyncio
async def test_default_ci_observation_stays_paper_only(tmp_path, monkeypatch):
    monkeypatch.setenv("SLEEPWEALTH_MARKET_SOURCE", "mock")
    market_result = await observe_approved_markets()
    assert market_result["approved_symbols"] == ["AAPL", "MSFT", "VTI"]
    assert all(market["source"] == "mock-market-observation" for market in market_result["markets"])
    assert all(market["source_classification"] == "synthetic-fixture" for market in market_result["markets"])

    result = await run_paper_dry_run("AAPL", 0.01, "buy", str(tmp_path / "audit.log"))
    assert result["status"] == "executed"
    assert result["market_observation"]["source"] == "mock-market-observation"
    assert result["market_observation"]["read_only"] is True
    assert result["execution"]["filled_price"] == 100.0
    assert result["truth"] == "read-only market observation; paper simulation only; no real money moved"
