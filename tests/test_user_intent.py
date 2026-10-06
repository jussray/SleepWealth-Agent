from datetime import datetime, timedelta, timezone

from mcp_gateway.user_intent import (
    issue_user_intent_receipt,
    validate_user_intent_receipt,
)

KEY = "i" * 32
SOURCE_SHA = "a" * 40
CALLER_FP = "1" * 64
SUBJECT_FP = "2" * 64
RESOURCE_FP = "3" * 64
INTENT_FP = "4" * 64


def _receipt(*, issued_at=None, ttl_seconds=300):
    return issue_user_intent_receipt(
        issuer_id="intent-issuer",
        issuer_key=KEY,
        source_sha=SOURCE_SHA,
        caller_fingerprint=CALLER_FP,
        subject_fingerprint=SUBJECT_FP,
        provider="vybe-solana-mcp",
        environment="mainnet-readonly",
        action="query-vybe-api",
        resource_fingerprint=RESOURCE_FP,
        intent_fingerprint=INTENT_FP,
        issued_at=issued_at,
        ttl_seconds=ttl_seconds,
    )


def test_user_intent_receipt_binds_exact_read_and_never_authorizes():
    receipt = _receipt()
    decision = validate_user_intent_receipt(
        receipt,
        trusted_keys={"intent-issuer": KEY},
        source_sha=SOURCE_SHA,
        caller_fingerprint=CALLER_FP,
        subject_fingerprint=SUBJECT_FP,
        provider="vybe-solana-mcp",
        environment="mainnet-readonly",
        action="query-vybe-api",
        resource_fingerprint=RESOURCE_FP,
    )

    assert decision.accepted is True
    assert decision.classification == "USER_INTENT_VERIFIED"
    assert receipt["authorizes"] is False
    assert receipt["allocation_authorized"] is False
    assert receipt["execution_authorized"] is False
    assert receipt["intent_fingerprint"] == INTENT_FP


def test_user_intent_receipt_cannot_be_reused_for_different_query():
    receipt = _receipt()
    decision = validate_user_intent_receipt(
        receipt,
        trusted_keys={"intent-issuer": KEY},
        source_sha=SOURCE_SHA,
        caller_fingerprint=CALLER_FP,
        subject_fingerprint=SUBJECT_FP,
        provider="vybe-solana-mcp",
        environment="mainnet-readonly",
        action="query-vybe-api",
        resource_fingerprint="5" * 64,
    )

    assert decision.accepted is False
    assert decision.classification == "USER_INTENT_CONFLICT"


def test_user_intent_receipt_expires():
    issued_at = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    receipt = _receipt(issued_at=issued_at, ttl_seconds=60)
    decision = validate_user_intent_receipt(
        receipt,
        trusted_keys={"intent-issuer": KEY},
        source_sha=SOURCE_SHA,
        caller_fingerprint=CALLER_FP,
        subject_fingerprint=SUBJECT_FP,
        provider="vybe-solana-mcp",
        environment="mainnet-readonly",
        action="query-vybe-api",
        resource_fingerprint=RESOURCE_FP,
        evaluated_at=issued_at + timedelta(seconds=61),
    )

    assert decision.accepted is False
    assert decision.classification == "STALE_USER_INTENT"


def test_user_intent_tamper_fails_closed():
    receipt = _receipt()
    receipt["purpose"] = "different-purpose"
    decision = validate_user_intent_receipt(
        receipt,
        trusted_keys={"intent-issuer": KEY},
        source_sha=SOURCE_SHA,
        caller_fingerprint=CALLER_FP,
        subject_fingerprint=SUBJECT_FP,
        provider="vybe-solana-mcp",
        environment="mainnet-readonly",
        action="query-vybe-api",
        resource_fingerprint=RESOURCE_FP,
    )

    assert decision.accepted is False
    assert decision.classification == "INVALID_USER_INTENT"
