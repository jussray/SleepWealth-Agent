"""Two distinct account models for Sleep Wealth. They never share a scope.

- CUSTOMER_CONNECTED: each customer's own brokerage account, with that customer's
  consent, credentials and per-account capital ceiling.
- POOLED_MANAGED: one governed pool. Requires legal, regulatory, custody and
  participant prerequisites before any pooled customer funds are accepted.

This module is an authorization evaluator. It never grants live execution.
Every gate must be a receipt signed by a trusted issuer with a >=32-byte key,
bound to one subject, and unexpired. Caller booleans are not evidence.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from collections.abc import Iterable, Mapping
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any

MIN_KEY_BYTES = 32


class AccountModel(StrEnum):
    CUSTOMER_CONNECTED = "customer-connected"
    POOLED_MANAGED = "pooled-managed"


CUSTOMER_GATES = (
    "customer_consent",
    "broker_oauth_grant",
    "account_risk_ceiling",
)
POOLED_GATES = (
    "legal_entity",
    "regulatory_approval",
    "custody_agreement",
    "participant_agreements",
    "independent_risk_authority",
    "pooled_capital_ceiling",
    "participant_accounting",
)
REQUIRED_GATES = {
    AccountModel.CUSTOMER_CONNECTED: CUSTOMER_GATES,
    AccountModel.POOLED_MANAGED: POOLED_GATES,
}
CAPITAL_GATES = frozenset({"account_risk_ceiling", "pooled_capital_ceiling"})


def _canonical(fields: Mapping[str, Any]) -> bytes:
    return json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _key(value: object) -> bytes:
    if isinstance(value, str):
        value = value.encode("utf-8")
    if not isinstance(value, bytes) or len(value) < MIN_KEY_BYTES:
        return b""
    return value


def sign_receipt(fields: Mapping[str, Any], key: bytes) -> str:
    """Issuer-side helper. Callers that hold a trusted key use this to mint receipts."""
    k = _key(key)
    if not k:
        raise ValueError("receipt key must be at least 32 bytes")
    return hmac.new(k, _canonical(fields), hashlib.sha256).hexdigest()


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None and dt.utcoffset() is not None else None


def verify_gate_receipt(
    receipt: Any,
    *,
    gate: str,
    subject: str,
    key: bytes,
    now: datetime,
    trusted_issuers: Iterable[str],
) -> str | None:
    """Return None when valid, otherwise a machine-readable reason."""
    if not isinstance(receipt, Mapping):
        return "receipt_not_object"
    if not _key(key):
        return "trusted_key_missing_or_short"
    if receipt.get("gate") != gate:
        return "gate_mismatch"
    if receipt.get("subject") != subject:
        return "subject_mismatch"
    if receipt.get("issued_by") not in set(trusted_issuers):
        return "untrusted_issuer"
    expires = _parse_time(receipt.get("expires_at"))
    if expires is None:
        return "expiry_unparseable"
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return "current_time_untrusted"
    if now >= expires:
        return "receipt_expired"
    signature = receipt.get("signature")
    if not isinstance(signature, str):
        return "signature_missing"
    if len(signature) != 64 or not signature.isascii() or any(c not in "0123456789abcdefABCDEF" for c in signature):
        return "signature_invalid"
    fields = {k: v for k, v in receipt.items() if k != "signature"}
    expected = hmac.new(_key(key), _canonical(fields), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature.lower(), expected):
        return "signature_invalid"
    return None


def evaluate_account_scope(
    *,
    model: AccountModel,
    subject: str,
    receipts: Iterable[Mapping[str, Any]],
    key: bytes,
    now: datetime,
    trusted_issuers: Iterable[str],
    capital_ceiling: float,
) -> dict[str, Any]:
    """Decide whether one account scope has every required legal/consent gate proven.

    Output never grants live execution. A passing result is only eligibility for
    the existing LiveGate review.
    """
    base = {
        "model": model.value if isinstance(model, AccountModel) else str(model),
        "subject": subject,
        "live_execution_authorized": False,
        "authorizes_real_money": False,
    }
    if not isinstance(model, AccountModel):
        return {**base, "status": "REJECTED", "reasons": ["unsupported_account_model"]}
    if not isinstance(subject, str) or not subject.strip():
        return {**base, "status": "REJECTED", "reasons": ["subject_required"]}
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return {**base, "status": "REJECTED", "reasons": ["trusted_clock_required"]}
    if not isinstance(capital_ceiling, (int, float)) or isinstance(capital_ceiling, bool) \
            or not math.isfinite(capital_ceiling) or capital_ceiling <= 0:
        return {**base, "status": "REJECTED", "reasons": ["capital_ceiling_must_be_positive"]}

    receipts = list(receipts)
    issuers = list(trusted_issuers)
    reasons: dict[str, str] = {}
    for gate in REQUIRED_GATES[model]:
        candidates = [r for r in receipts if isinstance(r, Mapping) and r.get("gate") == gate]
        if not candidates:
            reasons[gate] = "missing_receipt"
            continue
        failures: list[str] = []
        valid = False
        for candidate in candidates:
            failure = verify_gate_receipt(
                candidate, gate=gate, subject=subject, key=key,
                now=now, trusted_issuers=issuers,
            )
            if failure is None and gate in CAPITAL_GATES:
                receipt_ceiling = candidate.get("capital_ceiling")
                if (isinstance(receipt_ceiling, bool)
                    or not isinstance(receipt_ceiling, (int, float))
                    or not math.isfinite(receipt_ceiling)
                    or receipt_ceiling <= 0
                    or receipt_ceiling != capital_ceiling):
                    failure = "capital_ceiling_mismatch"
            if failure is None:
                valid = True
                break
            failures.append(failure)
        if not valid:
            reasons[gate] = failures[0] if failures else "unknown"
    if reasons:
        missing = sorted(reasons)
        return {**base, "status": "BLOCKED", "missing_or_invalid_gates": missing,
                "reasons": [f"{g}:{reasons[g]}" for g in missing], "capital_ceiling": capital_ceiling}
    return {**base, "status": "ELIGIBLE_FOR_LIVE_GATE_REVIEW", "reasons": [],
            "capital_ceiling": capital_ceiling}
