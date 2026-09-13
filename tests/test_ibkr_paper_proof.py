"""IBKR adapter must remain provably paper-only at every boundary."""

from types import SimpleNamespace

import pytest

from broker.base import Order
from broker.ibkr import IBKRBroker, PaperModeViolation


def test_paper_requires_all_three_signals():
    broker = IBKRBroker(paper_mode=True, port=4002)
    broker.managed_accounts = ["DU1234567"]
    assert broker.is_paper_only() is True

    broker.managed_accounts = ["U1234567"]
    assert broker.is_paper_only() is False

    broker.managed_accounts = ["DU1234567", "U999"]
    assert broker.is_paper_only() is False


def test_direct_live_construction_is_blocked_even_without_factory():
    with pytest.raises(PaperModeViolation, match="Live IBKR construction is disabled"):
        IBKRBroker(paper_mode=False, port=4001)


def test_live_port_is_blocked_at_construction():
    with pytest.raises(PaperModeViolation, match="requires a paper port"):
        IBKRBroker(paper_mode=True, port=4001)


def test_paper_proof_is_explicit():
    broker = IBKRBroker(paper_mode=True, port=4002)
    broker.managed_accounts = ["DU1"]
    proof = broker.paper_proof()
    assert proof["provably_paper"] is True
    assert proof["all_accounts_paper"] is True
    assert proof["port_is_paper"] is True


def test_factory_knows_ibkr():
    from broker.factory import KNOWN_BROKERS

    assert "ibkr" in KNOWN_BROKERS


def test_require_connection_checks_real_socket_state():
    broker = IBKRBroker()
    broker.managed_accounts = ["DU1"]
    broker._connected = True
    broker.ib = SimpleNamespace(isConnected=lambda: False)

    with pytest.raises(RuntimeError, match="Reconnect and re-prove paper mode"):
        broker._require_connection()

    assert broker._connected is False


def test_require_connection_disconnects_if_paper_proof_changes():
    disconnected = {"value": False}

    class FakeIB:
        @staticmethod
        def isConnected():
            return True

        @staticmethod
        def disconnect():
            disconnected["value"] = True

    broker = IBKRBroker()
    broker.ib = FakeIB()
    broker._connected = True
    broker.managed_accounts = ["U-LIVE"]

    with pytest.raises(PaperModeViolation, match="no longer satisfies the paper proof"):
        broker._require_connection()

    assert broker._connected is False
    assert disconnected["value"] is True


@pytest.mark.asyncio
async def test_submit_order_rejects_unknown_side_before_importing_ib_async():
    class FakeIB:
        @staticmethod
        def isConnected():
            return True

    broker = IBKRBroker()
    broker.ib = FakeIB()
    broker._connected = True
    broker.managed_accounts = ["DU1"]
    broker.account = "DU1"

    result = await broker.submit_order(Order(symbol="AAPL", qty=1, side="hold"))

    assert result == {"status": "rejected", "reason": "side must be 'buy' or 'sell'"}


@pytest.mark.asyncio
async def test_submit_order_rejects_nonpositive_cash_quantity_before_importing_ib_async():
    class FakeIB:
        @staticmethod
        def isConnected():
            return True

    broker = IBKRBroker()
    broker.ib = FakeIB()
    broker._connected = True
    broker.managed_accounts = ["DU1"]
    broker.account = "DU1"

    result = await broker.submit_order(
        Order(symbol="AAPL", qty=0, side="buy"), cash_qty=0
    )

    assert result == {"status": "rejected", "reason": "cash_qty must be > 0"}


@pytest.mark.asyncio
async def test_quote_fallback_preserves_zero_instead_of_truthiness_fallback(monkeypatch):
    class FakeTicker:
        last = 0.0
        close = 123.45
        bid = 0.0
        ask = 0.0

        @staticmethod
        def marketPrice():
            return 222.0

    class FakeIB:
        @staticmethod
        def isConnected():
            return True

        @staticmethod
        async def reqTickersAsync(_contract):
            return [FakeTicker()]

    broker = IBKRBroker(request_interval_seconds=0)
    broker.ib = FakeIB()
    broker._connected = True
    broker.managed_accounts = ["DU1"]
    broker.account = "DU1"

    async def fake_qualify(_symbol):
        return object()

    monkeypatch.setattr(broker, "_qualify", fake_qualify)

    quote = await broker.get_market_data("AAPL")

    assert quote["price"] == 0.0
    assert quote["bid"] == 0.0
    assert quote["ask"] == 0.0
