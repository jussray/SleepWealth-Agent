from datetime import datetime, timedelta, timezone

import pytest

from mcp_gateway.action_ledger import ProductActionLedger
from mcp_gateway.authority import (
    issue_product_action_authority,
    validate_product_action_authority,
)
from mcp_gateway.continuity import issue_continuity_cookie, validate_continuity_cookie

COOKIE_KEY = "c" * 32
AUTHORITY_KEY = "a" * 32
LEDGER_KEY = "l" * 32
FP_A = "1" * 64
FP_B = "2" * 64
FP_C = "3" * 64
FP_D = "4" * 64
FP_E = "5" * 64
FP_F = "6" * 64


def test_continuity_cookie_is_authenticated_but_never_authority():
    cookie = issue_continuity_cookie(
        issuer_id="cookie-issuer",
        issuer_key=COOKIE_KEY,
        caller_fingerprint=FP_A,
        subject_fingerprint=FP_D,
        provider="solana-rpc",
        provider_subject_fingerprint=FP_B,
        source_sha="a" * 40,
        environment="mainnet-beta",
        capabilities=("broadcast-signed-transaction",),
        authority_fingerprint=FP_C,
    )
    decision = validate_continuity_cookie(
        cookie,
        trusted_keys={"cookie-issuer": COOKIE_KEY},
    )
    assert decision.accepted is True
    assert decision.classification == "VERIFIED_CONTINUITY"
    assert decision.caller_fingerprint == FP_A
    assert decision.subject_fingerprint == FP_D
    assert cookie["authorizes"] is False
    assert cookie["execution_authorized"] is False
    assert cookie["contains_secret"] is False


def test_forged_or_stale_continuity_cookie_fails_closed():
    cookie = issue_continuity_cookie(
        issuer_id="cookie-issuer",
        issuer_key=COOKIE_KEY,
        caller_fingerprint=FP_A,
        subject_fingerprint=FP_D,
        provider="cash-app-pay",
        provider_subject_fingerprint=FP_B,
        source_sha="b" * 40,
        environment="production",
        capabilities=("create-payment",),
    )
    forged = dict(cookie)
    forged["provider"] = "solana-rpc"
    assert validate_continuity_cookie(
        forged,
        trusted_keys={"cookie-issuer": COOKIE_KEY},
    ).accepted is False

    old = datetime.now(timezone.utc) - timedelta(minutes=20)
    stale = issue_continuity_cookie(
        issuer_id="cookie-issuer",
        issuer_key=COOKIE_KEY,
        caller_fingerprint=FP_A,
        subject_fingerprint=FP_D,
        provider="cash-app-pay",
        provider_subject_fingerprint=FP_B,
        source_sha="b" * 40,
        environment="production",
        capabilities=("create-payment",),
        issued_at=old,
        ttl_seconds=60,
    )
    decision = validate_continuity_cookie(
        stale,
        trusted_keys={"cookie-issuer": COOKIE_KEY},
    )
    assert decision.accepted is False
    assert decision.classification == "STALE"


def _authority(**overrides):
    values = {
        "issuer_id": "authority-issuer",
        "issuer_key": AUTHORITY_KEY,
        "subject_fingerprint": FP_A,
        "provider": "cash-app-pay",
        "environment": "production",
        "account_fingerprint": FP_B,
        "action": "create-payment",
        "resource_fingerprint": FP_C,
        "human_approval_fingerprint": FP_D,
        "eligible_adult_receipt_fingerprint": FP_E,
        "provider_session_fingerprint": FP_F,
        "idempotency_key": "idem-1",
        "max_amount": 25.0,
        "currency": "USD",
    }
    values.update(overrides)
    return issue_product_action_authority(**values)


def _validate(receipt, **overrides):
    values = {
        "trusted_keys": {"authority-issuer": AUTHORITY_KEY},
        "subject_fingerprint": FP_A,
        "provider": "cash-app-pay",
        "environment": "production",
        "account_fingerprint": FP_B,
        "action": "create-payment",
        "resource_fingerprint": FP_C,
        "idempotency_key": "idem-1",
        "requested_amount": 24.99,
        "currency": "USD",
    }
    values.update(overrides)
    return validate_product_action_authority(receipt, **values)


def test_product_authority_binds_exact_subject_scope_and_amount():
    receipt = _authority()
    decision = _validate(receipt)
    assert decision.accepted is True
    assert decision.subject_fingerprint == FP_A
    assert receipt["eligible_adult_required"] is True
    assert receipt["provider_permission_required"] is True
    assert receipt["human_approval_required"] is True
    assert receipt["credential_material_included"] is False

    exceeded = _validate(receipt, requested_amount=25.01)
    assert exceeded.accepted is False
    assert exceeded.classification == "AMOUNT_EXCEEDED"

    drifted_resource = _validate(receipt, resource_fingerprint="f" * 64)
    assert drifted_resource.accepted is False
    assert drifted_resource.classification == "SCOPE_CONFLICT"

    drifted_subject = _validate(receipt, subject_fingerprint="e" * 64)
    assert drifted_subject.accepted is False
    assert drifted_subject.classification == "SCOPE_CONFLICT"


def test_action_ledger_blocks_replay_revocation_and_kill_switch(tmp_path):
    ledger = ProductActionLedger(tmp_path / "actions.json", LEDGER_KEY)
    ok, _ = ledger.reserve(
        provider="cash-app-pay",
        receipt_id="PAA-one",
        idempotency_key="idem-one",
        resource_fingerprint=FP_A,
    )
    assert ok is True
    replay, replay_reason = ledger.reserve(
        provider="cash-app-pay",
        receipt_id="PAA-one",
        idempotency_key="idem-one",
        resource_fingerprint=FP_A,
    )
    assert replay is False
    assert "already crossed" in replay_reason

    ledger.revoke("PAA-two")
    revoked, revoked_reason = ledger.reserve(
        provider="solana-rpc",
        receipt_id="PAA-two",
        idempotency_key="idem-two",
        resource_fingerprint=FP_B,
    )
    assert revoked is False
    assert "revoked" in revoked_reason

    ledger.set_kill_switch(True)
    killed, killed_reason = ledger.reserve(
        provider="solana-rpc",
        receipt_id="PAA-three",
        idempotency_key="idem-three",
        resource_fingerprint=FP_C,
    )
    assert killed is False
    assert "kill switch" in killed_reason


def test_authority_rejects_short_keys_and_bad_fingerprints():
    with pytest.raises(ValueError, match=r"32\+"):
        issue_product_action_authority(
            issuer_id="issuer",
            issuer_key="short",
            subject_fingerprint=FP_A,
            provider="solana-rpc",
            environment="mainnet-beta",
            account_fingerprint=FP_B,
            action="broadcast-signed-transaction",
            resource_fingerprint=FP_C,
            human_approval_fingerprint=FP_D,
            eligible_adult_receipt_fingerprint=FP_E,
            provider_session_fingerprint=FP_F,
            idempotency_key="idem",
        )
