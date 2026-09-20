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
    "version": "sandbox-money-race-v1",
    "floor_cash": 5.0,
    "max_position_size": 1000.0,
    "approved_symbols": ["AAPL"],
    "ceiling": {"current": 1000.0, "can_auto_increase": False},
}
AUTHORITY_KEY = "k" * 32
LEDGER_KEY = "l" * 32
ACCOUNT_FINGERPRINT = "1ca77c76c21cc04ea67242a7810ef06c805d2ea97cf2822bd07fd97a5816fe33"


class RevokingLedger(SandboxAuthorityLedger):
    def reserve(self, receipt_id: str, idempotency_key: str) -> tuple[bool, str]:
        result = super().reserve(receipt_id, idempotency_key)
        if result[0]:
            self.revoke(receipt_id)
        return result


@pytest.mark.asyncio
async def test_revocation_after_reservation_blocks_before_broker_submission(tmp_path):
    broker = MockBroker(initial_cash=10_000)
    await broker.connect()
    portfolio = PortfolioTracker(broker, min_cash_floor=RULES["floor_cash"])
    account = await portfolio.refresh()
    queue = ApprovalQueue(state_path=None)
    audit = AuditLogger(str(tmp_path / "audit.log"))
    executor = ExecutionManager(broker, queue, audit, RiskGates(broker, portfolio))
    ledger = RevokingLedger(tmp_path / "authority.json", LEDGER_KEY)
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
        idempotency_key="idem-race",
        nonce="nonce-race",
    )

    result = await guarded.execute_authorized(receipt)

    assert result["classification"] == "AUTHORITY_STATE_CHANGED"
    assert "revoked after reservation" in result["error"]
    assert broker.order_counter == 0
    assert ledger.snapshot()["idempotency"]["idem-race"]["state"] == "blocked"
