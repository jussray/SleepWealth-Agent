import pytest

from backend.pump_live_sandbox import PumpEvidenceSandboxSession


def pump_evidence(**overrides):
    values = {
        "source_url": "https://pump.fun/coin/example",
        "symbol": "MOM8",
        "mint": "PumpMint111111111111111111111111111111111",
        "name": "MOM OF 8",
        "price": 0.5,
        "observed_at": "2026-09-13T23:00:00Z",
    }
    values.update(overrides)
    return values


@pytest.mark.asyncio
async def test_pump_evidence_is_bound_into_exact_sandbox_proposal_before_approval():
    session = PumpEvidenceSandboxSession(initial_cash=100.0)

    before = await session.wallet()
    proposal = await session.propose_from_pump_evidence(
        pump_evidence(),
        qty=10,
        side="buy",
    )
    after_proposal = await session.wallet()

    assert proposal["status"] == "pending"
    assert proposal["stage"] == "approval"
    assert proposal["real_money"] is False
    assert proposal["live_execution"] is False
    assert len(proposal["proposal_fingerprint"]) == 64
    assert len(proposal["public_evidence_fingerprint"]) == 64
    assert len(proposal["evidence_observation_fingerprint"]) == 64
    assert proposal["evaluation"]["public_evidence_fingerprint"] == proposal["public_evidence_fingerprint"]
    assert proposal["evaluation"]["evidence_observation_fingerprint"] == proposal["evidence_observation_fingerprint"]
    assert proposal["pump_shadow"]["mint"].startswith("PumpMint")
    assert proposal["pump_shadow"]["mirrored_price"] == 0.5
    assert proposal["pump_shadow"]["real_money"] is False
    assert after_proposal["cash"] == before["cash"] == 100.0

    executed = await session.approve_and_execute(proposal["proposal_id"])
    after = await session.wallet()

    assert executed["status"] == "executed"
    assert executed["public_evidence_fingerprint"] == proposal["public_evidence_fingerprint"]
    assert executed["evidence_observation_fingerprint"] == proposal["evidence_observation_fingerprint"]
    assert executed["pump_shadow"]["mirror_fingerprint"] == proposal["pump_shadow"]["mirror_fingerprint"]
    assert executed["execution"]["real_money"] is False
    assert executed["live_execution"] is False
    assert after["cash"] == pytest.approx(95.0)


@pytest.mark.asyncio
async def test_pump_evidence_changes_proposal_identity():
    first = PumpEvidenceSandboxSession(initial_cash=100.0)
    second = PumpEvidenceSandboxSession(initial_cash=100.0)

    p1 = await first.propose_from_pump_evidence(pump_evidence(price=0.5), qty=10, side="buy")
    p2 = await second.propose_from_pump_evidence(pump_evidence(price=0.6), qty=10, side="buy")

    assert p1["public_evidence_fingerprint"] != p2["public_evidence_fingerprint"]
    assert p1["evidence_observation_fingerprint"] != p2["evidence_observation_fingerprint"]
    assert p1["proposal_fingerprint"] != p2["proposal_fingerprint"]


@pytest.mark.asyncio
async def test_pump_sandbox_rejects_execution_or_wallet_fields_in_evidence():
    session = PumpEvidenceSandboxSession(initial_cash=100.0)

    with pytest.raises(ValueError, match="reject execution/credential fields"):
        await session.propose_from_pump_evidence(
            pump_evidence(wallet_address="forbidden"),
            qty=10,
            side="buy",
        )


@pytest.mark.asyncio
async def test_pump_sandbox_blocks_unfunded_order_without_approval_authority():
    session = PumpEvidenceSandboxSession(initial_cash=1.0)

    result = await session.propose_from_pump_evidence(
        pump_evidence(price=0.5),
        qty=10,
        side="buy",
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "evaluation"
    assert "insufficient sandbox cash" in result["evaluation"]["reason"]
    assert result["real_money"] is False
    assert result["live_execution"] is False
