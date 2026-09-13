import pytest

from backend.server import CRYPTO_DEFAULT_QTY, DASHBOARD_HTML, STOCK_DEFAULT_QTY, run_paper_dry_run
from broker.factory import get_broker
from market import CRYPTO_LANE, LaneBoundFixtureProvider


def test_crypto_ui_switches_to_safe_fractional_paper_quantity():
    assert STOCK_DEFAULT_QTY == 0.01
    assert CRYPTO_DEFAULT_QTY == 0.00001
    assert "const qtyInput=document.getElementById('qty');" in DASHBOARD_HTML
    assert "qtyInput.value=crypto?'0.00001':'0.01';" in DASHBOARD_HTML


@pytest.mark.asyncio
async def test_crypto_default_executes_with_production_shaped_btc_price(tmp_path):
    provider = get_broker("mock", paper_only=True)
    assert await provider.connect() is True
    provider.set_market_price("BTC-USD", 120_000.0)

    result = await run_paper_dry_run(
        symbol="BTC-USD",
        qty=CRYPTO_DEFAULT_QTY,
        side="buy",
        audit_log_path=str(tmp_path / "crypto-default-audit.log"),
        market_provider=LaneBoundFixtureProvider(provider, CRYPTO_LANE),
        lane=CRYPTO_LANE,
    )

    assert result["status"] == "executed"
    assert result["lane"] == CRYPTO_LANE
    assert result["order"]["qty"] == CRYPTO_DEFAULT_QTY
    assert result["market_observation"]["price"] == 120_000.0
    assert result["live_execution"] is False
    assert result["execution"]["fill_classification"] == "SIMULATED_AT_OBSERVED_PRICE"
