from datetime import datetime, timedelta, timezone

import pytest

from broker import CryptoSandboxBroker, Order
from market import PumpShadowBridge


def snapshot(**overrides):
    values = {
        "mint": "PumpMint111111111111111111111111111111111",
        "symbol": "MOM8",
        "price": 0.0125,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": "founder-approved-read-only-source",
        "source_classification": "user-supplied",
    }
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_live_observation_is_read_only_and_non_authorizing():
    observation = await PumpShadowBridge.observe(snapshot())

    assert observation.symbol == "MOM8"
    assert observation.price == 0.0125
    assert observation.lane == "crypto"
    assert observation.crypto_native is True
    assert observation.instrument_type == "PUMP_TOKEN"
    assert observation.read_only is True
    assert observation.authority == "none"
    assert observation.fingerprint


@pytest.mark.asyncio
async def test_exact_live_price_mirrors_into_existing_crypto_sandbox():
    live = await PumpShadowBridge.observe(snapshot(price=0.025))
    sandbox = CryptoSandboxBroker(initial_cash=10.0)
    await sandbox.connect()

    receipt = PumpShadowBridge.mirror_to_practice(
        live,
        mint="PumpMint111111111111111111111111111111111",
        sandbox=sandbox,
    )
    fill = await sandbox.submit_order(Order("MOM8", 4, "buy", asset_class="crypto"))

    assert receipt.live_mode == "live"
    assert receipt.practice_mode == "practice"
    assert receipt.mirrored_price == live.price
    assert receipt.observation_fingerprint == live.fingerprint
    assert receipt.real_money is False
    assert receipt.wallet_access is False
    assert receipt.transaction_signing is False
    assert receipt.live_execution is False
    assert sandbox.is_paper_only() is True
    assert fill["filled_price"] == live.price
    assert fill["real_money"] is False
    assert fill["fill_classification"] == "SIMULATED_CRYPTO_WALLET_FILL"


@pytest.mark.asyncio
async def test_stale_live_snapshot_fails_closed():
    stale = snapshot(timestamp=(datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat())

    with pytest.raises(ValueError, match="stale"):
        await PumpShadowBridge.observe(stale)


@pytest.mark.asyncio
@pytest.mark.parametrize("price", [0, -1, float("nan"), float("inf"), float("-inf")])
async def test_invalid_live_price_fails_closed(price):
    with pytest.raises(ValueError, match="finite and greater than zero"):
        await PumpShadowBridge.observe(snapshot(price=price))


@pytest.mark.asyncio
async def test_website_scrape_classification_is_rejected():
    with pytest.raises(PermissionError, match="scraping is not supported"):
        await PumpShadowBridge.observe(snapshot(source_classification="pump-site-scrape"))


@pytest.mark.asyncio
async def test_snapshot_identity_and_mint_are_preserved():
    source = snapshot(symbol="MOM8")
    live = await PumpShadowBridge.observe(source)
    sandbox = CryptoSandboxBroker(initial_cash=10.0)
    await sandbox.connect()

    receipt = PumpShadowBridge.mirror_to_practice(
        live,
        mint=source["mint"],
        sandbox=sandbox,
    )

    assert receipt.symbol == "MOM8"
    assert receipt.mint == source["mint"]
    assert receipt.mirror_fingerprint


@pytest.mark.asyncio
async def test_empty_mint_fails_closed():
    live = await PumpShadowBridge.observe(snapshot())
    sandbox = CryptoSandboxBroker(initial_cash=10.0)
    await sandbox.connect()

    with pytest.raises(ValueError, match="mint must not be empty"):
        PumpShadowBridge.mirror_to_practice(live, mint=" ", sandbox=sandbox)
