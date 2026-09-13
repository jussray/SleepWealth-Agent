from datetime import datetime, timezone
import json

import pytest

from broker.ibkr_readonly import IBKRReadOnlyObserver, IBKRReadOnlyObserverError
from gate.live_money_readiness import live_money_readiness


class FakeIB:
    def __init__(self):
        self.connected = False
        self.disconnected = False
        self.connect_kwargs = None

    async def connectAsync(self, host, port, **kwargs):
        self.connect_kwargs = {"host": host, "port": port, **kwargs}
        self.connected = True

    def isConnected(self):
        return self.connected and not self.disconnected

    def managedAccounts(self):
        return ["U1234567", "U7654321"]

    async def reqCurrentTimeAsync(self):
        return datetime(2026, 9, 13, 22, 0, tzinfo=timezone.utc)

    def disconnect(self):
        self.disconnected = True


@pytest.mark.asyncio
async def test_readonly_observer_requests_readonly_and_redacts_accounts():
    fake = FakeIB()
    observer = IBKRReadOnlyObserver(client_factory=lambda: fake)

    receipt = await observer.observe()

    assert fake.connect_kwargs["readonly"] is True
    assert fake.connect_kwargs["clientId"] == 91
    assert receipt["event"] == "ibkr_readonly_session_observed"
    assert receipt["classification"] == "OBSERVED"
    assert receipt["connected"] is True
    assert receipt["execution_authorized"] is False
    assert receipt["readonly_requested"] is True
    assert receipt["provider_readonly_enforcement"] == "UNKNOWN"
    assert receipt["account_count"] == 2
    assert len(receipt["account_fingerprints"]) == 2
    assert all(len(value) == 64 for value in receipt["account_fingerprints"])
    assert len(receipt["fingerprint"]) == 64
    assert fake.disconnected is True

    rendered = json.dumps(receipt)
    assert "U1234567" not in rendered
    assert "U7654321" not in rendered

    checks = {check["code"]: check for check in receipt["checks"]}
    assert checks["SESSION_CONNECTIVITY"]["classification"] == "VERIFIED"
    assert checks["MANAGED_ACCOUNT_VISIBILITY"]["classification"] == "VERIFIED"
    assert checks["TWS_READ_ONLY_ENFORCEMENT"]["classification"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_readonly_observer_refuses_non_loopback_endpoint_before_connect():
    fake = FakeIB()
    observer = IBKRReadOnlyObserver(host="example.com", client_factory=lambda: fake)

    with pytest.raises(IBKRReadOnlyObserverError, match="loopback"):
        await observer.observe()

    assert fake.connect_kwargs is None


@pytest.mark.asyncio
async def test_readonly_observer_refuses_client_id_zero():
    observer = IBKRReadOnlyObserver(client_id=0, client_factory=FakeIB)

    with pytest.raises(IBKRReadOnlyObserverError, match="client_id"):
        await observer.observe()


def test_readonly_session_evidence_does_not_unlock_live_money():
    async def build_receipt():
        return await IBKRReadOnlyObserver(client_factory=FakeIB).observe()

    import asyncio

    observer_receipt = asyncio.run(build_receipt())
    readiness = live_money_readiness(observer_receipt)

    assert readiness["external_readonly_observer"]["classification"] == "VERIFIED_OBSERVATION"
    assert readiness["external_readonly_observer"]["accepted"] is True
    assert readiness["ready"] is False
    assert readiness["execution_authorized"] is False

    classifications = {
        check["code"]: check["classification"] for check in readiness["checks"]
    }
    assert classifications["LIVE_EXECUTION_MODE"] == "BLOCKED"
    assert classifications["REAL_MONEY_EFFECT_CLASS"] == "BLOCKED"
    assert classifications["EXTERNAL_BROKER_ADAPTER"] == "BLOCKED"
    assert classifications["LIVE_BROKER_SESSION_RECEIPT"] == "UNKNOWN"
