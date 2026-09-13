import pytest
from backend.pump_live_box_server import PumpLiveBoxSession


def evidence(mint="MOM8-DEMO-MINT", price=0.5):
    return {
        "source_url": "https://pump.fun/coin/MOM8",
        "symbol": "MOM8",
        "mint": mint,
        "price": price,
        "observed_at": "2026-09-13T23:05:00Z",
    }


@pytest.mark.asyncio
async def test_live_box_binds_public_evidence_into_proposal():
    session = PumpLiveBoxSession(100, state_path=None, session_id="live-box-test")
    first = await session.propose(evidence(), 10, "buy")
    second = await session.propose(evidence(mint="DIFFERENT-MINT"), 10, "buy")
    assert first["evidence"]["authority"] == "none"
    assert first["evidence"]["read_only"] is True
    assert first["evaluation"]["pump_observation_fingerprint"] == first["evidence"]["fingerprint"]
    assert first["proposal_fingerprint"] != second["proposal_fingerprint"]
    assert first["real_money"] is False
    assert first["live_execution"] is False


@pytest.mark.asyncio
async def test_live_box_changes_cash_only_after_explicit_sandbox_approval():
    session = PumpLiveBoxSession(100, state_path=None, session_id="live-box-test")
    before = await session.wallet()
    proposal = await session.propose(evidence(), 10, "buy")
    pending = await session.wallet()
    assert pending["cash"] == before["cash"] == 100.0
    executed = await session.approve(proposal["proposal_id"])
    after = await session.wallet()
    assert executed["status"] == "executed"
    assert executed["pump_observation_fingerprint"] == proposal["evidence"]["fingerprint"]
    assert executed["execution"]["real_money"] is False
    assert executed["execution"]["wallet_mode"] == "sandbox"
    assert after["cash"] == pytest.approx(95.0)


@pytest.mark.asyncio
async def test_live_box_rejects_non_pump_source():
    session = PumpLiveBoxSession(100, state_path=None, session_id="live-box-test")
    bad = evidence()
    bad["source_url"] = "https://example.com/coin/MOM8"
    with pytest.raises(ValueError, match="requires an https://pump.fun source_url"):
        await session.propose(bad, 10, "buy")
