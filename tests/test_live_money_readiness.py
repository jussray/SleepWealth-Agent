import hashlib
import json

from gate.live_money_readiness import live_money_readiness


def _fingerprinted_receipt(payload: dict) -> dict:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return {**payload, "fingerprint": hashlib.sha256(canonical.encode("utf-8")).hexdigest()}


def _valid_adult_eligibility_receipt() -> dict:
    return _fingerprinted_receipt(
        {
            "event": "broker_account_eligibility_observed",
            "classification": "VERIFIED",
            "source": "broker-provider",
            "broker": "eligible-provider",
            "account_holder_age_verified": True,
            "minimum_age": 18,
            "trading_enabled": True,
            "live_money_allowed": True,
            "execution_authorized": False,
        }
    )


def test_live_money_readiness_fails_closed_with_separate_receipts():
    receipt = live_money_readiness()

    assert receipt["event"] == "live_money_readiness_evaluated"
    assert receipt["ready"] is False
    assert receipt["execution_authorized"] is False
    assert len(receipt["fingerprint"]) == 64
    assert receipt["external_readonly_observer"]["classification"] == "UNKNOWN"
    assert receipt["broker_eligibility"]["classification"] == "UNKNOWN"

    checks = receipt["checks"]
    codes = [check["code"] for check in checks]
    assert len(codes) == len(set(codes))
    assert codes == [
        "LIVE_EXECUTION_MODE",
        "REAL_MONEY_EFFECT_CLASS",
        "EXTERNAL_BROKER_ADAPTER",
        "ADULT_ACCOUNT_ELIGIBILITY",
        "BROKER_ACCOUNT_ELIGIBILITY",
        "LIVE_BROKER_SESSION_RECEIPT",
    ]
    assert all(check["blocking"] is True for check in checks)

    classifications = {check["code"]: check["classification"] for check in checks}
    assert classifications == {
        "LIVE_EXECUTION_MODE": "BLOCKED",
        "REAL_MONEY_EFFECT_CLASS": "BLOCKED",
        "EXTERNAL_BROKER_ADAPTER": "BLOCKED",
        "ADULT_ACCOUNT_ELIGIBILITY": "UNKNOWN",
        "BROKER_ACCOUNT_ELIGIBILITY": "UNKNOWN",
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
        "ADULT_ACCOUNT_ELIGIBILITY",
        "BROKER_ACCOUNT_ELIGIBILITY",
        "LIVE_BROKER_SESSION_RECEIPT",
    ]


def test_broker_eligibility_is_provider_scoped_and_non_authorizing():
    receipt = live_money_readiness()
    eligibility = next(
        check for check in receipt["checks"] if check["code"] == "BROKER_ACCOUNT_ELIGIBILITY"
    )

    assert eligibility["classification"] == "UNKNOWN"
    assert eligibility["source"] == "broker-provider-authority"
    assert "unrelated product" in eligibility["reason"]
    assert "repository" in eligibility["reason"]
    assert "platform-account" in eligibility["reason"]
    assert receipt["execution_authorized"] is False


def test_provider_verified_18_plus_account_clears_only_eligibility_gates():
    receipt = live_money_readiness(
        broker_eligibility_receipt=_valid_adult_eligibility_receipt()
    )

    classifications = {check["code"]: check["classification"] for check in receipt["checks"]}
    assert classifications["ADULT_ACCOUNT_ELIGIBILITY"] == "VERIFIED"
    assert classifications["BROKER_ACCOUNT_ELIGIBILITY"] == "VERIFIED"
    assert receipt["broker_eligibility"]["classification"] == "VERIFIED_ELIGIBLE_ADULT_ACCOUNT"
    assert receipt["broker_eligibility"]["minimum_age"] == 18
    assert receipt["execution_authorized"] is False
    assert receipt["ready"] is False
    assert "ADULT_ACCOUNT_ELIGIBILITY" not in receipt["blockers"]
    assert "BROKER_ACCOUNT_ELIGIBILITY" not in receipt["blockers"]
    assert "LIVE_EXECUTION_MODE" in receipt["blockers"]


def test_self_attested_or_underage_receipt_cannot_clear_adult_gate():
    forged = _fingerprinted_receipt(
        {
            "event": "broker_account_eligibility_observed",
            "classification": "VERIFIED",
            "source": "self-attested",
            "broker": "eligible-provider",
            "account_holder_age_verified": True,
            "minimum_age": 17,
            "trading_enabled": True,
            "live_money_allowed": True,
            "execution_authorized": False,
        }
    )

    receipt = live_money_readiness(broker_eligibility_receipt=forged)

    assert receipt["broker_eligibility"]["classification"] == "INVALID"
    assert receipt["broker_eligibility"]["accepted"] is False
    assert "ADULT_ACCOUNT_ELIGIBILITY" in receipt["blockers"]
    assert "BROKER_ACCOUNT_ELIGIBILITY" in receipt["blockers"]
    assert receipt["execution_authorized"] is False
