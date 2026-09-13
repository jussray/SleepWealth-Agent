import pytest

from approvals.queue import ApprovalQueue, ApprovalStatus
from audit.logger import AuditLogger
from broker.base import Order
from broker.mock import MOCK_PRICE, MockBroker
from engine.evaluator import ProposalEvaluator
from execution.executor import ExecutionManager
from portfolio.tracker import PortfolioTracker
from risk.gates import RiskGates


RULES = {
    "version": "test-v1",
    "floor_cash": 5.0,
    "max_daily_loss": 100.0,
    "max_position_size": 1000.0,
    "approved_symbols": ["AAPL"],
    "ceiling": {"current": 1000.0, "can_auto_increase": False},
}


class SubmissionErrorBroker(MockBroker):
    async def submit_order(self, order):
        raise RuntimeError("simulated transport failure")


@pytest.mark.asyncio
async def test_submission_error_persists_reconciliation_state(tmp_path):
    broker = SubmissionErrorBroker(initial_cash=10_000)
    await broker.connect()
    portfolio = PortfolioTracker(broker, min_cash_floor=RULES["floor_cash"])
    account = await portfolio.refresh()
    state = tmp_path / "approvals.json"
    queue = ApprovalQueue(str(state), session_id="session-a")
    audit = AuditLogger(str(tmp_path / "audit.log"))
    executor = ExecutionManager(broker, queue, audit, RiskGates(broker, portfolio))

    order = Order("AAPL", 1, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account, price=MOCK_PRICE)
    proposal_id = await executor.propose_order(order, evaluation)
    assert queue.approve(proposal_id)

    result = await executor.execute_approved(proposal_id)
    assert "outcome unknown" in result["error"]
    assert queue.get(proposal_id).status is ApprovalStatus.RECONCILE_REQUIRED

    restarted = ApprovalQueue(str(state), session_id="session-b")
    restored = restarted.get(proposal_id)
    assert restored is not None
    assert restored.status is ApprovalStatus.RECONCILE_REQUIRED
    assert restarted.begin_execution(proposal_id) is False

    events = await audit.read()
    names = [event.get("event") for event in events]
    assert "execution_started" in names
    assert "execution_reconcile_required" in names
