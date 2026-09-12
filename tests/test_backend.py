from datetime import datetime, timezone

import pytest

from backend.server import run_paper_dry_run


class ReadOnlyQuoteProvider:
    def __init__(self, price: float): self.price = price
    async def get_market_data(self, symbol: str) -> dict:
        return {"symbol":symbol,"price":self.price,"bid":self.price-0.1,"ask":self.price+0.1,"timestamp":datetime.now(timezone.utc)}


@pytest.mark.asyncio
async def test_backend_uses_observed_price_for_evaluation(tmp_path):
    result = await run_paper_dry_run("AAPL",0.04,"buy",str(tmp_path/"audit.log"),market_provider=ReadOnlyQuoteProvider(120.0))
    assert result["status"] == "executed"
    assert result["market_observation"]["price"] == 120.0
    assert result["market_observation"]["read_only"] is True
    assert result["evaluation"]["estimated_cost"] == pytest.approx(4.8)
    assert result["evaluation"]["observed_price"] == 120.0
    assert result["broker"] == "mock"
    assert result["live_execution"] is False


@pytest.mark.asyncio
async def test_observed_price_can_block_order_even_when_old_assumption_would_pass(tmp_path):
    result = await run_paper_dry_run("AAPL",0.04,"buy",str(tmp_path/"audit.log"),market_provider=ReadOnlyQuoteProvider(130.0))
    assert result["status"] == "blocked"
    assert result["stage"] == "evaluator"
    assert "exceeds ceiling $5.00" in result["reason"]
    assert result["evaluation"]["estimated_cost"] == pytest.approx(5.2)
    assert "execution" not in result


@pytest.mark.asyncio
async def test_default_ci_observation_stays_paper_only(tmp_path):
    result = await run_paper_dry_run("AAPL",0.04,"buy",str(tmp_path/"audit.log"))
    assert result["status"] == "executed"
    assert result["market_observation"]["source"] == "mock-market-observation"
    assert result["market_observation"]["read_only"] is True
    assert result["truth"] == "read-only market observation; paper simulation only; no real money moved"
