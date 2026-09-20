from datetime import datetime, timedelta, timezone

import pytest

from approvals.queue import ApprovalQueue
from audit.logger import AuditLogger
from authority.money_movement import (
    SandboxAuthorityLedger,
    SandboxMoneyAction,
    issue_sandbox_money_authority,
    validate_sandbox_money_authority,
)
from broker.base import Order
from broker.mock import MOCK_PRICE, MockBroker
from engine.evaluator import ProposalEvaluator
from execution.executor import ExecutionManager
from execution.sandbox_money import SandboxMoneyExecutionManager
from portfolio.tracker import PortfolioTracker
from risk.gates import RiskGates


RULES = {
    "version": "sandbox-money-v1",
    "floor_cash": 5.0,
    "max_daily_loss": 100.0,
    "max_position_size": 1000.0,
    "approved_symbols": ["AAPL"],
    "ceiling": {"current": 1000.0, "can_auto_increase": False},
}
ISSUER_ID = "sandbox-authority-test"
AUTHORITY_KEY = "k" * 32
LEDGER_KEY = "l" * 32
ACCOUNT_FINGERPRINT = "1ca77c76c21cc04ea67242a7810ef06c805d2ea97cf2822bd07fd97a5816fe33"
SUBJECT = "sleepwealth-sandbox-runtime"
PROVIDER = "mock"


async def _build(tmp_path):
    broker = MockBroker(initial_cash=10_000)
    await broker.connect()
    portfolio = PortfolioTracker(broker, min_cash_floor=RULES["floor_cash"])
    queue = ApprovalQueue(state_path=None)
    audit = AuditLogger(log_path=str(tmp_path / "audit.log"))
    gates = RiskGates(broker, portfolio)
    executor = ExecutionManager(broker, queue, audit, gates)
    ledger = SandboxAuthorityLedger(tmp_path / "sandbox-authority.json", LEDGER_KEY)
    guarded = SandboxMoneyExecutionManager(
        executor,
        queue,
        subject=SUBJECT,
        provider=PROVIDER,
        account_fingerprint=ACCOUNT_FINGERPRINT,
        trusted_authority_keys={ISSUER_ID: AUTHORITY_KEY},
        ledger=ledger,
    )
    return broker, portfolio, queue, audit, executor, ledger, guarded


def _receipt(queue: ApprovalQueue, proposal_id: str, **overrides):
    proposal = queue.get(proposal_id)
    assert proposal is not None
    assert proposal.approved_fingerprint
    values = {
        "issuer_id": ISSUER_ID,
        "issuer_key": AUTHORITY_KEY,
        "proposal_id": proposal_id,
        "subject": SUBJECT,
        "provider": PROVIDER,
        "account_fingerprint": ACCOUNT_FINGERPRINT,
        "approval_fingerprint": proposal.approved_fingerprint,
        "action": SandboxMoneyAction.ORDER_SUBMIT,
        "symbol": proposal.order.symbol,
        "asset_class": proposal.order.asset_class,
        "side": proposal.order.side,
        "quantity": proposal.order.qty,
        "max_notional": proposal.evaluation["ceiling"],
        "idempotency_key": f"idem-{proposal_id}",
        "nonce": f"nonce-{proposal_id}",
    }
    values.update(overrides)
    return issue_sandbox_money_authority(**values)


@pytest.mark.asyncio
async def test_scoped_authority_executes_through_existing_paper_path(tmp_path):
    broker, portfolio, queue, audit, executor, ledger, guarded = await _build(tmp_path)
    account = await portfolio.refresh()

    order = Order("AAPL", 1, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account, price=MOCK_PRICE)
    proposal_id = await executor.propose_order(order, evaluation)
    assert queue.approve(proposal_id, reason="explicit human sandbox approval")

    receipt = _receipt(queue, proposal_id)
    result = await guarded.execute_authorized(receipt)

    assert result["status"] == "filled"
    assert result["sandbox_authority"] == "CONSUMED"
    assert result["sandbox_authority_state"] == "completed"
    assert result["sandbox_only"] is True
    assert result["live_execution_authorized"] is False
    assert broker.order_counter == 1
    state = ledger.snapshot()
    assert state["idempotency"][f"idem-{proposal_id}"]["state"] == "completed"
    events = await audit.read()
    assert any(event["event"] == "sandbox_money_authority_reserved" for event in events)
    assert any(event["event"] == "sandbox_money_authority_consumed" for event in events)


