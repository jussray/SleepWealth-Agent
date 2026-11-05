"""Account-scoped readiness requires independent provider-session proof."""
import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from execution.account_models import AccountModel, CUSTOMER_GATES, POOLED_GATES
from execution.receipt_issuer import mint_scope_receipts
from gate.account_scope_preflight import evaluate_bound_account_preflight
from gate.provider_session import mint_provider_session_receipt

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
ACCOUNT_KEY = b"account-scope-test-signing-key-of-32bytes"
SESSION_KEY = b"independent-provider-session-key-of-32bytes"
ACCOUNT_ISSUER = "account-authority"
SESSION_ISSUER = "provider-observer"
NOT_PROVIDED = object()
ACCOUNT_FP = hashlib.sha256(b"alpaca-account-a").hexdigest()
OTHER_FP = hashlib.sha256(b"alpaca-account-b").hexdigest()


def observed(fp=ACCOUNT_FP, provider="alpaca", permissions=None, blocked=False):
    payload = {
        "event": "provider_live_account_observed",
        "classification": "OBSERVED",
        "provider": provider,
        "environment": "live",
        "connected": True,
        "account_fingerprint": fp,
        "account_status": "ACTIVE",
        "crypto_status": "ACTIVE",
        "account_blocked": blocked,
        "trading_blocked": False,
        "trade_suspended_by_user": False,
        "asset_permissions": ["stock-market"] if permissions is None else permissions,
        "observed_at": NOW.isoformat(),
        "execution_authorized": False,
        "order_submit_capability": False,
    }
    payload["observation_fingerprint"] = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    ).hexdigest()
    return payload


def scope(model=AccountModel.CUSTOMER_CONNECTED, fp=ACCOUNT_FP):
    gates = CUSTOMER_GATES if model is AccountModel.CUSTOMER_CONNECTED else POOLED_GATES
    subject = "customer-a" if model is AccountModel.CUSTOMER_CONNECTED else "pool-a"
    return subject, mint_scope_receipts(
        gates=gates, model=model, subject=subject, account_binding=fp,
        issuer=ACCOUNT_ISSUER, key=ACCOUNT_KEY, now=NOW, capital_ceiling=1000.0,
    )


def preflight(*, model=AccountModel.CUSTOMER_CONNECTED, scope_fp=ACCOUNT_FP,
              session_fp=ACCOUNT_FP, provider="alpaca", expected_provider="alpaca",
              required_lane="stock-market", session_keys=None, receipt_override=NOT_PROVIDED,
              permissions=None, blocked=False):
    subject, receipts = scope(model=model, fp=scope_fp)
    session = mint_provider_session_receipt(
        observed(fp=session_fp, provider=provider, permissions=permissions, blocked=blocked),
        issuer_id=SESSION_ISSUER, receipt_key=SESSION_KEY, issued_at=NOW,
    )
    return evaluate_bound_account_preflight(
        model=model, subject=subject, capital_ceiling=1000.0,
        scope_receipts=receipts, account_receipt_key=ACCOUNT_KEY,
        trusted_account_issuers=[ACCOUNT_ISSUER],
        provider_session_receipt=session if receipt_override is NOT_PROVIDED else receipt_override,
        trusted_provider_session_keys={SESSION_ISSUER: SESSION_KEY} if session_keys is None else session_keys,
        expected_provider=expected_provider, required_lane=required_lane,
        now=NOW + timedelta(seconds=30),
    )


@pytest.mark.parametrize("model", [AccountModel.CUSTOMER_CONNECTED, AccountModel.POOLED_MANAGED])
def test_verified_provider_session_and_signed_account_scope_are_eligible(model):
    r = preflight(model=model)
    assert r["status"] == "ELIGIBLE_FOR_LIVE_GATE_REVIEW"
    assert r["live_execution_authorized"] is False
    assert r["authorizes_real_money"] is False
    assert r["account_binding"] == ACCOUNT_FP


def test_provider_session_for_other_account_is_rejected():
    r = preflight(session_fp=OTHER_FP)
    assert r["status"] == "BLOCKED"
    assert r["reason"] == "account_binding_mismatch"


def test_provider_cannot_be_switched_by_request():
    r = preflight(expected_provider="ibkr")
    assert r["status"] == "BLOCKED"
    assert r["reason"] == "provider_mismatch"


def test_unsigned_or_untrusted_provider_session_cannot_activate_scope():
    r = preflight(session_keys={"unknown-issuer": SESSION_KEY})
    assert r["status"] == "BLOCKED"
    assert r["reason"] == "provider_session_unverified"


def test_wrong_permission_does_not_satisfy_requested_lane():
    r = preflight(required_lane="crypto")
    assert r["status"] == "BLOCKED"
    assert r["reason"] == "lane_not_permitted"


def test_malformed_and_missing_session_receipts_are_rejected():
    for receipt in (None, "not-a-receipt", {"event": "broker_live_session_observed"}):
        r = preflight(receipt_override=receipt)
        assert r["status"] == "BLOCKED"
        assert r["live_execution_authorized"] is False


def test_expired_provider_session_is_rejected():
    subject, receipts = scope()
    session = mint_provider_session_receipt(
        observed(), issuer_id=SESSION_ISSUER, receipt_key=SESSION_KEY, issued_at=NOW,
        ttl_seconds=60,
    )
    r = evaluate_bound_account_preflight(
        model=AccountModel.CUSTOMER_CONNECTED, subject=subject,
        capital_ceiling=1000.0, scope_receipts=receipts,
        account_receipt_key=ACCOUNT_KEY, trusted_account_issuers=[ACCOUNT_ISSUER],
        provider_session_receipt=session,
        trusted_provider_session_keys={SESSION_ISSUER: SESSION_KEY},
        expected_provider="alpaca", required_lane="stock-market",
        now=NOW + timedelta(seconds=61),
    )
    assert r["status"] == "BLOCKED"
    assert r["reason"] == "provider_session_unverified"


def test_untrusted_clock_fails_closed():
    subject, receipts = scope()
    r = evaluate_bound_account_preflight(
        model=AccountModel.CUSTOMER_CONNECTED, subject=subject,
        capital_ceiling=1000.0, scope_receipts=receipts,
        account_receipt_key=ACCOUNT_KEY, trusted_account_issuers=[ACCOUNT_ISSUER],
        provider_session_receipt=None, trusted_provider_session_keys={},
        expected_provider="alpaca", required_lane="stock-market",
        now=datetime(2030, 1, 1),
    )
    assert r["status"] == "REJECTED"
    assert r["reason"] == "trusted_clock_required"


def test_malformed_lane_is_rejected_without_raising():
    r = preflight(required_lane=["stock-market"])
    assert r["status"] == "REJECTED"
    assert r["reason"] == "unsupported_market_lane"
