import hashlib
import json
from datetime import datetime, timedelta, timezone

import pytest

from gate.provider_session import (
    mint_provider_session_receipt,
    validate_provider_session_receipt,
)

KEY = b"sleepwealth-provider-session-test-key-32bytes"
ISSUER = "sleepwealth-runtime"
NOW = datetime(2026, 9, 20, 5, 0, tzinfo=timezone.utc)
ACCOUNT_FP = hashlib.sha256(b"alpaca-account-1").hexdigest()


def _observation(**overrides):
    payload = {
        "event": "provider_live_account_observed",
        "classification": "OBSERVED",
        "provider": "alpaca",
        "environment": "live",
        "connected": True,
        "account_fingerprint": ACCOUNT_FP,
        "account_status": "ACTIVE",
        "crypto_status": "ACTIVE",
        "account_blocked": False,
        "trading_blocked": False,
        "trade_suspended_by_user": False,
        "asset_permissions": ["stock-market", "crypto"],
        "observed_at": NOW.isoformat(),
        "execution_authorized": False,
        "order_submit_capability": False,
    }
    payload.update(overrides)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    payload["observation_fingerprint"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return payload


def test_minted_provider_session_is_authenticated_but_non_authorizing():
    receipt = mint_provider_session_receipt(
        _observation(),
        issuer_id=ISSUER,
        receipt_key=KEY,
        issued_at=NOW,
    )

    verified = validate_provider_session_receipt(
        receipt,
        trusted_keys={ISSUER: KEY},
        evaluated_at=NOW + timedelta(seconds=30),
    )

    assert verified["classification"] == "VERIFIED_LIVE_SESSION"
    assert verified["accepted"] is True
    assert verified["provider"] == "alpaca"
    assert verified["account_fingerprint"] == ACCOUNT_FP
    assert verified["asset_permissions"] == ["stock-market", "crypto"]
    assert receipt["execution_authorized"] is False
    assert receipt["order_submit_capability"] is False


def test_authentic_session_with_no_enabled_market_permission_is_blocked():
    receipt = mint_provider_session_receipt(
        _observation(
            account_status="ACCOUNT_UPDATED",
            crypto_status="INACTIVE",
            trading_blocked=True,
            asset_permissions=[],
        ),
        issuer_id=ISSUER,
        receipt_key=KEY,
        issued_at=NOW,
    )

    result = validate_provider_session_receipt(
        receipt,
        trusted_keys={ISSUER: KEY},
        evaluated_at=NOW + timedelta(seconds=30),
    )

    assert result["classification"] == "BLOCKED_ACCOUNT"
    assert result["accepted"] is False
    assert result["asset_permissions"] == []


def test_forged_or_unknown_issuer_session_is_untrusted():
    receipt = mint_provider_session_receipt(
        _observation(), issuer_id=ISSUER, receipt_key=KEY, issued_at=NOW
    )
    receipt["account_status"] = "LIMITED"
    receipt["fingerprint"] = hashlib.sha256(b"forged").hexdigest()

    invalid = validate_provider_session_receipt(
        receipt, trusted_keys={ISSUER: KEY}, evaluated_at=NOW
    )
    assert invalid["classification"] == "INVALID"

    receipt = mint_provider_session_receipt(
        _observation(), issuer_id=ISSUER, receipt_key=KEY, issued_at=NOW
    )
    untrusted = validate_provider_session_receipt(
        receipt, trusted_keys={"other": KEY}, evaluated_at=NOW
    )
    assert untrusted["classification"] == "UNTRUSTED"
    assert untrusted["accepted"] is False


def test_expired_session_is_stale():
    receipt = mint_provider_session_receipt(
        _observation(observed_at=(NOW - timedelta(minutes=20)).isoformat()),
        issuer_id=ISSUER,
        receipt_key=KEY,
        ttl_seconds=60,
        issued_at=NOW - timedelta(minutes=20),
    )
    result = validate_provider_session_receipt(
        receipt,
        trusted_keys={ISSUER: KEY},
        evaluated_at=NOW,
    )
    assert result["classification"] == "STALE"
    assert result["accepted"] is False


def test_signer_rejects_corrupted_observation_fingerprint():
    observation = _observation()
    observation["account_status"] = "LIMITED"

    with pytest.raises(ValueError):
        mint_provider_session_receipt(
            observation,
            issuer_id=ISSUER,
            receipt_key=KEY,
            issued_at=NOW,
        )


def test_receipt_rejects_execution_authority_or_unknown_asset_lane():
    with pytest.raises(ValueError):
        mint_provider_session_receipt(
            _observation(execution_authorized=True),
            issuer_id=ISSUER,
            receipt_key=KEY,
            issued_at=NOW,
        )

    with pytest.raises(ValueError):
        mint_provider_session_receipt(
            _observation(asset_permissions=["options"]),
            issuer_id=ISSUER,
            receipt_key=KEY,
            issued_at=NOW,
        )
