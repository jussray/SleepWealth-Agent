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


def _clear_overrides(monkeypatch):
    for name in _OVERRIDE_NAMES:
        monkeypatch.delenv(name, raising=False)


def test_pump_money_boundary_ignores_live_override_attempts(monkeypatch):
    _clear_overrides(monkeypatch)
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
    _clear_overrides(monkeypatch)
    clean = pump_money_boundary()
    monkeypatch.setenv("SLEEPWEALTH_PUMP_REAL_MONEY", "1")
    attempted = pump_money_boundary()

    assert clean["attempted_override_names"] == []
    assert attempted["attempted_override_names"] == ["SLEEPWEALTH_PUMP_REAL_MONEY"]
    assert clean["fingerprint"] != attempted["fingerprint"]
    assert clean["cookie"] != attempted["cookie"]
    assert clean["execution_authorized"] is attempted["execution_authorized"] is False


@pytest.mark.asyncio
async def test_live_box_stays_crypto_sandbox_under_live_override_attempts(monkeypatch):
    _clear_overrides(monkeypatch)
    for name in _OVERRIDE_NAMES:
        monkeypatch.setenv(name, "1")

    session = PumpLiveBoxSession(100, state_path=None, session_id="pump-boundary-test")
    wallet = await session.wallet()
    boundary = session.boundary()

    assert isinstance(session.broker, CryptoSandboxBroker)
    assert boundary["attempted_override_names"] == sorted(_OVERRIDE_NAMES)
    assert boundary["override_effect"] == "none"
    assert boundary["execution_authorized"] is False
    assert wallet["authority"] == "sandbox-simulation-only"
    assert wallet["real_money"] is False
    assert wallet["live_execution"] is False


def test_live_box_construction_fails_closed_if_boundary_contract_changes(monkeypatch):
    _clear_overrides(monkeypatch)
    unsafe = pump_money_boundary()
    unsafe["execution_authorized"] = True
    monkeypatch.setattr("backend.pump_live_box_server.pump_money_boundary", lambda: unsafe)

    with pytest.raises(RuntimeError, match="Pump money boundary invariant changed"):
        PumpLiveBoxSession(100, state_path=None, session_id="pump-boundary-unsafe-test")


@pytest.mark.asyncio
async def test_live_box_blocks_approval_when_money_boundary_fingerprint_changes(monkeypatch):
    _clear_overrides(monkeypatch)
    session = PumpLiveBoxSession(100, state_path=None, session_id="pump-boundary-drift-test")
    evidence = {
        "source_url": "https://pump.fun/coin/MOM8",
        "symbol": "MOM8",
        "mint": "MOM8-DEMO-MINT",
        "price": 0.5,
        "observed_at": "2026-09-14T08:00:00Z",
    }
    proposal = await session.propose(evidence, 10, "buy")
    assert proposal["evaluation"]["pump_money_boundary_fingerprint"] == proposal["money_boundary"]["fingerprint"]

    monkeypatch.setenv("SLEEPWEALTH_PUMP_LIVE_EXECUTION", "1")
    blocked = await session.approve(proposal["proposal_id"])
    wallet = await session.wallet()

    assert blocked["status"] == "blocked"
    assert blocked["money_boundary_changed"] is True
    assert blocked["money_boundary"]["attempted_override_names"] == [
        "SLEEPWEALTH_PUMP_LIVE_EXECUTION"
    ]
    assert blocked["authority"] == "none"
    assert blocked["real_money"] is False
    assert blocked["live_execution"] is False
    assert wallet["cash"] == pytest.approx(100.0)


def test_pump_live_box_source_does_not_consume_live_override_names():
    from pathlib import Path

    source = Path("backend/pump_live_box_server.py").read_text(encoding="utf-8")
    for name in _OVERRIDE_NAMES:
        assert name not in source
