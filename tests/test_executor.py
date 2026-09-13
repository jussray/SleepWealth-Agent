from datetime import datetime, timedelta, timezone

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
    "version": "test-v1",
    "floor_cash": 5.0,
    "max_daily_loss": 100.0,
    "max_position_size": 1000.0,
    "approved_symbols": ["AAPL"],
    "ceiling": {"current": 1000.0, "can_auto_increase": False},
}


async def _build(tmp_path, cash=10_000, broker=None, rules=None):
    active_rules = rules or RULES
    broker = broker or MockBroker(initial_cash=cash)
    await broker.connect()
    portfolio = PortfolioTracker(broker, min_cash_floor=active_rules["floor_cash"])
    queue = ApprovalQueue()
    audit = AuditLogger(log_path=str(tmp_path / "audit.log"))
    gates = RiskGates(broker, portfolio)
    executor = ExecutionManager(broker, queue, audit, gates)
    return broker, portfolio, queue, audit, executor


@pytest.mark.asyncio
async def test_happy_path(tmp_path):
    broker, portfolio, queue, audit, executor = await _build(tmp_path)
    account = await portfolio.refresh()

    order = Order("AAPL", 5, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account, price=MOCK_PRICE)
    assert evaluation["allowed"]

    proposal_id = await executor.propose_order(order, evaluation)
    assert queue.approve(proposal_id)
    result = await executor.execute_approved(proposal_id)

    assert result["status"] == "filled"
    events = await audit.read()
    assert any(event["event"] == "order_submitted" for event in events)


@pytest.mark.asyncio
async def test_unapproved_proposal_cannot_execute(tmp_path):
    _broker, portfolio, _queue, _audit, executor = await _build(tmp_path)
    account = await portfolio.refresh()

    order = Order("AAPL", 5, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account, price=MOCK_PRICE)
    proposal_id = await executor.propose_order(order, evaluation)

    result = await executor.execute_approved(proposal_id)
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


@pytest.mark.asyncio
async def test_approved_order_replacement_is_blocked(tmp_path):
    broker, portfolio, queue, _audit, executor = await _build(tmp_path)
    account = await portfolio.refresh()
    order = Order("AAPL", 1, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account, price=MOCK_PRICE)
    proposal_id = await executor.propose_order(order, evaluation)
    assert queue.approve(proposal_id)

    queue.get(proposal_id).order = Order("AAPL", 50, "buy")
    result = await executor.execute_approved(proposal_id)

    assert "fingerprint mismatch" in result["error"]
    assert broker.order_counter == 0


@pytest.mark.asyncio
async def test_reviewed_evidence_mutation_is_blocked(tmp_path):
    broker, portfolio, queue, _audit, executor = await _build(tmp_path)
    account = await portfolio.refresh()
    order = Order("AAPL", 1, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account, price=MOCK_PRICE)
    proposal_id = await executor.propose_order(order, evaluation)
    assert queue.approve(proposal_id)

    queue.get(proposal_id).evaluation["ceiling"] = 999_999
    result = await executor.execute_approved(proposal_id)

    assert "fingerprint mismatch" in result["error"]
    assert broker.order_counter == 0


@pytest.mark.asyncio
async def test_fresh_quote_rechecks_ceiling_before_submission(tmp_path):
    rules = {
        **RULES,
        "ceiling": {"current": 5.0, "can_auto_increase": False},
    }
    broker = MockBroker(initial_cash=10_000)
    broker.set_market_price("AAPL", 200.0)
    broker, portfolio, queue, _audit, executor = await _build(
        tmp_path,
        broker=broker,
        rules=rules,
    )
    account = await portfolio.refresh()

    order = Order("AAPL", 0.04, "buy")
    evaluation = ProposalEvaluator(rules).evaluate(order, account, price=100.0)
    assert evaluation["allowed"]
    proposal_id = await executor.propose_order(order, evaluation)
    assert queue.approve(proposal_id)

    result = await executor.execute_approved(proposal_id)

    assert "fresh evaluation blocked" in result["error"]
    assert "exceeds ceiling" in result["error"]
    assert broker.order_counter == 0


@pytest.mark.asyncio
async def test_stale_quote_is_blocked_separately(tmp_path):
    class StaleQuoteBroker(MockBroker):
        async def get_market_data(self, symbol: str) -> dict:
            quote = await super().get_market_data(symbol)
            quote["timestamp"] = datetime.now(timezone.utc) - timedelta(minutes=5)
            return quote

    broker, portfolio, queue, _audit, executor = await _build(
        tmp_path,
        broker=StaleQuoteBroker(initial_cash=10_000),
    )
    account = await portfolio.refresh()
    order = Order("AAPL", 1, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account, price=MOCK_PRICE)
    proposal_id = await executor.propose_order(order, evaluation)
    assert queue.approve(proposal_id)

    result = await executor.execute_approved(proposal_id)

    assert "quote is stale" in result["error"]
    assert broker.order_counter == 0


@pytest.mark.asyncio
async def test_fill_evidence_is_preserved(tmp_path):
    _broker, portfolio, queue, audit, executor = await _build(tmp_path)
    account = await portfolio.refresh()
    order = Order("AAPL", 1, "buy")
    evaluation = ProposalEvaluator(RULES).evaluate(order, account, price=MOCK_PRICE)
    proposal_id = await executor.propose_order(order, evaluation)
    assert queue.approve(proposal_id)

    result = await executor.execute_approved(proposal_id)

    assert result["filled_qty"] == 1
    assert result["filled_price"] == MOCK_PRICE
    events = await audit.read()
    submitted = next(event for event in events if event["event"] == "order_submitted")
    assert submitted["broker_result"]["filled_qty"] == 1
    assert submitted["fresh_evaluation"]["allowed"] is True