def test_forged_receipt_fails_authentication():
    receipt = issue_sandbox_money_authority(
        issuer_id=ISSUER_ID,
        issuer_key=AUTHORITY_KEY,
        proposal_id="PROP-1",
        subject=SUBJECT,
        provider=PROVIDER,
        account_fingerprint=ACCOUNT_FINGERPRINT,
        approval_fingerprint="b" * 64,
        action=SandboxMoneyAction.ORDER_SUBMIT,
        symbol="AAPL",
        asset_class="stocks",
        side="buy",
        quantity=1,
        max_notional=1000,
    )
    receipt["quantity"] = 99
    decision = validate_sandbox_money_authority(
        receipt,
        {ISSUER_ID: AUTHORITY_KEY},
    )
    assert decision.accepted is False
    assert decision.classification == "INVALID"


def test_expired_receipt_is_stale():
    issued = datetime.now(timezone.utc) - timedelta(minutes=4)
    receipt = issue_sandbox_money_authority(
        issuer_id=ISSUER_ID,
        issuer_key=AUTHORITY_KEY,
        proposal_id="PROP-1",
        subject=SUBJECT,
        provider=PROVIDER,
        account_fingerprint=ACCOUNT_FINGERPRINT,
        approval_fingerprint="b" * 64,
        action=SandboxMoneyAction.ORDER_SUBMIT,
        symbol="AAPL",
        asset_class="stocks",
        side="buy",
        quantity=1,
        max_notional=1000,
        issued_at=issued,
        ttl_seconds=60,
    )
    decision = validate_sandbox_money_authority(
        receipt,
        {ISSUER_ID: AUTHORITY_KEY},
        evaluated_at=datetime.now(timezone.utc),
    )
    assert decision.accepted is False
    assert decision.classification == "STALE"


def test_ledger_replay_revocation_and_kill_switch_fail_closed(tmp_path):
    ledger = SandboxAuthorityLedger(tmp_path / "ledger.json", LEDGER_KEY)
    ok, _ = ledger.reserve("SMA-one", "idem-one")
    assert ok is True
    replay, replay_reason = ledger.reserve("SMA-one", "idem-one")
    assert replay is False
    assert "already crossed" in replay_reason

    ledger.revoke("SMA-two")
    revoked, revoked_reason = ledger.reserve("SMA-two", "idem-two")
    assert revoked is False
    assert "revoked" in revoked_reason

    ledger.set_kill_switch(True)
    killed, killed_reason = ledger.reserve("SMA-three", "idem-three")
    assert killed is False
    assert "kill switch" in killed_reason


@pytest.mark.asyncio
async def test_account_scope_conflict_never_reaches_broker(tmp_path):
    broker, portfolio, queue, _audit, executor, _ledger, guarded = await _build(tmp_path)
    account = await portfolio.refresh()
    order = Order("AAPL", 1, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account, price=MOCK_PRICE)
    proposal_id = await executor.propose_order(order, evaluation)
    assert queue.approve(proposal_id)

    receipt = _receipt(queue, proposal_id, account_fingerprint="c" * 64)
    result = await guarded.execute_authorized(receipt)

    assert result["classification"] == "ACCOUNT_CONFLICT"
    assert broker.order_counter == 0


@pytest.mark.asyncio
async def test_ceiling_scope_conflict_never_reaches_broker(tmp_path):
    broker, portfolio, queue, _audit, executor, _ledger, guarded = await _build(tmp_path)
    account = await portfolio.refresh()
    order = Order("AAPL", 1, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account, price=MOCK_PRICE)
    proposal_id = await executor.propose_order(order, evaluation)
    assert queue.approve(proposal_id)

    receipt = _receipt(queue, proposal_id, max_notional=999.0)
    result = await guarded.execute_authorized(receipt)

    assert result["classification"] == "CEILING_CONFLICT"
    assert broker.order_counter == 0


@pytest.mark.asyncio
async def test_authority_kill_switch_never_reaches_broker(tmp_path):
    broker, portfolio, queue, _audit, executor, ledger, guarded = await _build(tmp_path)
    account = await portfolio.refresh()
    order = Order("AAPL", 1, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account, price=MOCK_PRICE)
    proposal_id = await executor.propose_order(order, evaluation)
    assert queue.approve(proposal_id)
    receipt = _receipt(queue, proposal_id)

    ledger.set_kill_switch(True)
    result = await guarded.execute_authorized(receipt)

    assert result["classification"] == "AUTHORITY_STATE_BLOCKED"
    assert "kill switch" in result["error"]
    assert broker.order_counter == 0
