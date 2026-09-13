import pytest

from approvals.queue import ApprovalQueue
from audit.logger import AuditLogger
from broker.base import Order
from broker.mock import MockBroker
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
    evaluator = ProposalEvaluator(RULES)
    executor = ExecutionManager(broker, queue, audit, gates, evaluator)
    return broker, portfolio, queue, audit, executor


@pytest.mark.asyncio
async def test_happy_path(tmp_path):
    broker, portfolio, queue, audit, executor = await _build(tmp_path)
    account = await portfolio.refresh()

    order = Order("AAPL", 5, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account)
    assert evaluation["allowed"]

    proposal_id = await executor.propose_order(order, evaluation)
    queue.approve(proposal_id)
    result = await executor.execute_approved(proposal_id)

    assert "order_id" in result
    events = await audit.read()
    assert any(e["event"] == "order_submitted" for e in events)


@pytest.mark.asyncio
async def test_unapproved_proposal_cannot_execute(tmp_path):
    broker, portfolio, queue, audit, executor = await _build(tmp_path)
    account = await portfolio.refresh()

    order = Order("AAPL", 5, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account)
    proposal_id = await executor.propose_order(order, evaluation)

    result = await executor.execute_approved(proposal_id)
    assert "error" in result
    assert "not approved" in result["error"]


@pytest.mark.asyncio
async def test_unapproved_symbol_blocked(tmp_path):
    broker, portfolio, queue, audit, executor = await _build(tmp_path)
    account = await portfolio.refresh()

    evaluation = ProposalEvaluator(RULES).evaluate(Order("DOGE", 1, "buy"), account)
    assert not evaluation["allowed"]
    assert "approved_symbols" in evaluation["reason"]


@pytest.mark.asyncio
async def test_cash_floor_blocks_order(tmp_path):
    broker, portfolio, queue, audit, executor = await _build(tmp_path, cash=500)
    account = await portfolio.refresh()

    evaluation = ProposalEvaluator(RULES).evaluate(Order("AAPL", 5, "buy"), account)
    assert not evaluation["allowed"]
    assert "cash floor" in evaluation["reason"]


@pytest.mark.asyncio
async def test_approved_order_replacement_is_blocked(tmp_path):
    broker, portfolio, queue, audit, executor = await _build(tmp_path)
    account = await portfolio.refresh()

    order = Order("AAPL", 1, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account)
    proposal_id = await executor.propose_order(order, evaluation)
    assert queue.approve(proposal_id)

    queue.get(proposal_id).order = Order("AAPL", 50, "buy")
    result = await executor.execute_approved(proposal_id)

    assert "fingerprint mismatch" in result["error"]
    assert broker.order_counter == 0


@pytest.mark.asyncio
async def test_fresh_quote_rechecks_ceiling_before_submission(tmp_path):
    class PriceSpikeBroker(MockBroker):
        async def get_market_data(self, symbol: str) -> dict:
            data = await super().get_market_data(symbol)
            data.update({"price": 200.0, "bid": 199.0, "ask": 200.0})
            return data

    rules = {**RULES, "ceiling": {"current": 5.0, "can_auto_increase": False}}
    broker = PriceSpikeBroker(initial_cash=10_000)
    await broker.connect()
    portfolio = PortfolioTracker(broker, min_cash_floor=rules["floor_cash"])
    queue = ApprovalQueue()
    audit = AuditLogger(log_path=str(tmp_path / "audit.log"))
    gates = RiskGates(broker, portfolio)
    evaluator = ProposalEvaluator(rules)
    executor = ExecutionManager(broker, queue, audit, gates, evaluator)
    account = await portfolio.refresh()

    order = Order("AAPL", 0.04, "buy")
    evaluation = evaluator.evaluate(order, account, price=100.0)
    assert evaluation["allowed"]
    proposal_id = await executor.propose_order(order, evaluation)
    assert queue.approve(proposal_id)

    result = await executor.execute_approved(proposal_id)

    assert "fresh evaluation blocked" in result["error"]
    assert "exceeds ceiling" in result["error"]
    assert broker.order_counter == 0


@pytest.mark.asyncio
async def test_broker_fill_evidence_is_preserved(tmp_path):
    broker, portfolio, queue, audit, executor = await _build(tmp_path)
    account = await portfolio.refresh()
    order = Order("AAPL", 1, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account)
    proposal_id = await executor.propose_order(order, evaluation)
    queue.approve(proposal_id)

    result = await executor.execute_approved(proposal_id)

    assert result["filled_qty"] == 1
    assert result["filled_price"] == 100.0
    events = await audit.read()
    submitted = next(event for event in events if event["event"] == "order_submitted")
    assert submitted["broker_result"]["filled_qty"] == 1
