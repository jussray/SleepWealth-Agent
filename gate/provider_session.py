"""Authenticated, non-authorizing provider-session receipts.

A provider session receipt proves that trusted Sleep Wealth runtime code observed a
specific provider/account context recently. It is not trading authority. The
receipt deliberately contains only non-secret account fingerprints and capability
observations, never credentials, account numbers, orders, wallet secrets, or
funding instructions.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Mapping

MIN_RECEIPT_KEY_BYTES = 32
MAX_SESSION_TTL_SECONDS = 10 * 60
MAX_OBSERVATION_AGE_SECONDS = 5 * 60
MAX_CLOCK_SKEW_SECONDS = 5 * 60
ALLOWED_ASSET_PERMISSIONS = frozenset({"stock-market", "crypto"})
BLOCK_FLAGS = ("account_blocked", "trading_blocked", "trade_suspended_by_user")


def _canonical(payload: Mapping[str, object]) -> bytes:
    body = dict(payload)
    body.pop("fingerprint", None)
    body.pop("receipt_auth", None)
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _canonical_observation(observation: Mapping[str, object]) -> bytes:
    body = dict(observation)
    body.pop("observation_fingerprint", None)
    return json.dumps(
        body,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _key(value: object) -> bytes:
    if isinstance(value, bytes):
        result = value
    elif isinstance(value, str):
        result = value.encode("utf-8")
    else:
        return b""
    return result if len(result) >= MIN_RECEIPT_KEY_BYTES else b""


def _sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.isascii()
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


def _time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _block_flags_are_booleans(payload: Mapping[str, object]) -> bool:
    return all(isinstance(payload.get(name), bool) for name in BLOCK_FLAGS)


def _account_is_blocked(payload: Mapping[str, object]) -> bool:
    return any(payload.get(name) is True for name in BLOCK_FLAGS)


def _observation_fingerprint_matches(observation: Mapping[str, object]) -> bool:
    supplied = observation.get("observation_fingerprint")
    if not _sha256(supplied):
        return False
    expected = hashlib.sha256(_canonical_observation(observation)).hexdigest()
    return hmac.compare_digest(str(supplied).lower(), expected.lower())


def _observation_ok(observation: Mapping[str, object]) -> bool:
    permissions = observation.get("asset_permissions")
    return (
        observation.get("event") == "provider_live_account_observed"
        and observation.get("classification") == "OBSERVED"
        and observation.get("environment") == "live"
        and observation.get("connected") is True
        and observation.get("execution_authorized") is False
        and observation.get("order_submit_capability") is False
        and isinstance(observation.get("provider"), str)
        and bool(str(observation.get("provider", "")).strip())
        and _sha256(observation.get("account_fingerprint"))
        and isinstance(permissions, list)
        and len(permissions) == len(set(permissions))
        and all(item in ALLOWED_ASSET_PERMISSIONS for item in permissions)
        and _block_flags_are_booleans(observation)
        and not (_account_is_blocked(observation) and bool(permissions))
        and _observation_fingerprint_matches(observation)
        and _time(observation.get("observed_at")) is not None
    )


def mint_provider_session_receipt(
    observation: Mapping[str, object],
    *,
    issuer_id: str,
    receipt_key: object,
    ttl_seconds: int = 5 * 60,
    issued_at: datetime | None = None,
) -> dict[str, object]:
    """Authenticate a safe provider observation without granting execution authority."""

    if not _observation_ok(observation):
        raise ValueError("provider observation is missing required non-authorizing invariants")
    if not isinstance(issuer_id, str) or not issuer_id.strip():
        raise ValueError("issuer_id must not be empty")
    key = _key(receipt_key)
    if not key:
        raise ValueError(f"receipt key must be at least {MIN_RECEIPT_KEY_BYTES} bytes")
    if not 1 <= int(ttl_seconds) <= MAX_SESSION_TTL_SECONDS:
        raise ValueError(f"session receipt ttl must be 1..{MAX_SESSION_TTL_SECONDS} seconds")

    now = _utc(issued_at)
    observed_at = _time(observation.get("observed_at"))
    if observed_at is None:
        raise ValueError("provider observation timestamp is invalid")
    observed = observed_at.astimezone(timezone.utc)
    if not (
        now - timedelta(seconds=MAX_OBSERVATION_AGE_SECONDS)
        <= observed
        <= now + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS)
    ):
        raise ValueError("provider observation is stale or too far in the future")

    expires = now + timedelta(seconds=int(ttl_seconds))
    receipt: dict[str, object] = {
        "schema": "sleepwealth-provider-session-v1",
        "event": "broker_live_session_observed",
        "classification": "VERIFIED_OBSERVATION",
        "source": "trusted-provider-observer",
        "provider": observation["provider"],
        "environment": "live",
        "account_fingerprint": observation["account_fingerprint"],
        "asset_permissions": list(observation["asset_permissions"]),
        "account_status": observation.get("account_status"),
        "crypto_status": observation.get("crypto_status"),
        "account_blocked": observation.get("account_blocked"),
        "trading_blocked": observation.get("trading_blocked"),
        "trade_suspended_by_user": observation.get("trade_suspended_by_user"),
        "observation_fingerprint": observation["observation_fingerprint"],
        "observed_at": observation["observed_at"],
        "issuer_id": issuer_id.strip(),
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "execution_authorized": False,
        "order_submit_capability": False,
    }
    receipt["fingerprint"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    receipt["receipt_auth"] = hmac.new(key, _canonical(receipt), hashlib.sha256).hexdigest()
    return receipt


def validate_provider_session_receipt(
    receipt: Mapping[str, object] | None,
    *,
    trusted_keys: Mapping[str, object] | None,
    evaluated_at: datetime | None = None,
) -> dict[str, object]:
    """Validate authenticity, freshness, and fail-closed session invariants."""

    if receipt is None:
        return {
            "classification": "UNKNOWN",
            "accepted": False,
            "reason": "no authenticated live provider session receipt supplied",
        }

    permissions = receipt.get("asset_permissions")
    structural_ok = (
        receipt.get("schema") == "sleepwealth-provider-session-v1"
        and receipt.get("event") == "broker_live_session_observed"
        and receipt.get("classification") == "VERIFIED_OBSERVATION"
        and receipt.get("source") == "trusted-provider-observer"
        and receipt.get("environment") == "live"
        and receipt.get("execution_authorized") is False
        and receipt.get("order_submit_capability") is False
        and isinstance(receipt.get("provider"), str)
        and bool(str(receipt.get("provider", "")).strip())
        and isinstance(receipt.get("issuer_id"), str)
        and bool(str(receipt.get("issuer_id", "")).strip())
        and _sha256(receipt.get("account_fingerprint"))
        and _sha256(receipt.get("observation_fingerprint"))
        and isinstance(permissions, list)
        and len(permissions) == len(set(permissions))
        and all(item in ALLOWED_ASSET_PERMISSIONS for item in permissions)
        and _block_flags_are_booleans(receipt)
        and _sha256(receipt.get("fingerprint"))
        and hashlib.sha256(_canonical(receipt)).hexdigest() == str(receipt.get("fingerprint"))
    )
    if not structural_ok:
        return {
            "classification": "INVALID",
            "accepted": False,
            "reason": "live provider session receipt failed integrity or non-authority invariants",
        }

    issuer_id = str(receipt["issuer_id"])
    key = _key((trusted_keys or {}).get(issuer_id))
    provided_auth = receipt.get("receipt_auth")
    expected_auth = hmac.new(key, _canonical(receipt), hashlib.sha256).hexdigest() if key else ""
    if not (
        key
        and _sha256(provided_auth)
        and hmac.compare_digest(str(provided_auth).lower(), expected_auth.lower())
    ):
        return {
            "classification": "UNTRUSTED",
            "accepted": False,
            "reason": "live provider session receipt lacks valid trusted-runtime authentication",
        }

    issued_at = _time(receipt.get("issued_at"))
    expires_at = _time(receipt.get("expires_at"))
    observed_at = _time(receipt.get("observed_at"))
    now = _utc(evaluated_at)
    freshness_ok = False
    if issued_at and expires_at and observed_at:
        issued = issued_at.astimezone(timezone.utc)
        expires = expires_at.astimezone(timezone.utc)
        observed = observed_at.astimezone(timezone.utc)
        ttl = (expires - issued).total_seconds()
        freshness_ok = (
            0 < ttl <= MAX_SESSION_TTL_SECONDS
            and issued - timedelta(seconds=MAX_OBSERVATION_AGE_SECONDS)
            <= observed
            <= issued + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS)
            and issued <= now + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS)
            and now <= expires
        )
    if not freshness_ok:
        return {
            "classification": "STALE",
            "accepted": False,
            "reason": "live provider session or its underlying observation is outside the trusted freshness window",
        }

    if _account_is_blocked(receipt) or not permissions:
        return {
            "classification": "BLOCKED_ACCOUNT",
            "accepted": False,
            "reason": (
                "live provider/account session is authentic and fresh but the account is blocked, "
                "suspended, or exposes no enabled stock-market/crypto permission"
            ),
            "provider": receipt["provider"],
            "account_fingerprint": receipt["account_fingerprint"],
            "asset_permissions": list(permissions),
            "expires_at": receipt["expires_at"],
            "fingerprint": receipt["fingerprint"],
        }

    return {
        "classification": "VERIFIED_LIVE_SESSION",
        "accepted": True,
        "reason": (
            "trusted runtime recently observed this live provider/account session with at least "
            "one enabled market permission; no execution authority is granted"
        ),
        "provider": receipt["provider"],
        "account_fingerprint": receipt["account_fingerprint"],
        "asset_permissions": list(permissions),
        "expires_at": receipt["expires_at"],
        "fingerprint": receipt["fingerprint"],
    }
