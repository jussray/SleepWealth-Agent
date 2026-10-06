from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

SCHEMA = "sleepwealth-user-intent-v1"
MIN_INTENT_KEY_BYTES = 32
MAX_INTENT_TTL_SECONDS = 10 * 60
MAX_CLOCK_SKEW_SECONDS = 5 * 60


def _canonical(payload: Mapping[str, object]) -> bytes:
    body = dict(payload)
    body.pop("fingerprint", None)
    body.pop("receipt_auth", None)
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _key(value: object) -> bytes:
    if isinstance(value, bytes):
        result = value
    elif isinstance(value, str):
        result = value.encode("utf-8")
    else:
        return b""
    return result if len(result) >= MIN_INTENT_KEY_BYTES else b""


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.isascii()
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


def _parse_time(value: object) -> datetime | None:
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


@dataclass(frozen=True, slots=True)
class UserIntentDecision:
    accepted: bool
    classification: str
    reason: str
    receipt_id: str | None = None
    intent_fingerprint: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "classification": self.classification,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "intent_fingerprint": self.intent_fingerprint,
        }


def issue_user_intent_receipt(
    *,
    issuer_id: str,
    issuer_key: str | bytes,
    source_sha: str,
    caller_fingerprint: str,
    subject_fingerprint: str,
    provider: str,
    environment: str,
    action: str,
    resource_fingerprint: str,
    intent_fingerprint: str,
    purpose: str = "user-requested-read",
    issued_at: datetime | None = None,
    ttl_seconds: int = 300,
) -> dict[str, object]:
    """Bind explicit user intent to one exact provider read without granting authority.

    The trusted product control plane may call this after it has identified the
    user's explicit request. Raw user text is not stored here; only its SHA-256
    fingerprint is retained. This function is intentionally not an MCP tool.
    """

    key = _key(issuer_key)
    if not issuer_id.strip() or not key:
        raise ValueError("trusted intent issuer id and a 32+ byte key are required")
    for name, value in {
        "caller_fingerprint": caller_fingerprint,
        "subject_fingerprint": subject_fingerprint,
        "resource_fingerprint": resource_fingerprint,
        "intent_fingerprint": intent_fingerprint,
    }.items():
        if not _valid_sha256(value):
            raise ValueError(f"{name} must be a SHA-256 fingerprint")
    if len(str(source_sha).strip()) < 7:
        raise ValueError("source_sha is required")
    if not provider.strip() or not environment.strip() or not action.strip() or not purpose.strip():
        raise ValueError("provider, environment, action, and purpose are required")
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool):
        raise ValueError("ttl_seconds must be an integer")
    if not 1 <= ttl_seconds <= MAX_INTENT_TTL_SECONDS:
        raise ValueError(f"intent TTL must be 1..{MAX_INTENT_TTL_SECONDS} seconds")

    now = _utc(issued_at)
    expires = now + timedelta(seconds=ttl_seconds)
    receipt: dict[str, object] = {
        "schema": SCHEMA,
        "event": "user_intent_bound",
        "classification": "USER_INTENT_PRESENT",
        "receipt_id": f"UIR-{uuid.uuid4().hex}",
        "issuer_id": issuer_id.strip(),
        "source_sha": str(source_sha).strip(),
        "caller_fingerprint": caller_fingerprint.lower(),
        "subject_fingerprint": subject_fingerprint.lower(),
        "provider": provider.strip().lower(),
        "environment": environment.strip().lower(),
        "action": action.strip().lower(),
        "resource_fingerprint": resource_fingerprint.lower(),
        "intent_fingerprint": intent_fingerprint.lower(),
        "purpose": purpose.strip().lower(),
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "user_intent_present": True,
        "authorizes": False,
        "allocation_authorized": False,
        "execution_authorized": False,
        "credential_material_included": False,
    }
    receipt["fingerprint"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    receipt["receipt_auth"] = hmac.new(key, _canonical(receipt), hashlib.sha256).hexdigest()
    return receipt


def validate_user_intent_receipt(
    receipt: Mapping[str, object] | None,
    *,
    trusted_keys: Mapping[str, object] | None,
    source_sha: str,
    caller_fingerprint: str,
    subject_fingerprint: str,
    provider: str,
    environment: str,
    action: str,
    resource_fingerprint: str,
    evaluated_at: datetime | None = None,
) -> UserIntentDecision:
    if receipt is None:
        return UserIntentDecision(False, "MISSING_USER_INTENT", "explicit user intent is required")

    receipt_id = str(receipt.get("receipt_id", "")) or None
    intent_fingerprint = str(receipt.get("intent_fingerprint", "")) or None

    def reject(classification: str, reason: str) -> UserIntentDecision:
        return UserIntentDecision(False, classification, reason, receipt_id, intent_fingerprint)

    structural_ok = (
        receipt.get("schema") == SCHEMA
        and receipt.get("event") == "user_intent_bound"
        and receipt.get("classification") == "USER_INTENT_PRESENT"
        and isinstance(receipt_id, str)
        and receipt_id.startswith("UIR-")
        and isinstance(receipt.get("issuer_id"), str)
        and bool(str(receipt.get("issuer_id", "")).strip())
        and len(str(receipt.get("source_sha", "")).strip()) >= 7
        and _valid_sha256(receipt.get("caller_fingerprint"))
        and _valid_sha256(receipt.get("subject_fingerprint"))
        and _valid_sha256(receipt.get("resource_fingerprint"))
        and _valid_sha256(receipt.get("intent_fingerprint"))
        and isinstance(receipt.get("provider"), str)
        and isinstance(receipt.get("environment"), str)
        and isinstance(receipt.get("action"), str)
        and isinstance(receipt.get("purpose"), str)
        and bool(str(receipt.get("purpose", "")).strip())
        and receipt.get("user_intent_present") is True
        and receipt.get("authorizes") is False
        and receipt.get("allocation_authorized") is False
        and receipt.get("execution_authorized") is False
        and receipt.get("credential_material_included") is False
        and _valid_sha256(receipt.get("fingerprint"))
        and isinstance(receipt.get("receipt_auth"), str)
    )
    if not structural_ok:
        return reject("INVALID_USER_INTENT", "user intent receipt structure is invalid")

    issuer_id = str(receipt["issuer_id"])
    key = _key((trusted_keys or {}).get(issuer_id))
    if not key:
        return reject("UNTRUSTED_USER_INTENT", "user intent issuer is not trusted")

    expected_fingerprint = hashlib.sha256(_canonical(receipt)).hexdigest()
    if not hmac.compare_digest(str(receipt["fingerprint"]).lower(), expected_fingerprint.lower()):
        return reject("INVALID_USER_INTENT", "user intent fingerprint does not match receipt")
    expected_auth = hmac.new(key, _canonical(receipt), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(receipt["receipt_auth"]).lower(), expected_auth.lower()):
        return reject("INVALID_USER_INTENT", "user intent receipt authentication failed")

    now = _utc(evaluated_at)
    issued_at = _parse_time(receipt.get("issued_at"))
    expires_at = _parse_time(receipt.get("expires_at"))
    if issued_at is None or expires_at is None or expires_at <= issued_at:
        return reject("INVALID_USER_INTENT", "user intent receipt time bounds are invalid")
    if issued_at - now > timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
        return reject("FUTURE_USER_INTENT", "user intent receipt is not active yet")
    if now >= expires_at:
        return reject("STALE_USER_INTENT", "user intent receipt has expired")

    bindings = {
        "source_sha": str(source_sha).strip(),
        "caller_fingerprint": caller_fingerprint.lower(),
        "subject_fingerprint": subject_fingerprint.lower(),
        "provider": provider.strip().lower(),
        "environment": environment.strip().lower(),
        "action": action.strip().lower(),
        "resource_fingerprint": resource_fingerprint.lower(),
    }
    for field, expected in bindings.items():
        actual = str(receipt.get(field, "")).strip().lower()
        if actual != str(expected).strip().lower():
            return reject(
                "USER_INTENT_CONFLICT",
                f"user intent receipt {field} does not match requested workflow",
            )

    return UserIntentDecision(
        True,
        "USER_INTENT_VERIFIED",
        "explicit user intent is bound to this exact provider read",
        receipt_id,
        intent_fingerprint,
    )
