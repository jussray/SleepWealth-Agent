from datetime import datetime, timedelta, timezone

import pytest

from execution.account_models import (
    CUSTOMER_GATES,
    POOLED_GATES,
    AccountModel,
    evaluate_account_scope,
    verify_gate_receipt,
)
from execution.receipt_issuer import (
    KEY_ENV_VAR,
    MAX_TTL_SECONDS,
    load_issuer_key,
    mint_gate_receipt,
    mint_scope_receipts,
)

KEY = b"issuer-test-key-0123456789abcdef"
ISSUER = "trusted-runtime"
NOW = datetime(2030, 1, 1, tzinfo=timezone.utc)


def _mint(gate="customer_consent", subject="cust-1", **kw):
    args = {"gate": gate, "subject": subject, "issuer": ISSUER, "key": KEY, "now": NOW}
    args.update(kw)
    return mint_gate_receipt(**args)


def test_minted_receipt_verifies_against_the_verifier():
    r = _mint()
    assert verify_gate_receipt(r, gate="customer_consent", subject="cust-1", key=KEY, now=NOW,
                               trusted_issuers=[ISSUER]) is None


def test_expiry_is_now_plus_ttl_in_utc():
    r = _mint(ttl_seconds=3600)
    assert r["expires_at"] == (NOW + timedelta(hours=1)).isoformat()


def test_default_ttl_is_the_maximum_and_expires_after_it():
    r = _mint()
    assert r["expires_at"] == (NOW + timedelta(seconds=MAX_TTL_SECONDS)).isoformat()
    later = NOW + timedelta(seconds=MAX_TTL_SECONDS + 1)
    assert verify_gate_receipt(r, gate="customer_consent", subject="cust-1", key=KEY, now=later,
                               trusted_issuers=[ISSUER]) == "receipt_expired"


@pytest.mark.parametrize("bad_gate", ["live_trade", "", "CUSTOMER_CONSENT"])
def test_unknown_gate_is_rejected(bad_gate):
    with pytest.raises(ValueError, match="unknown gate"):
        _mint(gate=bad_gate)


@pytest.mark.parametrize("subject", ["", "   ", None])
def test_blank_subject_is_rejected(subject):
    with pytest.raises(ValueError, match="subject"):
        _mint(subject=subject)


@pytest.mark.parametrize("ttl", [0, -1, MAX_TTL_SECONDS + 1, True, 1.5, "60"])
def test_out_of_range_or_non_integer_ttl_is_rejected(ttl):
    with pytest.raises(ValueError):
        _mint(ttl_seconds=ttl)


def test_naive_datetime_is_rejected():
    with pytest.raises(ValueError, match="timezone-aware"):
        _mint(now=datetime(2030, 1, 1))


def test_short_key_fails_closed_at_signing():
    with pytest.raises(ValueError, match="at least 32 bytes"):
        _mint(key=b"short")


def test_scope_receipts_make_a_customer_scope_eligible_end_to_end():
    receipts = mint_scope_receipts(gates=CUSTOMER_GATES, subject="cust-1", issuer=ISSUER, key=KEY, now=NOW)
    result = evaluate_account_scope(
        model=AccountModel.CUSTOMER_CONNECTED, subject="cust-1", receipts=receipts,
        key=KEY, now=NOW, trusted_issuers=[ISSUER], capital_ceiling=1000.0,
    )
    assert result["status"] == "ELIGIBLE_FOR_LIVE_GATE_REVIEW"
    assert result["live_execution_authorized"] is False


def test_pooled_scope_needs_every_pooled_gate_minted():
    receipts = mint_scope_receipts(gates=POOLED_GATES[:-1], subject="pool-1", issuer=ISSUER, key=KEY, now=NOW)
    result = evaluate_account_scope(
        model=AccountModel.POOLED_MANAGED, subject="pool-1", receipts=receipts,
        key=KEY, now=NOW, trusted_issuers=[ISSUER], capital_ceiling=1000.0,
    )
    assert result["status"] == "BLOCKED"
    assert result["missing_or_invalid_gates"] == [POOLED_GATES[-1]]


def test_duplicate_gate_in_one_request_is_rejected():
    with pytest.raises(ValueError, match="duplicate"):
        mint_scope_receipts(gates=["customer_consent", "customer_consent"], subject="c", issuer=ISSUER,
                            key=KEY, now=NOW)


def test_issuer_key_is_read_from_environment_and_never_defaulted():
    with pytest.raises(RuntimeError, match="not set"):
        load_issuer_key({})
    with pytest.raises(RuntimeError, match="at least 32 bytes"):
        load_issuer_key({KEY_ENV_VAR: "short"})
    assert load_issuer_key({KEY_ENV_VAR: KEY.decode()}) == KEY
