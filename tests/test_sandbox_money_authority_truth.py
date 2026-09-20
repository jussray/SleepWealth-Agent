import pytest

from approvals.queue import ApprovalQueue
from audit.logger import AuditLogger
from authority.money_movement import (
    SandboxAuthorityLedger,
    SandboxMoneyAction,
    issue_sandbox_money_authority,
)
from broker.base import Order
from broker.mock import MOCK_PRICE, MockBroker
from engine.evaluator import ProposalEvaluator
from execution.executor import ExecutionManager
from execution.sandbox_money import SandboxMoneyExecutionManager
from portfolio.tracker import PortfolioTracker
from risk.gates import RiskGates


RULES = {
    "version": "sandbox-money-truth-v1",
    "floor_cash": 5.0,
    "max_position_size": 1000.0,
    "approved_symbols": ["AAPL"],
    "ceiling": {"current": 1000.0, "can_auto_increase": False},
}
AUTHORITY_KEY = "k" * 32
LEDGER_KEY = "l" * 32
ACCOUNT_FINGERPRINT = "a" * 64


class FailingCompletedLedger(SandboxAuthorityLedger):
    def classify(self, idempotency_key: str, state: str) -> None:
        if state == "completed":
            raise OSError("simulated authority ledger persistence failure")
        super().classify(idempotency_key, state)


class UnprovedPaperBroker(MockBroker):
    def paper_proof(self) -> dict:
        proof = super().paper_proof()
        proof["provably_paper"] = False
        return proof


async def _scenario(tmp_path, *, broker=None, ledger_class=SandboxAuthorityLedger):
    active_broker = broker or MockBroker(initial_cash=10_000)
    await active_broker.connect()
    portfolio = PortfolioTracker(active_broker, min_cash_floor=RULES["floor_cash"])
    account = await portfolio.refresh()
    queue = ApprovalQueue(state_path=None)
    audit = AuditLogger(str(tmp_path / "audit.log"))
    executor = ExecutionManager(
        active_broker,
        queue,
        audit,
        RiskGates(active_broker, portfolio),
    )
    ledger = ledger_class(tmp_path / "authority.json", LEDGER_KEY)
    guarded = SandboxMoneyExecutionManager(
        executor,
        queue,
        subject="sleepwealth-sandbox-runtime",
        provider="mock",
        account_fingerprint=ACCOUNT_FINGERPRINT,
        trusted_authority_keys={"test-issuer": AUTHORITY_KEY},
        ledger=ledger,
    )
    order = Order("AAPL", 1, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account, price=MOCK_PRICE)
    proposal_id = await executor.propose_order(order, evaluation)
    assert queue.approve(proposal_id)
    proposal = queue.get(proposal_id)
    assert proposal is not None and proposal.approved_fingerprint
    receipt = issue_sandbox_money_authority(
        issuer_id="test-issuer",
        issuer_key=AUTHORITY_KEY,
        proposal_id=proposal_id,
        subject="sleepwealth-sandbox-runtime",
        provider="mock",
        account_fingerprint=ACCOUNT_FINGERPRINT,
        approval_fingerprint=proposal.approved_fingerprint,
        action=SandboxMoneyAction.ORDER_SUBMIT,
        symbol="AAPL",
        asset_class="stocks",
        side="buy",
        quantity=1,
        max_notional=evaluation["ceiling"],
        idempotency_key="idem-truth",
        nonce="nonce-truth",
    )
    return active_broker, guarded, receipt


@pytest.mark.asyncio
async def test_execution_truth_survives_authority_ledger_write_failure(tmp_path):
    broker, guarded, receipt = await _scenario(
        tmp_path,
        ledger_class=FailingCompletedLedger,
    )

    result = await guarded.execute_authorized(receipt)

    assert result["status"] == "filled"
    assert broker.order_counter == 1
    assert result["sandbox_authority"] == "CONSUMED_STATE_DEGRADED"
    assert result["sandbox_authority_ledger_persisted"] is False
    assert result["sandbox_authority_state"] == "reconcile_required"
    assert result["reconciliation_required"] is True
    assert "simulated authority ledger persistence failure" in result["sandbox_authority_state_error"]


@pytest.mark.asyncio
async def test_boolean_paper_claim_without_proof_is_refused(tmp_path):
    broker = UnprovedPaperBroker(initial_cash=10_000)
    active_broker, guarded, receipt = await _scenario(tmp_path, broker=broker)

    result = await guarded.execute_authorized(receipt)

    assert result["classification"] == "LIVE_BROKER_REFUSED"
    assert "provable paper broker evidence" in result["error"]
    assert active_broker.order_counter == 0
