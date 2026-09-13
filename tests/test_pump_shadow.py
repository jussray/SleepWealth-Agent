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
async def test_live_observation_is_read_only_non_authorizing_and_mint_bound():
    source = snapshot()
    observation = await PumpShadowBridge.observe(source)

    assert observation.symbol == "MOM8"
    assert observation.mint == source["mint"]
    assert observation.price == 0.0125
    assert observation.lane == "crypto"
    assert observation.crypto_native is True
    assert observation.instrument_type == "PUMP_TOKEN"
    assert observation.read_only is True
    assert observation.authority == "none"
    assert observation.fingerprint
    assert observation.market_fingerprint
    assert observation.fingerprint != observation.market_fingerprint


@pytest.mark.asyncio
async def test_exact_live_price_and_bound_mint_mirror_into_existing_crypto_sandbox():
    source = snapshot(price=0.025)
    live = await PumpShadowBridge.observe(source)
    sandbox = CryptoSandboxBroker(initial_cash=10.0)
    await sandbox.connect()

    receipt = PumpShadowBridge.mirror_to_practice(live, sandbox=sandbox)
    fill = await sandbox.submit_order(Order("MOM8", 4, "buy", asset_class="crypto"))

    assert receipt.live_mode == "live"
    assert receipt.practice_mode == "practice"
    assert receipt.mint == source["mint"]
    assert receipt.mirrored_price == live.price
    assert receipt.observation_fingerprint == live.fingerprint
    assert receipt.market_fingerprint == live.market_fingerprint
    assert receipt.real_money is False
    assert receipt.wallet_access is False
    assert receipt.transaction_signing is False
    assert receipt.live_execution is False
    assert sandbox.is_paper_only() is True
    assert fill["filled_price"] == live.price
    assert fill["real_money"] is False
    assert fill["fill_classification"] == "SIMULATED_CRYPTO_WALLET_FILL"


@pytest.mark.asyncio
async def test_same_market_snapshot_with_different_mint_has_different_pump_fingerprint():
    first = await PumpShadowBridge.observe(snapshot(mint="PumpMintA"))
    second = await PumpShadowBridge.observe(snapshot(mint="PumpMintB"))

    assert first.market_fingerprint == second.market_fingerprint
    assert first.fingerprint != second.fingerprint


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
async def test_empty_mint_fails_closed_before_observation():
    with pytest.raises(ValueError, match="identity fields must not be empty"):
        await PumpShadowBridge.observe(snapshot(mint=" "))
