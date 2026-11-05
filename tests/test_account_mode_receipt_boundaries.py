"""Regression tests for mode-specific, cryptographically bound capital authority."""
from datetime import datetime, timedelta, timezone

import pytest

from execution.account_models import (
    AccountModel, CUSTOMER_GATES, POOLED_GATES,
    evaluate_account_scope, sign_receipt, verify_gate_receipt,
)
from execution.receipt_issuer import mint_gate_receipt, mint_scope_receipts

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
KEY = b"account-mode-boundary-test-key-0123456789"
ISSUER = "trusted-runtime"
CAPITAL_GATES = {"account_risk_ceiling", "pooled_capital_ceiling"}


def receipt(gate, subject, *, limit=1000.0):
    fields = {
        "gate": gate, "subject": subject, "issued_by": ISSUER,
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
    }
    if gate in CAPITAL_GATES:
        fields["capital_ceiling"] = limit
    return {**fields, "signature": sign_receipt(fields, KEY)}


@pytest.mark.parametrize("mode,gates,subject", [
    (AccountModel.CUSTOMER_CONNECTED, CUSTOMER_GATES, "customer-a"),
    (AccountModel.POOLED_MANAGED, POOLED_GATES, "pool-a"),
])
def test_capital_authority_must_match_signed_receipt(mode, gates, subject):
    receipts = [receipt(gate, subject) for gate in gates]
    base = dict(model=mode, subject=subject, receipts=receipts, key=KEY,
                now=NOW, trusted_issuers=[ISSUER])
    assert evaluate_account_scope(**base, capital_ceiling=1000.0)["status"] == "ELIGIBLE_FOR_LIVE_GATE_REVIEW"
    greater = evaluate_account_scope(**base, capital_ceiling=9000.0)
    assert greater["status"] == "BLOCKED"
    assert any("capital_ceiling_mismatch" in reason for reason in greater["reasons"])


@pytest.mark.parametrize("mode,gates,subject", [
    (AccountModel.CUSTOMER_CONNECTED, CUSTOMER_GATES, "customer-a"),
    (AccountModel.POOLED_MANAGED, POOLED_GATES, "pool-a"),
])
def test_capital_gate_without_signed_amount_cannot_authorize_any_ceiling(mode, gates, subject):
    receipts = [receipt(gate, subject) for gate in gates]
    cap_gate = next(g for g in gates if g in CAPITAL_GATES)
    old_fields = {key: value for key, value in receipts[-1].items()
                  if key not in {"signature", "capital_ceiling"}}
    # Replace the exact capital receipt, regardless of gate ordering.
    receipts = [r for r in receipts if r["gate"] != cap_gate]
    receipts.append({**old_fields, "gate": cap_gate, "signature": sign_receipt({**old_fields, "gate": cap_gate}, KEY)})
    decision = evaluate_account_scope(
        model=mode, subject=subject, receipts=receipts,
        key=KEY, now=NOW, trusted_issuers=[ISSUER], capital_ceiling=1000.0,
    )
    assert decision["status"] == "BLOCKED"
    assert any("capital_ceiling" in reason for reason in decision["reasons"])


def test_malformed_unicode_signature_is_rejected_not_raised():
    r = receipt("customer_consent", "customer-a")
    r["signature"] = "é" * 64
    assert verify_gate_receipt(r, gate="customer_consent", subject="customer-a",
                               key=KEY, now=NOW, trusted_issuers=[ISSUER]) == "signature_invalid"


def test_naive_receipt_expiry_cannot_be_assumed_utc():
    r = receipt("customer_consent", "customer-a")
    r["expires_at"] = "2030-01-02T00:00:00"
    fields = {k: v for k, v in r.items() if k != "signature"}
    r["signature"] = sign_receipt(fields, KEY)
    assert verify_gate_receipt(r, gate="customer_consent", subject="customer-a",
                               key=KEY, now=NOW, trusted_issuers=[ISSUER]) == "expiry_unparseable"


def test_invalid_account_model_rejects_without_crashing():
    decision = evaluate_account_scope(
        model="pooled-managed", subject="pool-a", receipts=[],
        key=KEY, now=NOW, trusted_issuers=[ISSUER], capital_ceiling=1000.0,
    )
    assert decision["status"] == "REJECTED"


def test_issuer_requires_explicit_amount_for_capital_grant():
    with pytest.raises(ValueError, match="capital_ceiling"):
        mint_gate_receipt(gate="account_risk_ceiling", subject="customer-a",
                          issuer=ISSUER, key=KEY, now=NOW)
    issued = mint_scope_receipts(gates=CUSTOMER_GATES, subject="customer-a",
                                  issuer=ISSUER, key=KEY, now=NOW,
                                  capital_ceiling=1000.0)
    bound = next(r for r in issued if r["gate"] == "account_risk_ceiling")
    assert bound["capital_ceiling"] == 1000.0


def test_unhashable_issuer_is_a_rejection_not_an_exception():
    r = receipt("customer_consent", "customer-a")
    r["issued_by"] = ["trusted-runtime"]
    assert verify_gate_receipt(
        r, gate="customer_consent", subject="customer-a",
        key=KEY, now=NOW, trusted_issuers=[ISSUER],
    ) == "untrusted_issuer"


def test_untrusted_naive_clock_rejected_without_exception():
    decision = evaluate_account_scope(
        model=AccountModel.CUSTOMER_CONNECTED, subject="customer-a",
        receipts=[], key=KEY, now=datetime(2030, 1, 1),
        trusted_issuers=[ISSUER], capital_ceiling=1000.0,
    )
    assert decision["status"] == "REJECTED"
    assert "trusted_clock_required" in decision["reasons"]
