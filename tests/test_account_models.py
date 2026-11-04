from datetime import datetime, timedelta, timezone

import pytest

from execution.account_models import (
    CUSTOMER_GATES,
    POOLED_GATES,
    AccountModel,
    evaluate_account_scope,
    sign_receipt,
    verify_gate_receipt,
)

KEY = b"k" * 32
ISSUER = "trusted-runtime"
NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _receipt(gate, subject, *, key=KEY, expires=None, issuer=ISSUER):
    fields = {
        "gate": gate,
        "subject": subject,
        "issued_by": issuer,
        "expires_at": (expires or (NOW + timedelta(days=1))).isoformat(),
    }
    return {**fields, "signature": sign_receipt(fields, key)}


def _all(gates, subject, **kw):
    return [_receipt(g, subject, **kw) for g in gates]


def _eval(model, subject, receipts, **kw):
    return evaluate_account_scope(
        model=model,
        subject=subject,
        receipts=receipts,
        key=KEY,
        now=NOW,
        trusted_issuers=[ISSUER],
        capital_ceiling=kw.pop("capital_ceiling", 5000.0),
        **kw,
    )


def test_no_receipts_blocks_and_lists_every_missing_gate():
    r = _eval(AccountModel.CUSTOMER_CONNECTED, "cust-1", [])
    assert r["status"] == "BLOCKED"
    assert r["missing_or_invalid_gates"] == sorted(CUSTOMER_GATES)
    assert r["live_execution_authorized"] is False


def test_customer_scope_eligible_only_with_all_customer_receipts():
    r = _eval(AccountModel.CUSTOMER_CONNECTED, "cust-1", _all(CUSTOMER_GATES, "cust-1"))
    assert r["status"] == "ELIGIBLE_FOR_LIVE_GATE_REVIEW"
    assert r["live_execution_authorized"] is False
    assert r["authorizes_real_money"] is False


def test_pooled_gates_cannot_be_satisfied_by_customer_receipts():
    r = _eval(AccountModel.POOLED_MANAGED, "pool-1", _all(CUSTOMER_GATES, "pool-1"))
    assert r["status"] == "BLOCKED"
    assert set(r["missing_or_invalid_gates"]) == set(POOLED_GATES)


def test_customer_receipts_for_another_customer_are_rejected():
    r = _eval(AccountModel.CUSTOMER_CONNECTED, "cust-2", _all(CUSTOMER_GATES, "cust-1"))
    assert r["status"] == "BLOCKED"
    assert all("subject_mismatch" in reason for reason in r["reasons"])


def test_expired_receipt_is_rejected():
    receipts = _all(CUSTOMER_GATES, "cust-1")
    receipts[0] = _receipt(CUSTOMER_GATES[0], "cust-1", expires=NOW - timedelta(seconds=1))
    r = _eval(AccountModel.CUSTOMER_CONNECTED, "cust-1", receipts)
    assert r["status"] == "BLOCKED"
    assert "customer_consent:receipt_expired" in r["reasons"]


def test_tampered_receipt_fails_signature():
    receipts = _all(CUSTOMER_GATES, "cust-1")
    receipts[1] = {**receipts[1], "subject": "cust-1", "expires_at": (NOW + timedelta(days=9)).isoformat()}
    r = _eval(AccountModel.CUSTOMER_CONNECTED, "cust-1", receipts)
    assert "broker_oauth_grant:signature_invalid" in r["reasons"]


def test_receipt_signed_with_wrong_key_fails():
    receipts = _all(CUSTOMER_GATES, "cust-1", key=b"x" * 32)
    r = _eval(AccountModel.CUSTOMER_CONNECTED, "cust-1", receipts)
    assert r["status"] == "BLOCKED"
    assert all("signature_invalid" in reason for reason in r["reasons"])


def test_untrusted_issuer_is_rejected():
    receipts = _all(CUSTOMER_GATES, "cust-1", issuer="random-caller")
    r = _eval(AccountModel.CUSTOMER_CONNECTED, "cust-1", receipts)
    assert all("untrusted_issuer" in reason for reason in r["reasons"])


def test_short_or_missing_trusted_key_fails_closed():
    receipts = _all(CUSTOMER_GATES, "cust-1")
    assert verify_gate_receipt(receipts[0], gate=CUSTOMER_GATES[0], subject="cust-1",
                                key=b"short", now=NOW, trusted_issuers=[ISSUER]) == "trusted_key_missing_or_short"
    with pytest.raises(ValueError):
        sign_receipt({"a": 1}, b"short")


@pytest.mark.parametrize("ceiling", [0, -1, float("nan"), float("inf"), True, "100"])
def test_capital_ceiling_must_be_positive_finite_number(ceiling):
    r = evaluate_account_scope(
        model=AccountModel.CUSTOMER_CONNECTED, subject="cust-1",
        receipts=_all(CUSTOMER_GATES, "cust-1"), key=KEY, now=NOW,
        trusted_issuers=[ISSUER], capital_ceiling=ceiling,
    )
    assert r["status"] == "REJECTED"


def test_blank_subject_rejected():
    r = _eval(AccountModel.POOLED_MANAGED, "  ", _all(POOLED_GATES, "  "))
    assert r["status"] == "REJECTED"


def test_pooled_scope_eligible_only_with_all_pooled_receipts():
    r = _eval(AccountModel.POOLED_MANAGED, "pool-1", _all(POOLED_GATES, "pool-1"))
    assert r["status"] == "ELIGIBLE_FOR_LIVE_GATE_REVIEW"
    assert r["live_execution_authorized"] is False


def test_pooled_scope_with_one_gate_missing_stays_blocked():
    receipts = _all(POOLED_GATES, "pool-1")[:-1]
    r = _eval(AccountModel.POOLED_MANAGED, "pool-1", receipts)
    assert r["status"] == "BLOCKED"
    assert r["missing_or_invalid_gates"] == [POOLED_GATES[-1]]
