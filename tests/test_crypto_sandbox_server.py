import pytest

from backend.crypto_sandbox_server import CryptoSandboxSession


@pytest.mark.asyncio
async def test_proposal_requires_separate_approval_before_wallet_changes():
    session = CryptoSandboxSession(initial_cash=100.0)

    before = await session.wallet()
    proposal = await session.propose("MOM8", 10, "buy", 0.5)
    after_proposal = await session.wallet()

    assert proposal["status"] == "pending"
    assert proposal["stage"] == "approval"
    assert proposal["real_money"] is False
    assert proposal["live_execution"] is False
    assert len(proposal["proposal_fingerprint"]) == 64
    assert proposal["proposal_cookie"].startswith("crypto-sandbox-proposal-v1:")
    assert after_proposal["cash"] == before["cash"] == 100.0

    executed = await session.approve_and_execute(proposal["proposal_id"])
    after = await session.wallet()

    assert executed["status"] == "executed"
    assert executed["execution"]["real_money"] is False
    assert executed["execution"]["wallet_mode"] == "sandbox"
    assert executed["approval_cookie"].startswith("crypto-sandbox-approval-v1:")
    assert executed["outcome_cookie"].startswith("crypto-sandbox-outcome-v1:")
    assert len(executed["outcome_fingerprint"]) == 64
    assert after["cash"] == pytest.approx(95.0)


@pytest.mark.asyncio
async def test_same_sandbox_proposal_cannot_execute_twice():
    session = CryptoSandboxSession(initial_cash=100.0)
    proposal = await session.propose("MOM8", 10, "buy", 0.5)

    first = await session.approve_and_execute(proposal["proposal_id"])
    second = await session.approve_and_execute(proposal["proposal_id"])

    assert first["status"] == "executed"
    assert second["status"] == "blocked"
    assert second["stage"] == "approval"
    assert "not pending" in second["reason"]


@pytest.mark.asyncio
async def test_sandbox_blocks_unfunded_proposal_without_creating_authority():
    session = CryptoSandboxSession(initial_cash=5.0)

    result = await session.propose("MOM8", 20, "buy", 0.5)

    assert result["status"] == "blocked"
    assert result["stage"] == "evaluation"
    assert result["evaluation"]["allowed"] is False
    assert "insufficient sandbox cash" in result["evaluation"]["reason"]
    assert result["real_money"] is False
    assert result["live_execution"] is False
