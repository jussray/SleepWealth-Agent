import pytest

from broker import CryptoSandboxBroker, Order, get_broker


@pytest.mark.asyncio
async def test_crypto_sandbox_is_paper_only_and_emits_receipt_markers():
    broker = CryptoSandboxBroker()
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
    broker = CryptoSandboxBroker()
    await broker.connect()

    result = await broker.submit_order(
        Order(symbol="AAPL", qty=1, side="buy", asset_class="stocks")
    )

    assert result["status"] == "rejected"
    assert "crypto" in result["reason"]


@pytest.mark.asyncio
async def test_crypto_cancel_all_marks_only_working_orders_cancelled_and_preserves_evidence():
    broker = CryptoSandboxBroker()
    await broker.connect()
    broker.orders = {
        "CRYPTO-WORKING": {"status": "ApiPending", "real_money": False},
        "CRYPTO-FILLED": {"status": "filled", "real_money": False, "filled_price": 0.5},
    }

    assert await broker.cancel_all() is True

    working = await broker.get_order_status("CRYPTO-WORKING")
    filled = await broker.get_order_status("CRYPTO-FILLED")
    assert working["status"] == "Cancelled"
    assert working["cancelled_at"] is not None
    assert working["real_money"] is False
    assert filled["status"] == "filled"
    assert filled["filled_price"] == 0.5
    assert await broker.cancel_all() is False


def test_crypto_sandbox_is_not_public_broker_selection():
    with pytest.raises(ValueError, match="External broker adapters are disabled"):
        get_broker("crypto-sandbox")

    with pytest.raises(ValueError, match="Live broker execution is disabled"):
        get_broker("mock", paper_only=False)

    with pytest.raises(ValueError, match="credentials are not accepted"):
        get_broker("mock", credentials={"secret": "not-used"})
