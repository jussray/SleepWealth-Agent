from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

SCHEMA = "sleepwealth-human-read-grant-v1"
MIN_PERMISSION_KEY_BYTES = 32
MAX_PERMISSION_TTL_SECONDS = 24 * 60 * 60
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
    return result if len(result) >= MIN_PERMISSION_KEY_BYTES else b""


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


def _normalized_values(values: Sequence[str], *, field: str) -> tuple[str, ...]:
    normalized = tuple(
        dict.fromkeys(str(value).strip().lower() for value in values if str(value).strip())
    )
    if not normalized:
        raise ValueError(f"{field} must contain at least one value")
    return normalized


@dataclass(frozen=True, slots=True)
class HumanReadGrantDecision:
    accepted: bool
    classification: str
    reason: str
    grant_id: str | None = None
    scope_fingerprint: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "classification": self.classification,
            "reason": self.reason,
            "grant_id": self.grant_id,
            "scope_fingerprint": self.scope_fingerprint,
        }


def issue_human_read_grant(
    *,
    issuer_id: str,
    issuer_key: str | bytes,
    source_sha: str,
    caller_fingerprint: str,
    subject_fingerprint: str,
    provider: str,
    environment: str,
    allowed_actions: Sequence[str],
    allowed_resource_prefixes: Sequence[str],
    human_approval_fingerprint: str,
    purpose: str = "human-approved-read-autonomy",
    issued_at: datetime | None = None,
    ttl_seconds: int = 60 * 60,
) -> dict[str, object]:
    """Issue a bounded standing grant for read-only provider autonomy.

    A trusted control plane calls this only after explicit human approval.
    The grant permits repeated reads inside the declared scope until expiry.
    It never grants transaction, payment, signing, capital-allocation, or
    execution authority and is intentionally not exposed as an MCP tool.
    """

    key = _key(issuer_key)
    if not issuer_id.strip() or not key:
        raise ValueError("trusted permission issuer id and a 32+ byte key are required")
    for name, value in {
        "caller_fingerprint": caller_fingerprint,
        "subject_fingerprint": subject_fingerprint,
        "human_approval_fingerprint": human_approval_fingerprint,
    }.items():
        if not _valid_sha256(value):
            raise ValueError(f"{name} must be a SHA-256 fingerprint")
    source_sha = str(source_sha or "").strip()
    if len(source_sha) < 7:
        raise ValueError("source_sha is required")
    provider = str(provider or "").strip().lower()
    environment = str(environment or "").strip().lower()
    purpose = str(purpose or "").strip().lower()
    if not provider or not environment or not purpose:
        raise ValueError("provider, environment, and purpose are required")

    actions = _normalized_values(allowed_actions, field="allowed_actions")
    prefixes = tuple(
        dict.fromkeys(str(value).strip() for value in allowed_resource_prefixes if str(value).strip())
    )
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool):
        raise ValueError("ttl_seconds must be an integer")
    if not 1 <= ttl_seconds <= MAX_PERMISSION_TTL_SECONDS:
        raise ValueError(
            f"permission TTL must be 1..{MAX_PERMISSION_TTL_SECONDS} seconds"
        )

    scope = {
        "source_sha": source_sha,
        "caller_fingerprint": caller_fingerprint.lower(),
        "subject_fingerprint": subject_fingerprint.lower(),
        "provider": provider,
        "environment": environment,
        "allowed_actions": list(actions),
        "allowed_resource_prefixes": list(prefixes),
        "purpose": purpose,
    }
    scope_fingerprint = hashlib.sha256(
        json.dumps(scope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()

    now = _utc(issued_at)
    expires = now + timedelta(seconds=ttl_seconds)
    receipt: dict[str, object] = {
        "schema": SCHEMA,
        "event": "human_read_grant_issued",
        "classification": "HUMAN_READ_PERMISSION_GRANTED",
        "grant_id": f"HRG-{uuid.uuid4().hex}",
        "issuer_id": issuer_id.strip(),
        **scope,
        "scope_fingerprint": scope_fingerprint,
        "human_approval_fingerprint": human_approval_fingerprint.lower(),
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "human_authorization_present": True,
        "standing_read_grant": True,
        "provider_read_authorized": True,
        "allocation_authorized": False,
        "execution_authorized": False,
        "money_moving_authorized": False,
        "transaction_construction_authorized": False,
        "payment_authorized": False,
        "credential_material_included": False,
    }
    receipt["fingerprint"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    receipt["receipt_auth"] = hmac.new(key, _canonical(receipt), hashlib.sha256).hexdigest()
    return receipt


def validate_human_read_grant(
    receipt: Mapping[str, object] | None,
    *,
    trusted_keys: Mapping[str, object] | None,
    source_sha: str,
    caller_fingerprint: str,
    subject_fingerprint: str,
    provider: str,
    environment: str,
    action: str,
    resource_path: str | None = None,
    evaluated_at: datetime | None = None,
) -> HumanReadGrantDecision:
    if receipt is None:
        return HumanReadGrantDecision(
            False,
            "MISSING_HUMAN_PERMISSION",
            "explicit human read permission is required",
        )

    grant_id = str(receipt.get("grant_id", "")) or None
    scope_fingerprint = str(receipt.get("scope_fingerprint", "")) or None

    def reject(classification: str, reason: str) -> HumanReadGrantDecision:
        return HumanReadGrantDecision(
            False,
            classification,
            reason,
            grant_id,
            scope_fingerprint,
        )

    actions = receipt.get("allowed_actions")
    prefixes = receipt.get("allowed_resource_prefixes")
    structural_ok = (
        receipt.get("schema") == SCHEMA
        and receipt.get("event") == "human_read_grant_issued"
        and receipt.get("classification") == "HUMAN_READ_PERMISSION_GRANTED"
        and isinstance(grant_id, str)
        and grant_id.startswith("HRG-")
        and isinstance(receipt.get("issuer_id"), str)
        and bool(str(receipt.get("issuer_id", "")).strip())
        and len(str(receipt.get("source_sha", "")).strip()) >= 7
        and _valid_sha256(receipt.get("caller_fingerprint"))
        and _valid_sha256(receipt.get("subject_fingerprint"))
        and _valid_sha256(receipt.get("human_approval_fingerprint"))
        and _valid_sha256(scope_fingerprint)
        and isinstance(actions, list)
        and bool(actions)
        and all(isinstance(value, str) and bool(value.strip()) for value in actions)
        and isinstance(prefixes, list)
        and all(isinstance(value, str) and bool(value.strip()) for value in prefixes)
        and receipt.get("human_authorization_present") is True
        and receipt.get("standing_read_grant") is True
        and receipt.get("provider_read_authorized") is True
        and receipt.get("allocation_authorized") is False
        and receipt.get("execution_authorized") is False
        and receipt.get("money_moving_authorized") is False
        and receipt.get("transaction_construction_authorized") is False
        and receipt.get("payment_authorized") is False
        and receipt.get("credential_material_included") is False
        and _valid_sha256(receipt.get("fingerprint"))
        and isinstance(receipt.get("receipt_auth"), str)
    )
    if not structural_ok:
        return reject("INVALID_HUMAN_PERMISSION", "human read grant structure is invalid")

    issuer_id = str(receipt["issuer_id"])
    key = _key((trusted_keys or {}).get(issuer_id))
    if not key:
        return reject("UNTRUSTED_HUMAN_PERMISSION", "human permission issuer is not trusted")

    expected_fingerprint = hashlib.sha256(_canonical(receipt)).hexdigest()
    if not hmac.compare_digest(str(receipt["fingerprint"]).lower(), expected_fingerprint.lower()):
        return reject("INVALID_HUMAN_PERMISSION", "human read grant fingerprint does not match")
    expected_auth = hmac.new(key, _canonical(receipt), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(receipt["receipt_auth"]).lower(), expected_auth.lower()):
        return reject("INVALID_HUMAN_PERMISSION", "human read grant authentication failed")

    expected_scope = {
        "source_sha": str(receipt.get("source_sha", "")).strip(),
        "caller_fingerprint": str(receipt.get("caller_fingerprint", "")).lower(),
        "subject_fingerprint": str(receipt.get("subject_fingerprint", "")).lower(),
        "provider": str(receipt.get("provider", "")).strip().lower(),
        "environment": str(receipt.get("environment", "")).strip().lower(),
        "allowed_actions": [str(value).strip().lower() for value in actions],
        "allowed_resource_prefixes": [str(value).strip() for value in prefixes],
        "purpose": str(receipt.get("purpose", "")).strip().lower(),
    }
    calculated_scope = hashlib.sha256(
        json.dumps(expected_scope, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    if not hmac.compare_digest(str(scope_fingerprint).lower(), calculated_scope.lower()):
        return reject("INVALID_HUMAN_PERMISSION", "human read grant scope fingerprint does not match")

    now = _utc(evaluated_at)
    issued_at = _parse_time(receipt.get("issued_at"))
    expires_at = _parse_time(receipt.get("expires_at"))
    if issued_at is None or expires_at is None or expires_at <= issued_at:
        return reject("INVALID_HUMAN_PERMISSION", "human read grant time bounds are invalid")
    if issued_at - now > timedelta(seconds=MAX_CLOCK_SKEW_SECONDS):
        return reject("FUTURE_HUMAN_PERMISSION", "human read grant is not active yet")
    if now >= expires_at:
        return reject("STALE_HUMAN_PERMISSION", "human read grant has expired")

    bindings = {
        "source_sha": str(source_sha).strip(),
        "caller_fingerprint": caller_fingerprint.lower(),
        "subject_fingerprint": subject_fingerprint.lower(),
        "provider": provider.strip().lower(),
        "environment": environment.strip().lower(),
    }
    for field, expected in bindings.items():
        actual = str(receipt.get(field, "")).strip().lower()
        if actual != str(expected).strip().lower():
            return reject(
                "HUMAN_PERMISSION_CONFLICT",
                f"human read grant {field} does not match requested workflow",
            )

    normalized_action = str(action or "").strip().lower()
    allowed_actions = {str(value).strip().lower() for value in actions}
    if normalized_action not in allowed_actions:
        return reject(
            "HUMAN_PERMISSION_SCOPE_CONFLICT",
            "requested provider action is outside the human-approved read scope",
        )

    if resource_path is not None:
        path = str(resource_path).strip()
        allowed_prefixes = tuple(str(value).strip() for value in prefixes)
        if allowed_prefixes and not any(path.startswith(prefix) for prefix in allowed_prefixes):
            return reject(
                "HUMAN_PERMISSION_SCOPE_CONFLICT",
                "requested provider resource is outside the human-approved read scope",
            )

    return HumanReadGrantDecision(
        True,
        "HUMAN_READ_PERMISSION_VERIFIED",
        "standing human read permission covers this provider request",
        grant_id,
        scope_fingerprint,
    )
