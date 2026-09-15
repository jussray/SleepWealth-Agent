from datetime import datetime, timezone

import pytest

from broker import CryptoSandboxBroker, Order
from market import PumpFunPracticeShadowBridge


def evidence(**overrides):
    values = {
        "source_url": "https://pump.fun/coin/example",
        "symbol": "MOM8",
        "mint": "PumpMint111111111111111111111111111111111",
        "name": "MOM OF 8",
        "market_cap": 12345,
        "price": 0.0125,
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }
    values.update(overrides)
    return values


def test_shadow_observation_binds_public_evidence_mint_and_price_without_authority():
    bridge = PumpFunPracticeShadowBridge()
    observed = bridge.observe(evidence())

    assert observed.symbol == "MOM8"
    assert observed.mint.startswith("PumpMint")
    assert observed.price == 0.0125
    assert observed.fingerprint
    assert observed.public_evidence_fingerprint
    assert observed.read_only is True
    assert observed.authority == "none"
    assert observed.real_money is False
    assert observed.wallet_connection is False
    assert observed.transaction_signing is False
    assert observed.automated_scraping is False


def test_price_and_mint_each_change_shadow_identity():
    observed_at = datetime.now(timezone.utc).isoformat()
    bridge = PumpFunPracticeShadowBridge()
    base = bridge.observe(evidence(observed_at=observed_at))
    changed_price = bridge.observe(evidence(price=0.02, observed_at=observed_at))
    changed_mint = bridge.observe(evidence(mint="DifferentMint", observed_at=observed_at))

    assert base.fingerprint != changed_price.fingerprint
    assert base.fingerprint != changed_mint.fingerprint


@pytest.mark.asyncio
async def test_exact_shadow_price_mirrors_into_existing_paper_crypto_sandbox():
    bridge = PumpFunPracticeShadowBridge()
    observed = bridge.observe(evidence(price=0.025))
    sandbox = CryptoSandboxBroker(initial_cash=10.0)
    await sandbox.connect()

    receipt = bridge.mirror_to_practice(observed, sandbox)
    fill = await sandbox.submit_order(Order("MOM8", 4, "buy", asset_class="crypto"))

    assert receipt.observation_fingerprint == observed.fingerprint
    assert receipt.public_evidence_fingerprint == observed.public_evidence_fingerprint
    assert receipt.mint == observed.mint
    assert receipt.mirrored_price == observed.price
    assert receipt.real_money is False
    assert receipt.wallet_connection is False
    assert receipt.transaction_signing is False
    assert receipt.live_execution is False
    assert sandbox.is_paper_only() is True
    assert fill["filled_price"] == observed.price
    assert fill["real_money"] is False
    assert fill["fill_classification"] == "SIMULATED_CRYPTO_WALLET_FILL"


@pytest.mark.parametrize("price", [0, -1, float("nan"), float("inf"), float("-inf")])
def test_invalid_shadow_price_fails_closed(price):
    bridge = PumpFunPracticeShadowBridge()
    with pytest.raises(ValueError, match="finite and greater than zero"):
        bridge.observe(evidence(price=price))


def test_shadow_requires_symbol_mint_and_price():
    bridge = PumpFunPracticeShadowBridge()
    with pytest.raises(ValueError, match="both symbol and mint"):
        bridge.observe(evidence(mint=""))
    with pytest.raises(ValueError, match="requires price"):
        broken = evidence()
        broken.pop("price")
        bridge.observe(broken)


def test_existing_pump_observer_still_rejects_execution_fields_and_non_pump_sources():
    bridge = PumpFunPracticeShadowBridge()
    with pytest.raises(ValueError, match="reject execution/credential fields"):
        bridge.observe(evidence(wallet_address="forbidden"))
    with pytest.raises(ValueError, match="pump.fun source_url"):
        bridge.observe(evidence(source_url="https://example.com/coin"))
