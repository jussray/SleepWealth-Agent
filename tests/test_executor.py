import pytest

from approvals.queue import ApprovalQueue
from audit.logger import AuditLogger
from broker.base import Order
from broker.mock import MOCK_PRICE, MockBroker
from engine.evaluator import ProposalEvaluator
from execution.executor import ExecutionManager
from portfolio.tracker import PortfolioTracker
from risk.gates import RiskGates

RULES = {
    "floor_cash": 5.0,
    "max_daily_loss": 100.0,
    "max_position_size": 1000.0,
    "approved_symbols": ["AAPL"],
    "ceiling": {"current": 1000.0, "can_auto_increase": False},
}


async def _build(tmp_path, cash=10_000):
    broker = MockBroker(initial_cash=cash)
    await broker.connect()
    portfolio = PortfolioTracker(broker, min_cash_floor=RULES["floor_cash"])
    queue = ApprovalQueue()
    audit = AuditLogger(log_path=str(tmp_path / "audit.log"))
    gates = RiskGates(broker, portfolio)
    executor = ExecutionManager(broker, queue, audit, gates)
    return broker, portfolio, queue, audit, executor


@pytest.mark.asyncio
async def test_happy_path(tmp_path):
    _broker, portfolio, queue, audit, executor = await _build(tmp_path)
    account = await portfolio.refresh()

    order = Order("AAPL", 5, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account, price=MOCK_PRICE)
    assert evaluation["allowed"]

    proposal_id = await executor.propose_order(order, evaluation)
    queue.approve(proposal_id)
    result = await executor.execute_approved(proposal_id)

    assert "order_id" in result
    events = await audit.read()
    assert any(e["event"] == "order_submitted" for e in events)


@pytest.mark.asyncio
async def test_unapproved_proposal_cannot_execute(tmp_path):
    _broker, portfolio, _queue, _audit, executor = await _build(tmp_path)
    account = await portfolio.refresh()

    order = Order("AAPL", 5, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account, price=MOCK_PRICE)
    proposal_id = await executor.propose_order(order, evaluation)

    result = await executor.execute_approved(proposal_id)
    assert "error" in result
    assert "not approved" in result["error"]


@pytest.mark.asyncio
async def test_unapproved_symbol_blocked(tmp_path):
    _broker, portfolio, _queue, _audit, _executor = await _build(tmp_path)
    account = await portfolio.refresh()

    evaluation = ProposalEvaluator(RULES).evaluate(
        Order("DOGE", 1, "buy"),
        account,
        price=MOCK_PRICE,
    )
    assert not evaluation["allowed"]
    assert "approved_symbols" in evaluation["reason"]


@pytest.mark.asyncio
async def test_cash_floor_blocks_order(tmp_path):
    _broker, portfolio, _queue, _audit, _executor = await _build(tmp_path, cash=500)
    account = await portfolio.refresh()

    evaluation = ProposalEvaluator(RULES).evaluate(
        Order("AAPL", 5, "buy"),
        account,
        price=MOCK_PRICE,
    )
    assert not evaluation["allowed"]
    assert "cash floor" in evaluation["reason"]
