"""A signed account grant must belong to one broker account and one model."""
from datetime import datetime, timezone

import pytest

from execution.account_models import (
    AccountModel, CUSTOMER_GATES, POOLED_GATES, evaluate_account_scope,
)
from execution.receipt_issuer import mint_scope_receipts, mint_gate_receipt

NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)
KEY = b"independent-account-boundary-test-key-123456"
ISSUER = "trusted-runtime"
ACCOUNT_A = "a" * 64
ACCOUNT_B = "b" * 64


def issue(model, subject, binding):
    gates = CUSTOMER_GATES if model is AccountModel.CUSTOMER_CONNECTED else POOLED_GATES
    return mint_scope_receipts(
        gates=gates, model=model, subject=subject, account_binding=binding,
        issuer=ISSUER, key=KEY, now=NOW, capital_ceiling=1000.0,
    )


def decide(model, subject, binding, receipts):
    return evaluate_account_scope(
        model=model, subject=subject, account_binding=binding, receipts=receipts,
        key=KEY, now=NOW, trusted_issuers=[ISSUER], capital_ceiling=1000.0,
    )


@pytest.mark.parametrize("model,subject", [
    (AccountModel.CUSTOMER_CONNECTED, "customer-123"),
    (AccountModel.POOLED_MANAGED, "pool-xyz"),
])
def test_signed_receipts_bound_to_specific_account_even_with_same_owner(model, subject):
    receipts = issue(model, subject, ACCOUNT_A)
    assert decide(model, subject, ACCOUNT_A, receipts)["status"] == "ELIGIBLE_FOR_LIVE_GATE_REVIEW"
    other = decide(model, subject, ACCOUNT_B, receipts)
    assert other["status"] == "BLOCKED"
    assert any("account_binding_mismatch" in reason for reason in other["reasons"])


def test_grants_from_two_customer_accounts_cannot_be_combined():
    first = issue(AccountModel.CUSTOMER_CONNECTED, "customer-123", ACCOUNT_A)
    second = issue(AccountModel.CUSTOMER_CONNECTED, "customer-123", ACCOUNT_B)
    mixed = [first[0], second[1], second[2]]
    result = decide(AccountModel.CUSTOMER_CONNECTED, "customer-123", ACCOUNT_A, mixed)
    assert result["status"] == "BLOCKED"
    assert "broker_oauth_grant" in result["missing_or_invalid_gates"]


@pytest.mark.parametrize("invalid", ["", "a" * 63, "z" * 64, "A" * 64, None])
def test_unsafe_or_missing_account_fingerprint_rejected(invalid):
    decision = decide(AccountModel.CUSTOMER_CONNECTED, "customer-123", invalid, [])
    assert decision["status"] == "REJECTED"
    assert "account_binding_invalid" in decision["reasons"]


def test_mint_rejects_mixed_mode_gate():
    with pytest.raises(ValueError, match="not valid for"):
        mint_gate_receipt(
            gate="pooled_capital_ceiling", model=AccountModel.CUSTOMER_CONNECTED,
            subject="customer-123", account_binding=ACCOUNT_A,
            issuer=ISSUER, key=KEY, now=NOW, capital_ceiling=1000.0,
        )


def test_both_models_can_use_same_code_without_sharing_authority():
    customer = issue(AccountModel.CUSTOMER_CONNECTED, "customer-123", ACCOUNT_A)
    pooled = issue(AccountModel.POOLED_MANAGED, "pool-xyz", ACCOUNT_B)
    assert decide(AccountModel.CUSTOMER_CONNECTED, "customer-123", ACCOUNT_A, pooled)["status"] == "BLOCKED"
    assert decide(AccountModel.POOLED_MANAGED, "pool-xyz", ACCOUNT_B, customer)["status"] == "BLOCKED"
