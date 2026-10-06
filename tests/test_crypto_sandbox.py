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
async def test_crypto_sandbox_implements_full_capability_surface_without_live_authority():
    broker = CryptoSandboxBroker(initial_cash=100.0)
    await broker.connect()

    matrix = broker.capability_matrix()
    for capability in ("launch", "mint", "wallet", "trade", "spend", "transfer"):
        assert matrix[capability]["implemented"] is True
        assert matrix[capability]["mode"] == "sandbox"
    assert matrix["live_authority"] is False

    launch = await broker.launch_asset("MOM8", "MOM OF 8")
    assert launch["status"] == "launched"
    assert launch["real_money"] is False
    assert launch["live_execution"] is False

    mint = await broker.mint_asset("MOM8", 20)
    assert mint["status"] == "minted"
    assert mint["balance"] == pytest.approx(20.0)

    wallet = await broker.wallet()
    assert wallet["positions"]["MOM8"] == pytest.approx(20.0)
    assert wallet["launched_assets"]["MOM8"]["status"] == "launched"

    broker.set_market_price("TEST", 0.50)
    trade = await broker.trade("TEST", 10, "buy")
    assert trade["status"] == "filled"
    assert trade["real_money"] is False

    spend = await broker.spend(5, "sandbox listing fee")
    assert spend["status"] == "spent"
    assert spend["cash_remaining"] == pytest.approx(90.0)
    assert spend["real_money"] is False

    transfer = await broker.transfer_asset("MOM8", 5, "SANDBOX-WALLET-2")
    assert transfer["status"] == "transferred"
    assert transfer["balance"] == pytest.approx(15.0)
    assert transfer["real_money"] is False
    assert transfer["destination_wallet_id"] == "SANDBOX-WALLET-2"

    for receipt in (launch, mint, spend, transfer):
        assert receipt["continuity_cookie"].startswith("crypto-sandbox-capability:")
        assert len(receipt["continuity_fingerprint"]) == 64


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
