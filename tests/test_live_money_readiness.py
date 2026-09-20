import hashlib
import hmac
import json
from datetime import datetime, timezone

from gate.live_money_readiness import live_money_readiness
from gate.provider_session import mint_provider_session_receipt

ELIGIBILITY_KEY = b"sleepwealth-test-eligibility-key-32-bytes!!"
ELIGIBILITY_ISSUER = "test-broker-control-plane"
SESSION_KEY = b"sleepwealth-test-provider-session-key-32bytes"
SESSION_ISSUER = "test-sleepwealth-runtime"
EVALUATED_AT = datetime(2026, 9, 20, 4, 0, tzinfo=timezone.utc)
DEFAULT_ACCOUNT_FP = hashlib.sha256(b"provider-account-123").hexdigest()


def _canonical_payload(payload: dict) -> bytes:
    canonical_payload = dict(payload)
    canonical_payload.pop("fingerprint", None)
    canonical_payload.pop("receipt_auth", None)
    canonical = json.dumps(
        canonical_payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return canonical.encode("utf-8")


def _fingerprinted_receipt(payload: dict) -> dict:
    return {
        **payload,
        "fingerprint": hashlib.sha256(_canonical_payload(payload)).hexdigest(),
    }


def _signed_adult_eligibility_receipt(**overrides) -> dict:
    payload = {
        "event": "broker_account_eligibility_observed",
        "classification": "VERIFIED",
        "source": "broker-provider",
        "issuer_id": ELIGIBILITY_ISSUER,
        "broker": "eligible-provider",
        "account_fingerprint": DEFAULT_ACCOUNT_FP,
        "account_holder_age_verified": True,
        "minimum_age": 18,
        "trading_enabled": True,
        "live_money_allowed": True,
        "execution_authorized": False,
        "issued_at": "2026-09-20T03:55:00+00:00",
        "expires_at": "2026-09-20T04:55:00+00:00",
    }
    payload.update(overrides)
    receipt = _fingerprinted_receipt(payload)
    receipt["receipt_auth"] = hmac.new(
        ELIGIBILITY_KEY,
        _canonical_payload(receipt),
        hashlib.sha256,
    ).hexdigest()
    return receipt


def _signed_live_session(
    *,
    provider="alpaca",
    account_fingerprint=DEFAULT_ACCOUNT_FP,
    permissions=None,
):
    observation = {
        "event": "provider_live_account_observed",
        "classification": "OBSERVED",
        "provider": provider,
        "environment": "live",
        "connected": True,
        "account_fingerprint": account_fingerprint,
        "account_status": "ACTIVE",
        "crypto_status": "ACTIVE",
        "account_blocked": False,
        "trading_blocked": False,
        "trade_suspended_by_user": False,
        "asset_permissions": permissions or ["stock-market", "crypto"],
        "observed_at": EVALUATED_AT.isoformat(),
        "execution_authorized": False,
        "order_submit_capability": False,
        "observation_fingerprint": hashlib.sha256(b"provider-observation").hexdigest(),
    }
    return mint_provider_session_receipt(
        observation,
        issuer_id=SESSION_ISSUER,
        receipt_key=SESSION_KEY,
        issued_at=EVALUATED_AT,
    )


def _readiness(
    receipt=None,
    *,
    keys=None,
    live_session=None,
    session_keys=None,
    evaluated_at=EVALUATED_AT,
):
    return live_money_readiness(
        broker_eligibility_receipt=receipt,
        live_provider_session_receipt=live_session,
        trusted_eligibility_keys=keys,
        trusted_session_keys=session_keys,
        evaluated_at=evaluated_at,
    )


def test_live_money_readiness_fails_closed_with_separate_receipts():
    receipt = live_money_readiness()

    assert receipt["event"] == "live_money_readiness_evaluated"
    assert receipt["ready"] is False
    assert receipt["execution_authorized"] is False
    assert len(receipt["fingerprint"]) == 64
    assert receipt["external_readonly_observer"]["classification"] == "UNKNOWN"
    assert receipt["broker_eligibility"]["classification"] == "UNKNOWN"
    assert receipt["live_provider_session"]["classification"] == "UNKNOWN"

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


def test_trusted_provider_verified_18_plus_account_clears_only_eligibility_gates():
    receipt = _readiness(
        _signed_adult_eligibility_receipt(),
        keys={ELIGIBILITY_ISSUER: ELIGIBILITY_KEY},
    )

    classifications = {
        check["code"]: check["classification"] for check in receipt["checks"]
    }
    assert classifications["ADULT_ACCOUNT_ELIGIBILITY"] == "VERIFIED"
    assert classifications["BROKER_ACCOUNT_ELIGIBILITY"] == "VERIFIED"
    assert (
        receipt["broker_eligibility"]["classification"]
        == "VERIFIED_ELIGIBLE_ADULT_ACCOUNT"
    )
    assert receipt["broker_eligibility"]["minimum_age"] == 18
    assert len(receipt["broker_eligibility"]["account_fingerprint"]) == 64
    assert receipt["execution_authorized"] is False
    assert receipt["ready"] is False
    assert "ADULT_ACCOUNT_ELIGIBILITY" not in receipt["blockers"]
    assert "BROKER_ACCOUNT_ELIGIBILITY" not in receipt["blockers"]
    assert "LIVE_BROKER_SESSION_RECEIPT" in receipt["blockers"]


def test_same_provider_and_account_session_clears_only_live_session_gate():
    eligibility = _signed_adult_eligibility_receipt(
        broker="alpaca",
        account_fingerprint=DEFAULT_ACCOUNT_FP,
    )
    session = _signed_live_session(
        provider="alpaca",
        account_fingerprint=DEFAULT_ACCOUNT_FP,
    )

    receipt = _readiness(
        eligibility,
        keys={ELIGIBILITY_ISSUER: ELIGIBILITY_KEY},
        live_session=session,
        session_keys={SESSION_ISSUER: SESSION_KEY},
    )

    classifications = {
        check["code"]: check["classification"] for check in receipt["checks"]
    }
    assert classifications["ADULT_ACCOUNT_ELIGIBILITY"] == "VERIFIED"
    assert classifications["BROKER_ACCOUNT_ELIGIBILITY"] == "VERIFIED"
    assert classifications["LIVE_BROKER_SESSION_RECEIPT"] == "VERIFIED"
    assert receipt["live_provider_session"]["classification"] == "VERIFIED_LIVE_SESSION"
    assert "LIVE_BROKER_SESSION_RECEIPT" not in receipt["blockers"]
    assert "LIVE_EXECUTION_MODE" in receipt["blockers"]
    assert "REAL_MONEY_EFFECT_CLASS" in receipt["blockers"]
    assert "EXTERNAL_BROKER_ADAPTER" in receipt["blockers"]
    assert receipt["ready"] is False
    assert receipt["execution_authorized"] is False


def test_live_session_for_different_account_is_conflict_not_green():
    eligibility = _signed_adult_eligibility_receipt(
        broker="alpaca",
        account_fingerprint=DEFAULT_ACCOUNT_FP,
    )
    session = _signed_live_session(
        provider="alpaca",
        account_fingerprint=hashlib.sha256(b"different-account").hexdigest(),
    )

    receipt = _readiness(
        eligibility,
        keys={ELIGIBILITY_ISSUER: ELIGIBILITY_KEY},
        live_session=session,
        session_keys={SESSION_ISSUER: SESSION_KEY},
    )
    check = next(
        item for item in receipt["checks"] if item["code"] == "LIVE_BROKER_SESSION_RECEIPT"
    )
    assert check["classification"] == "CONFLICT"
    assert "different" in check["reason"]
    assert "LIVE_BROKER_SESSION_RECEIPT" in receipt["blockers"]
    assert receipt["execution_authorized"] is False


def test_live_session_for_different_provider_is_conflict_not_green():
    eligibility = _signed_adult_eligibility_receipt(
        broker="alpaca",
        account_fingerprint=DEFAULT_ACCOUNT_FP,
    )
    session = _signed_live_session(
        provider="another-provider",
        account_fingerprint=DEFAULT_ACCOUNT_FP,
    )

    receipt = _readiness(
        eligibility,
        keys={ELIGIBILITY_ISSUER: ELIGIBILITY_KEY},
        live_session=session,
        session_keys={SESSION_ISSUER: SESSION_KEY},
    )
    check = next(
        item for item in receipt["checks"] if item["code"] == "LIVE_BROKER_SESSION_RECEIPT"
    )
    assert check["classification"] == "CONFLICT"
    assert "LIVE_BROKER_SESSION_RECEIPT" in receipt["blockers"]


def test_hash_only_provider_claim_cannot_mint_adult_trust():
    unsigned = _signed_adult_eligibility_receipt()
    unsigned.pop("receipt_auth")

    receipt = _readiness(unsigned, keys={ELIGIBILITY_ISSUER: ELIGIBILITY_KEY})

    assert receipt["broker_eligibility"]["classification"] == "UNTRUSTED"
    assert receipt["broker_eligibility"]["accepted"] is False
    assert "ADULT_ACCOUNT_ELIGIBILITY" in receipt["blockers"]


def test_unknown_issuer_or_wrong_key_cannot_clear_adult_gate():
    signed = _signed_adult_eligibility_receipt()

    missing_issuer = _readiness(signed, keys={"another-issuer": ELIGIBILITY_KEY})
    wrong_key = _readiness(
        signed,
        keys={ELIGIBILITY_ISSUER: b"x" * 32},
    )

    assert missing_issuer["broker_eligibility"]["classification"] == "UNTRUSTED"
    assert wrong_key["broker_eligibility"]["classification"] == "UNTRUSTED"
    assert missing_issuer["execution_authorized"] is False
    assert wrong_key["execution_authorized"] is False


def test_expired_adult_eligibility_receipt_is_stale_not_verified():
    expired = _signed_adult_eligibility_receipt(
        issued_at="2026-09-18T02:00:00+00:00",
        expires_at="2026-09-18T03:00:00+00:00",
    )

    receipt = _readiness(expired, keys={ELIGIBILITY_ISSUER: ELIGIBILITY_KEY})

    assert receipt["broker_eligibility"]["classification"] == "STALE"
    assert receipt["broker_eligibility"]["accepted"] is False
    assert "ADULT_ACCOUNT_ELIGIBILITY" in receipt["blockers"]
    assert "BROKER_ACCOUNT_ELIGIBILITY" in receipt["blockers"]


def test_self_attested_or_underage_receipt_cannot_clear_adult_gate():
    forged = _signed_adult_eligibility_receipt(
        source="self-attested",
        minimum_age=17,
    )

    receipt = _readiness(
        forged,
        keys={ELIGIBILITY_ISSUER: ELIGIBILITY_KEY},
    )

    assert receipt["broker_eligibility"]["classification"] == "INVALID"
    assert receipt["broker_eligibility"]["accepted"] is False
    assert "ADULT_ACCOUNT_ELIGIBILITY" in receipt["blockers"]
    assert "BROKER_ACCOUNT_ELIGIBILITY" in receipt["blockers"]
    assert receipt["execution_authorized"] is False
