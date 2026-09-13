from gate.live_money_readiness import live_money_readiness


def test_live_money_readiness_fails_closed_with_separate_receipts():
    receipt = live_money_readiness()

    assert receipt["event"] == "live_money_readiness_evaluated"
    assert receipt["ready"] is False
    assert receipt["execution_authorized"] is False
    assert len(receipt["fingerprint"]) == 64
    assert receipt["external_readonly_observer"]["classification"] == "UNKNOWN"

    checks = receipt["checks"]
    codes = [check["code"] for check in checks]
    assert len(codes) == len(set(codes))
    assert codes == [
        "LIVE_EXECUTION_MODE",
        "REAL_MONEY_EFFECT_CLASS",
        "EXTERNAL_BROKER_ADAPTER",
        "LIVE_BROKER_SESSION_RECEIPT",
    ]
    assert all(check["blocking"] is True for check in checks)

    classifications = {check["code"]: check["classification"] for check in checks}
    assert classifications == {
        "LIVE_EXECUTION_MODE": "BLOCKED",
        "REAL_MONEY_EFFECT_CLASS": "BLOCKED",
        "EXTERNAL_BROKER_ADAPTER": "BLOCKED",
        "LIVE_BROKER_SESSION_RECEIPT": "UNKNOWN",
    }
    assert receipt["blockers"] == codes


def test_live_money_readiness_is_deterministic_and_non_authorizing():
    first = live_money_readiness()
    second = live_money_readiness()

    assert first["fingerprint"] == second["fingerprint"]
    assert first["execution_authorized"] is False
    assert second["execution_authorized"] is False
    assert "never grants" in first["truth"].lower()


def test_forged_observer_receipt_is_rejected_without_changing_blockers():
    forged = {
        "event": "ibkr_readonly_session_observed",
        "classification": "OBSERVED",
        "connected": True,
        "execution_authorized": False,
        "readonly_requested": True,
        "loopback_only": True,
        "fingerprint": "0" * 64,
    }

    receipt = live_money_readiness(forged)

    assert receipt["external_readonly_observer"]["classification"] == "INVALID"
    assert receipt["external_readonly_observer"]["accepted"] is False
    assert receipt["ready"] is False
    assert receipt["execution_authorized"] is False
    assert receipt["blockers"] == [
        "LIVE_EXECUTION_MODE",
        "REAL_MONEY_EFFECT_CLASS",
        "EXTERNAL_BROKER_ADAPTER",
        "LIVE_BROKER_SESSION_RECEIPT",
    ]
