import json

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
    assert executed["receipt"]["classification"] == "SIMULATED_EXECUTION_RECEIPT"
    assert executed["receipt"]["simulated_fill_fingerprint"] == executed["execution"]["continuity_fingerprint"]
    assert executed["receipt"]["real_money"] is False
    assert executed["receipt"]["live_execution"] is False
    assert len(executed["receipt"]["receipt_fingerprint"]) == 64
    assert after["cash"] == pytest.approx(95.0)
    assert after["equity"] == pytest.approx(100.0)
    assert after["pnl_total"] == pytest.approx(0.0)
    assert len(after["pnl_fingerprint"]) == 64


@pytest.mark.asyncio
async def test_live_box_blocks_approval_when_newer_shadow_price_replaces_bound_price():
    session = PumpLiveBoxSession(100, state_path=None, session_id="live-box-stale-test")
    stale = await session.propose(evidence(price=0.5), 10, "buy")
    current = await session.propose(evidence(price=0.75), 10, "buy")

    blocked = await session.approve(stale["proposal_id"])
    wallet_after_block = await session.wallet()

    assert blocked["status"] == "blocked"
    assert blocked["stale_evidence"] is True
    assert blocked["bound_price"] == pytest.approx(0.5)
    assert blocked["current_price"] == pytest.approx(0.75)
    assert "new proposal" in blocked["reason"]
    assert blocked["real_money"] is False
    assert blocked["live_execution"] is False
    assert wallet_after_block["cash"] == pytest.approx(100.0)

    executed = await session.approve(current["proposal_id"])
    wallet_after_current = await session.wallet()
    assert executed["status"] == "executed"
    assert executed["execution"]["filled_price"] == pytest.approx(0.75)
    assert wallet_after_current["cash"] == pytest.approx(92.5)
    assert wallet_after_current["pnl_total"] == pytest.approx(0.0)


@pytest.mark.asyncio
async def test_live_box_round_trip_emits_pnl_and_chained_audit_receipts(tmp_path):
    audit_path = tmp_path / "pump-live-box-audit.jsonl"
    session = PumpLiveBoxSession(
        100,
        state_path=None,
        session_id="live-box-pnl-test",
        audit_path=str(audit_path),
    )

    buy = await session.propose(evidence(price=0.5), 10, "buy")
    bought = await session.approve(buy["proposal_id"])
    assert bought["status"] == "executed"
    assert bought["wallet"]["pnl_total"] == pytest.approx(0.0)
    assert bought["receipt"]["audit"]["classification"] == "OBSERVED_UNANCHORED"
    assert bought["receipt"]["audit"]["trusted"] is False

    sell = await session.propose(evidence(price=0.75), 10, "sell")
    sold = await session.approve(sell["proposal_id"])
    wallet = await session.wallet()

    assert sold["status"] == "executed"
    assert sold["execution"]["filled_price"] == pytest.approx(0.75)
    assert wallet["cash"] == pytest.approx(102.5)
    assert wallet["equity"] == pytest.approx(102.5)
    assert wallet["pnl_total"] == pytest.approx(2.5)
    assert sold["receipt"]["sandbox_pnl_total"] == pytest.approx(2.5)
    assert sold["receipt"]["pnl_fingerprint"] == wallet["pnl_fingerprint"]
    assert sold["receipt"]["audit"]["classification"] == "OBSERVED_UNANCHORED"
    assert sold["receipt"]["audit"]["trusted"] is False
    assert sold["receipt"]["audit"]["entry_hash"] == sold["receipt"]["audit"]["terminal_hash"]
    assert sold["receipt"]["real_money"] is False
    assert sold["receipt"]["live_execution"] is False

    records = [json.loads(line) for line in audit_path.read_text(encoding="utf-8").splitlines()]
    assert len(records) == 2
    assert records[0]["event"] == "pump_sandbox_execution_observed"
    assert records[1]["prev_hash"] == records[0]["entry_hash"]
    assert records[1]["sandbox_pnl_total"] == pytest.approx(2.5)
    assert records[1]["real_money"] is False
    assert records[1]["live_execution"] is False


@pytest.mark.asyncio
async def test_live_box_rejects_non_pump_source():
    session = PumpLiveBoxSession(100, state_path=None, session_id="live-box-test")
    bad = evidence()
    bad["source_url"] = "https://example.com/coin/MOM8"
    with pytest.raises(ValueError, match="requires an https://pump.fun source_url"):
        await session.propose(bad, 10, "buy")
