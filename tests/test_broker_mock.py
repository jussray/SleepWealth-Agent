import pytest

from broker.base import Order
from broker.mock import MockBroker


@pytest.mark.asyncio
async def test_connect():
    broker = MockBroker(initial_cash=10_000)
    assert await broker.connect() is True
    assert broker.cash == 10_000


@pytest.mark.asyncio
async def test_buy_fills_and_debits_cash():
    broker = MockBroker(initial_cash=10_000)
    await broker.connect()
    result = await broker.submit_order(Order("AAPL", 10, "buy"))
    assert result["status"] == "filled"
    assert broker.cash == 10_000 - 1_000
    assert broker.positions["AAPL"] == 10


@pytest.mark.asyncio
async def test_insufficient_cash_rejected():
    broker = MockBroker(initial_cash=100)
    await broker.connect()
    result = await broker.submit_order(Order("AAPL", 10, "buy"))
    assert result["status"] == "rejected"
    assert "insufficient cash" in result["reason"]


@pytest.mark.asyncio
async def test_sell_without_position_rejected():
    broker = MockBroker(initial_cash=10_000)
    await broker.connect()
    result = await broker.submit_order(Order("AAPL", 5, "sell"))
    assert result["status"] == "rejected"


@pytest.mark.asyncio
async def test_zero_qty_rejected():
    broker = MockBroker()
    await broker.connect()
    result = await broker.submit_order(Order("AAPL", 0, "buy"))
    assert result["status"] == "rejected"


@pytest.mark.asyncio
async def test_cancel_all_marks_only_working_orders_cancelled_and_preserves_evidence():
    broker = MockBroker()
    await broker.connect()
    broker.orders = {
        "MOCK-WORKING": {"status": "Submitted"},
        "MOCK-FILLED": {"status": "filled", "filled_price": 100.0},
    }

    assert await broker.cancel_all() is True

    working = await broker.get_order_status("MOCK-WORKING")
    filled = await broker.get_order_status("MOCK-FILLED")
    assert working["status"] == "Cancelled"
    assert working["cancelled_at"] is not None
    assert filled["status"] == "filled"
    assert filled["filled_price"] == 100.0
    assert await broker.cancel_all() is False


def test_mock_is_paper_only():
    assert MockBroker().is_paper_only() is True
