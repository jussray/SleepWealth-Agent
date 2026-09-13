from gate.live_money_readiness import live_money_readiness


def test_live_money_readiness_fails_closed_with_separate_receipts():
    receipt = live_money_readiness()

    assert receipt["event"] == "live_money_readiness_evaluated"
    assert receipt["ready"] is False
    assert receipt["execution_authorized"] is False
    assert len(receipt["fingerprint"]) == 64

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
