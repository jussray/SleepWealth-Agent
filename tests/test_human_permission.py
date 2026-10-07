from datetime import datetime, timedelta, timezone

from mcp_gateway.human_permission import (
    issue_human_capability_grant,
    issue_human_read_grant,
    validate_human_capability_grant,
    validate_human_read_grant,
)

KEY = "p" * 32
SOURCE_SHA = "a" * 40
CALLER_FP = "1" * 64
SUBJECT_FP = "2" * 64
HUMAN_FP = "3" * 64


def _grant(*, issued_at=None, ttl_seconds=3600):
    return issue_human_read_grant(
        issuer_id="permission-issuer",
        issuer_key=KEY,
        source_sha=SOURCE_SHA,
        caller_fingerprint=CALLER_FP,
        subject_fingerprint=SUBJECT_FP,
        provider="vybe-solana-mcp",
        environment="mainnet-readonly",
        allowed_actions=("query-vybe-api", "search-endpoints"),
        allowed_resource_prefixes=("/v4/",),
        human_approval_fingerprint=HUMAN_FP,
        issued_at=issued_at,
        ttl_seconds=ttl_seconds,
    )


def _validate(grant, *, action="query-vybe-api", resource_path="/v4/token/a", evaluated_at=None):
    return validate_human_read_grant(
        grant,
        trusted_keys={"permission-issuer": KEY},
        source_sha=SOURCE_SHA,
        caller_fingerprint=CALLER_FP,
        subject_fingerprint=SUBJECT_FP,
        provider="vybe-solana-mcp",
        environment="mainnet-readonly",
        action=action,
        resource_path=resource_path,
        evaluated_at=evaluated_at,
    )


def test_human_read_grant_authorizes_repeated_reads_inside_scope_not_execution():
    grant = _grant()

    first = _validate(grant, resource_path="/v4/token/a")
    second = _validate(grant, resource_path="/v4/wallet/b")

    assert first.accepted is True
    assert second.accepted is True
    assert grant["provider_read_authorized"] is True
    assert grant["execution_authorized"] is False
    assert grant["allocation_authorized"] is False
    assert grant["money_moving_authorized"] is False
    assert grant["transaction_construction_authorized"] is False
    assert grant["payment_authorized"] is False


def test_human_read_grant_blocks_action_outside_scope():
    decision = _validate(_grant(), action="get-endpoint")

    assert decision.accepted is False
    assert decision.classification == "HUMAN_PERMISSION_SCOPE_CONFLICT"


def test_human_read_grant_blocks_resource_outside_scope():
    decision = _validate(_grant(), resource_path="/v3/private")

    assert decision.accepted is False
    assert decision.classification == "HUMAN_PERMISSION_SCOPE_CONFLICT"


def test_human_read_grant_expires():
    issued_at = datetime(2026, 10, 6, 12, 0, tzinfo=timezone.utc)
    grant = _grant(issued_at=issued_at, ttl_seconds=60)

    decision = _validate(grant, evaluated_at=issued_at + timedelta(seconds=61))

    assert decision.accepted is False
    assert decision.classification == "STALE_HUMAN_PERMISSION"


def test_human_read_grant_tamper_fails_closed():
    grant = _grant()
    grant["allowed_actions"] = ["query-vybe-api", "get-endpoint"]

    decision = _validate(grant)

    assert decision.accepted is False
    assert decision.classification == "INVALID_HUMAN_PERMISSION"


def test_human_capability_grant_supports_read_and_prepare_write_without_execution():
    grant = issue_human_capability_grant(
        issuer_id="permission-issuer",
        issuer_key=KEY,
        source_sha=SOURCE_SHA,
        caller_fingerprint=CALLER_FP,
        subject_fingerprint=SUBJECT_FP,
        provider="vybe-solana-mcp",
        environment="mainnet-readonly",
        allowed_actions=("query-vybe-api", "build-vybe-transaction"),
        allowed_resource_prefixes=("/v4/",),
        allowed_effects=("read", "prepare-write"),
        human_approval_fingerprint=HUMAN_FP,
    )

    read = validate_human_capability_grant(
        grant,
        trusted_keys={"permission-issuer": KEY},
        source_sha=SOURCE_SHA,
        caller_fingerprint=CALLER_FP,
        subject_fingerprint=SUBJECT_FP,
        provider="vybe-solana-mcp",
        environment="mainnet-readonly",
        action="query-vybe-api",
        required_effect="read",
        resource_path="/v4/token/a",
    )
    write = validate_human_capability_grant(
        grant,
        trusted_keys={"permission-issuer": KEY},
        source_sha=SOURCE_SHA,
        caller_fingerprint=CALLER_FP,
        subject_fingerprint=SUBJECT_FP,
        provider="vybe-solana-mcp",
        environment="mainnet-readonly",
        action="build-vybe-transaction",
        required_effect="prepare-write",
        resource_path="/v4/trading/swap",
    )

    assert read.accepted is True
    assert write.accepted is True
    assert grant["provider_read_authorized"] is True
    assert grant["provider_prepare_write_authorized"] is True
    assert grant["execution_authorized"] is False
    assert grant["signing_authorized"] is False
    assert grant["broadcast_authorized"] is False
    assert grant["money_moving_authorized"] is False
    assert grant["payment_authorized"] is False


def test_read_only_grant_cannot_prepare_write():
    grant = issue_human_read_grant(
        issuer_id="permission-issuer",
        issuer_key=KEY,
        source_sha=SOURCE_SHA,
        caller_fingerprint=CALLER_FP,
        subject_fingerprint=SUBJECT_FP,
        provider="vybe-solana-mcp",
        environment="mainnet-readonly",
        allowed_actions=("query-vybe-api", "build-vybe-transaction"),
        allowed_resource_prefixes=("/v4/",),
        human_approval_fingerprint=HUMAN_FP,
    )

    decision = validate_human_capability_grant(
        grant,
        trusted_keys={"permission-issuer": KEY},
        source_sha=SOURCE_SHA,
        caller_fingerprint=CALLER_FP,
        subject_fingerprint=SUBJECT_FP,
        provider="vybe-solana-mcp",
        environment="mainnet-readonly",
        action="build-vybe-transaction",
        required_effect="prepare-write",
        resource_path="/v4/trading/swap",
    )

    assert decision.accepted is False
    assert decision.classification == "HUMAN_PERMISSION_EFFECT_CONFLICT"
