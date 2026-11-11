import logging

from mcp_gateway.dispatcher import ProviderDispatcher


class _RecordingLedger:
    def __init__(self):
        self.calls = []

    def classify(self, provider, idempotency_key, state):
        self.calls.append((provider, idempotency_key, state))


class _FailingLedger:
    def classify(self, provider, idempotency_key, state):
        raise OSError("ledger write failed")


def _dispatcher(ledger):
    d = ProviderDispatcher.__new__(ProviderDispatcher)
    d.ledger = ledger
    return d


def test_reconcile_marker_is_written_with_the_dispatched_key():
    ledger = _RecordingLedger()
    _dispatcher(ledger)._record_reconcile_required("vybe", "idem-1")
    assert ledger.calls == [("vybe", "idem-1", "reconcile_required")]


def test_failed_reconcile_marker_is_logged_and_does_not_raise(caplog):
    with caplog.at_level(logging.ERROR, logger="mcp_gateway.dispatcher"):
        _dispatcher(_FailingLedger())._record_reconcile_required("vybe", "idem-2")
    messages = [record.getMessage() for record in caplog.records]
    assert any("could not record reconcile_required for provider=vybe" in m for m in messages)
