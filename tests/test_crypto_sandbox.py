import pytest

from broker import CryptoSandboxBroker, Order, get_broker


@pytest.mark.asyncio
async def test_crypto_sandbox_is_paper_only_and_emits_receipt_markers():
    broker = get_broker("crypto-sandbox")
    assert isinstance(broker, CryptoSandboxBroker)
    assert broker.is_paper_only() is True
    assert await broker.connect() is True

    broker.set_market_price("MOM8", 0.50)
    result = await broker.submit_order(
        Order(symbol="MOM8", qty=10, side="buy", asset_class="crypto")
    )

    assert result["status"] == "filled"
    assert result["real_money"] is False
    assert result["wallet_mode"] == "sandbox"
    assert result["continuity_cookie"].startswith("crypto-sandbox:")
    assert len(result["continuity_fingerprint"]) == 64

    summary = await broker.get_account_summary()
    assert summary["real_money"] is False
    assert summary["wallet_mode"] == "sandbox"
    assert summary["cash"] == pytest.approx(95.0)


@pytest.mark.asyncio
async def test_crypto_sandbox_rejects_non_crypto_orders():
    broker = get_broker("crypto-sandbox")
    await broker.connect()

    result = await broker.submit_order(
        Order(symbol="AAPL", qty=1, side="buy", asset_class="stocks")
    )

    assert result["status"] == "rejected"
    assert "crypto" in result["reason"]


def test_crypto_sandbox_cannot_accept_credentials_or_live_mode():
    with pytest.raises(ValueError, match="credentials are not accepted"):
        get_broker("crypto-sandbox", credentials={"secret": "not-used"})

    with pytest.raises(ValueError, match="Live broker execution is disabled"):
        get_broker("crypto-sandbox", paper_only=False)
