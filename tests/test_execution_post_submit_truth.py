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


async def _build(tmp_path, queue=None, audit=None):
    broker = MockBroker(initial_cash=10_000)
    await broker.connect()
    portfolio = PortfolioTracker(broker, min_cash_floor=RULES["floor_cash"])
    queue = queue or ApprovalQueue(state_path=None)
    audit = audit or AuditLogger(log_path=str(tmp_path / "audit.log"))
    gates = RiskGates(broker, portfolio)
    executor = ExecutionManager(broker, queue, audit, gates)
    return broker, portfolio, queue, audit, executor


async def _approved_order(tmp_path, queue=None, audit=None):
    broker, portfolio, queue, audit, executor = await _build(tmp_path, queue, audit)
    account = await portfolio.refresh()
    order = Order("AAPL", 1, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account, price=MOCK_PRICE)
    proposal_id = await executor.propose_order(order, evaluation)
    assert queue.approve(proposal_id)
    return broker, queue, audit, executor, proposal_id


@pytest.mark.asyncio
async def test_broker_success_survives_final_audit_failure(tmp_path):
    class FinalAuditFailLogger(AuditLogger):
        async def log(self, event: dict) -> str:
            if event.get("event") == "order_submitted":
                raise OSError("simulated audit disk failure")
            return await super().log(event)

    audit = FinalAuditFailLogger(log_path=str(tmp_path / "audit.log"))
    broker, queue, _audit, executor, proposal_id = await _approved_order(
        tmp_path,
        audit=audit,
    )

    result = await executor.execute_approved(proposal_id)

    assert result["execution_confirmed"] is True
    assert result["status"] == "filled"
    assert result["order_id"].startswith("MOCK-")
    assert result["completion_classification"] == "EXECUTED_AUDIT_DEGRADED"
    assert result["approval_state_persisted"] is True
    assert result["audit_persisted"] is False
    assert "simulated audit disk failure" in result["audit_error"]

    restored = queue.get(proposal_id)
    assert restored is not None
    assert restored.status is ApprovalStatus.EXECUTED
    assert restored.order_id == result["order_id"]
    assert broker.order_counter == 1

    replay = await executor.execute_approved(proposal_id)
    assert "not approved" in replay["error"]
    assert broker.order_counter == 1


@pytest.mark.asyncio
async def test_broker_success_survives_execution_state_persistence_failure(tmp_path):
    queue = ApprovalQueue(state_path=None)
    broker, queue, audit, executor, proposal_id = await _approved_order(
        tmp_path,
        queue=queue,
    )

    original_mark_executed = queue.mark_executed

    def fail_mark_executed(_proposal_id, _order_id=None):
        raise OSError("simulated approval-state persistence failure")

    queue.mark_executed = fail_mark_executed
    result = await executor.execute_approved(proposal_id)
    queue.mark_executed = original_mark_executed

    assert result["execution_confirmed"] is True
    assert result["status"] == "filled"
    assert result["order_id"].startswith("MOCK-")
    assert result["completion_classification"] == "EXECUTED_STATE_DEGRADED"
    assert result["approval_state_persisted"] is False
    assert result["reconciliation_required"] is True
    assert result["reconcile_state_persisted"] is True
    assert "simulated approval-state persistence failure" in result["state_error"]
    assert result["audit_persisted"] is True

    restored = queue.get(proposal_id)
    assert restored is not None
    assert restored.status is ApprovalStatus.RECONCILE_REQUIRED
    assert broker.order_counter == 1

    replay = await executor.execute_approved(proposal_id)
    assert "not approved" in replay["error"]
    assert broker.order_counter == 1

    events = await audit.read()
    reconcile = next(
        event for event in events if event.get("event") == "execution_reconcile_required"
    )
    assert reconcile["order_id"] == result["order_id"]
    assert reconcile["reconcile_state_persisted"] is True
