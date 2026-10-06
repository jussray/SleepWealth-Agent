from __future__ import annotations

import hashlib
import hmac
import json
import math
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping

MIN_AUTHORITY_KEY_BYTES = 32
MAX_AUTHORITY_TTL_SECONDS = 5 * 60
MAX_CLOCK_SKEW_SECONDS = 5 * 60
SCHEMA = "sleepwealth-product-action-authority-v1"


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
    return result if len(result) >= MIN_AUTHORITY_KEY_BYTES else b""


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


def _finite_nonnegative(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number >= 0


@dataclass(frozen=True, slots=True)
class ProductAuthorityDecision:
    accepted: bool
    classification: str
    reason: str
    receipt_id: str | None = None
    subject_fingerprint: str | None = None
    provider: str | None = None
    action: str | None = None
    environment: str | None = None
    account_fingerprint: str | None = None
    resource_fingerprint: str | None = None
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "classification": self.classification,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "subject_fingerprint": self.subject_fingerprint,
            "provider": self.provider,
            "action": self.action,
            "environment": self.environment,
            "account_fingerprint": self.account_fingerprint,
            "resource_fingerprint": self.resource_fingerprint,
            "idempotency_key": self.idempotency_key,
        }


def issue_product_action_authority(
    *,
    issuer_id: str,
    issuer_key: str | bytes,
    subject_fingerprint: str,
    provider: str,
    environment: str,
    account_fingerprint: str,
    action: str,
    resource_fingerprint: str,
    human_approval_fingerprint: str,
    eligible_adult_receipt_fingerprint: str,
    provider_session_fingerprint: str,
    idempotency_key: str,
    max_amount: float | int | None = None,
    currency: str | None = None,
    issued_at: datetime | None = None,
    ttl_seconds: int = 120,
) -> dict[str, object]:
    """Issue a short-lived authority receipt from a trusted product control plane.

    This function is intentionally not exposed as an MCP tool. The trusted
    deployment control plane must first verify adult eligibility, current human
    approval, and a live provider/account session. The resulting fingerprints are
    bound here so an MCP caller cannot swap subject, provider, account, action,
    payload, amount, or idempotency identity after approval.
    """

    key = _key(issuer_key)
    if not issuer_id.strip() or not key:
        raise ValueError("trusted authority issuer id and a 32+ byte key are required")
    required_fingerprints = {
        "subject_fingerprint": subject_fingerprint,
        "account_fingerprint": account_fingerprint,
        "resource_fingerprint": resource_fingerprint,
        "human_approval_fingerprint": human_approval_fingerprint,
        "eligible_adult_receipt_fingerprint": eligible_adult_receipt_fingerprint,
        "provider_session_fingerprint": provider_session_fingerprint,
    }
    if not all(_valid_sha256(value) for value in required_fingerprints.values()):
        raise ValueError("all authority bindings must be SHA-256 fingerprints")
    if not provider.strip() or not environment.strip() or not action.strip():
        raise ValueError("provider, environment, and action are required")
    if not idempotency_key.strip():
        raise ValueError("idempotency_key is required")
    if max_amount is not None and not _finite_nonnegative(max_amount):
        raise ValueError("max_amount must be finite and nonnegative")
    if max_amount is not None and (currency is None or not currency.strip()):
        raise ValueError("currency is required when max_amount is supplied")
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool):
        raise ValueError("ttl_seconds must be an integer")
    if not 1 <= ttl_seconds <= MAX_AUTHORITY_TTL_SECONDS:
        raise ValueError(f"authority TTL must be 1..{MAX_AUTHORITY_TTL_SECONDS} seconds")

    now = _utc(issued_at)
    expires = now + timedelta(seconds=ttl_seconds)
    receipt: dict[str, object] = {
        "schema": SCHEMA,
        "event": "product_action_authority_issued",
        "classification": "PRODUCT_ACTION_AUTHORIZED",
        "receipt_id": f"PAA-{uuid.uuid4().hex}",
        "issuer_id": issuer_id.strip(),
        "subject_fingerprint": subject_fingerprint.lower(),
        "provider": provider.strip().lower(),
        "environment": environment.strip().lower(),
        "account_fingerprint": account_fingerprint.lower(),
        "action": action.strip().lower(),
        "resource_fingerprint": resource_fingerprint.lower(),
        "human_approval_fingerprint": human_approval_fingerprint.lower(),
        "eligible_adult_receipt_fingerprint": eligible_adult_receipt_fingerprint.lower(),
        "provider_session_fingerprint": provider_session_fingerprint.lower(),
        "idempotency_key": idempotency_key.strip(),
        "max_amount": float(max_amount) if max_amount is not None else None,
        "currency": currency.strip().upper() if currency else None,
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "eligible_adult_required": True,
        "provider_permission_required": True,
        "human_approval_required": True,
        "execution_authorized": True,
        "credential_material_included": False,
    }
    receipt["fingerprint"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    receipt["receipt_auth"] = hmac.new(key, _canonical(receipt), hashlib.sha256).hexdigest()
    return receipt


def validate_product_action_authority(
    receipt: Mapping[str, object] | None,
    *,
    trusted_keys: Mapping[str, object] | None,
    subject_fingerprint: str,
    provider: str,
    environment: str,
    account_fingerprint: str,
    action: str,
    resource_fingerprint: str,
    idempotency_key: str,
    requested_amount: float | int | None = None,
    currency: str | None = None,
    evaluated_at: datetime | None = None,
) -> ProductAuthorityDecision:
    if receipt is None:
        return ProductAuthorityDecision(False, "MISSING", "product action authority is required")

    receipt_id = str(receipt.get("receipt_id", "")) or None
    receipt_subject = str(receipt.get("subject_fingerprint", "")) or None
    receipt_provider = str(receipt.get("provider", "")) or None
    receipt_action = str(receipt.get("action", "")) or None
    receipt_environment = str(receipt.get("environment", "")) or None
    receipt_account = str(receipt.get("account_fingerprint", "")) or None
    receipt_resource = str(receipt.get("resource_fingerprint", "")) or None
    receipt_idem = str(receipt.get("idempotency_key", "")) or None

    def reject(classification: str, reason: str) -> ProductAuthorityDecision:
        return ProductAuthorityDecision(
            False,
            classification,
            reason,
            receipt_id,
            receipt_subject,
            receipt_provider,
            receipt_action,
            receipt_environment,
            receipt_account,
            receipt_resource,
            receipt_idem,
        )

    structural_ok = (
        receipt.get("schema") == SCHEMA
        and receipt.get("event") == "product_action_authority_issued"
        and receipt.get("classification") == "PRODUCT_ACTION_AUTHORIZED"
        and isinstance(receipt_id, str)
        and receipt_id.startswith("PAA-")
        and isinstance(receipt.get("issuer_id"), str)
        and bool(str(receipt.get("issuer_id", "")).strip())
        and _valid_sha256(receipt_subject)
        and _valid_sha256(receipt_account)
        and _valid_sha256(receipt_resource)
        and _valid_sha256(receipt.get("human_approval_fingerprint"))
        and _valid_sha256(receipt.get("eligible_adult_receipt_fingerprint"))
        and _valid_sha256(receipt.get("provider_session_fingerprint"))
        and isinstance(receipt_provider, str)
        and bool(receipt_provider.strip())
        and isinstance(receipt_environment, str)
        and bool(receipt_environment.strip())
        and isinstance(receipt_action, str)
        and bool(receipt_action.strip())
        and isinstance(receipt_idem, str)
        and bool(receipt_idem.strip())
        and receipt.get("eligible_adult_required") is True
        and receipt.get("provider_permission_required") is True
        and receipt.get("human_approval_required") is True
        and receipt.get("execution_authorized") is True
        and receipt.get("credential_material_included") is False
        and _valid_sha256(receipt.get("fingerprint"))
        and hmac.compare_digest(
            str(receipt.get("fingerprint")).lower(),
            hashlib.sha256(_canonical(receipt)).hexdigest().lower(),
        )
    )
    if not structural_ok:
        return reject("INVALID", "product action authority invariants failed")

    issuer_id = str(receipt["issuer_id"])
    key = _key((trusted_keys or {}).get(issuer_id))
    provided_auth = receipt.get("receipt_auth")
    expected_auth = hmac.new(key, _canonical(receipt), hashlib.sha256).hexdigest() if key else ""
    if not (
        key
        and _valid_sha256(provided_auth)
        and hmac.compare_digest(str(provided_auth).lower(), expected_auth.lower())
    ):
        return reject("UNTRUSTED", "product action authority authentication failed")

    issued = _parse_time(receipt.get("issued_at"))
    expires = _parse_time(receipt.get("expires_at"))
    now = _utc(evaluated_at)
    freshness_ok = False
    if issued and expires:
        issued_utc = issued.astimezone(timezone.utc)
        expires_utc = expires.astimezone(timezone.utc)
        ttl = (expires_utc - issued_utc).total_seconds()
        freshness_ok = (
            0 < ttl <= MAX_AUTHORITY_TTL_SECONDS
            and issued_utc <= now + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS)
            and now <= expires_utc
        )
    if not freshness_ok:
        return reject("STALE", "product action authority is outside its freshness window")

    if not _valid_sha256(subject_fingerprint):
        return reject("INVALID_REQUEST", "subject_fingerprint must be a SHA-256 value")
    requested_scope = (
        subject_fingerprint.lower(),
        provider.strip().lower(),
        environment.strip().lower(),
        account_fingerprint.lower(),
        action.strip().lower(),
        resource_fingerprint.lower(),
        idempotency_key.strip(),
    )
    receipt_scope = (
        str(receipt_subject).lower(),
        str(receipt_provider).lower(),
        str(receipt_environment).lower(),
        str(receipt_account).lower(),
        str(receipt_action).lower(),
        str(receipt_resource).lower(),
        str(receipt_idem),
    )
    if requested_scope != receipt_scope:
        return reject(
            "SCOPE_CONFLICT",
            "subject/provider/account/action/resource/idempotency scope changed",
        )

    max_amount = receipt.get("max_amount")
    receipt_currency = receipt.get("currency")
    if requested_amount is not None:
        if not _finite_nonnegative(requested_amount):
            return reject("INVALID_REQUEST", "requested amount must be finite and nonnegative")
        if max_amount is None or not _finite_nonnegative(max_amount):
            return reject("AMOUNT_UNBOUND", "authority does not contain an amount ceiling")
        if float(requested_amount) > float(max_amount):
            return reject("AMOUNT_EXCEEDED", "requested amount exceeds authority ceiling")
        if not currency or str(receipt_currency or "").upper() != currency.strip().upper():
            return reject("CURRENCY_CONFLICT", "requested currency does not match authority")

    return ProductAuthorityDecision(
        True,
        "VERIFIED_PRODUCT_AUTHORITY",
        "trusted product authority is fresh and exactly scoped",
        receipt_id,
        receipt_subject,
        receipt_provider,
        receipt_action,
        receipt_environment,
        receipt_account,
        receipt_resource,
        receipt_idem,
    )
