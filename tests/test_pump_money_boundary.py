import pytest

from backend.pump_live_box_server import PumpLiveBoxSession
from broker.crypto_sandbox import CryptoSandboxBroker
from gate.pump_money_boundary import pump_money_boundary


_OVERRIDE_NAMES = (
    "SLEEPWEALTH_REAL_MONEY",
    "SLEEPWEALTH_LIVE_EXECUTION",
    "SLEEPWEALTH_PUMP_REAL_MONEY",
    "SLEEPWEALTH_PUMP_LIVE_EXECUTION",
    "SLEEPWEALTH_PUMP_WALLET",
    "SLEEPWEALTH_PUMP_BROKER",
)


def test_pump_money_boundary_ignores_live_override_attempts(monkeypatch):
    for name in _OVERRIDE_NAMES:
        monkeypatch.setenv(name, "SHOULD-NOT-BECOME-AUTHORITY")

    receipt = pump_money_boundary()

    assert receipt["classification"] == "BLOCKED"
    assert receipt["authority"] == "sandbox-simulation-only"
    assert receipt["execution_authorized"] is False
    assert receipt["real_money"] is False
    assert receipt["live_execution"] is False
    assert receipt["wallet_connection"] is False
    assert receipt["funding"] is False
    assert receipt["signing"] is False
    assert receipt["brokerage_order_submission"] is False
    assert receipt["attempted_override_names"] == sorted(_OVERRIDE_NAMES)
    assert receipt["override_effect"] == "none"
    assert "SHOULD-NOT-BECOME-AUTHORITY" not in str(receipt)
    assert len(receipt["fingerprint"]) == 64
    assert receipt["cookie"].startswith("pump-money-boundary-v1:")


def test_pump_money_boundary_fingerprint_changes_with_override_presence(monkeypatch):
    clean = pump_money_boundary()
    monkeypatch.setenv("SLEEPWEALTH_PUMP_REAL_MONEY", "1")
    attempted = pump_money_boundary()

    assert clean["fingerprint"] != attempted["fingerprint"]
    assert clean["cookie"] != attempted["cookie"]
    assert clean["execution_authorized"] is attempted["execution_authorized"] is False


@pytest.mark.asyncio
async def test_live_box_stays_crypto_sandbox_under_live_override_attempts(monkeypatch):
    for name in _OVERRIDE_NAMES:
        monkeypatch.setenv(name, "1")

    session = PumpLiveBoxSession(100, state_path=None, session_id="pump-boundary-test")
    wallet = await session.wallet()

    assert isinstance(session.broker, CryptoSandboxBroker)
    assert wallet["authority"] == "sandbox-simulation-only"
    assert wallet["real_money"] is False
    assert wallet["live_execution"] is False


def test_pump_live_box_source_does_not_consume_live_override_names():
    from pathlib import Path

    source = Path("backend/pump_live_box_server.py").read_text(encoding="utf-8")
    for name in _OVERRIDE_NAMES:
        assert name not in source
