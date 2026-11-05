"""Bind independently authenticated provider sessions to both account models.

This is an advisory pre-live control. No broker calls, credentials, money movement,
execution approval, or real-money authority are produced by this module.
"""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
from typing import Any

from execution.account_models import (
    AccountModel, evaluate_account_scope, valid_account_binding,
)
from gate.provider_session import (
    ALLOWED_ASSET_PERMISSIONS, validate_provider_session_receipt,
)


def evaluate_bound_account_preflight(
    *,
    model: AccountModel,
    subject: str,
    capital_ceiling: float,
    scope_receipts: Iterable[Mapping[str, Any]],
    account_receipt_key: bytes,
    trusted_account_issuers: Iterable[str],
    provider_session_receipt: Mapping[str, object] | None,
    trusted_provider_session_keys: Mapping[str, object],
    expected_provider: str,
    required_lane: str,
    now: datetime,
) -> dict[str, Any]:
    """Require a signed, fresh broker account session for one isolated scope.

    expected_provider and trusted keys must come from runtime configuration,
    never from untrusted model output or an HTTP request. A provider session is
    independent observation; a scope receipt is independent account governance.
    Both are required before *review*, and neither grants execution authority.
    """
    base = {
        "status": "BLOCKED",
        "live_execution_authorized": False,
        "authorizes_real_money": False,
        "reason": "",
    }

    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        return {**base, "status": "REJECTED", "reason": "trusted_clock_required"}
    if not isinstance(model, AccountModel):
        return {**base, "status": "REJECTED", "reason": "unsupported_account_model"}
    if not isinstance(subject, str) or not subject.strip():
        return {**base, "status": "REJECTED", "reason": "subject_required"}
    if not isinstance(expected_provider, str) or not expected_provider.strip():
        return {**base, "status": "REJECTED", "reason": "expected_provider_required"}
    if required_lane not in ALLOWED_ASSET_PERMISSIONS:
        return {**base, "status": "REJECTED", "reason": "unsupported_market_lane"}

    if not isinstance(provider_session_receipt, Mapping):
        return {**base, "reason": "provider_session_unverified"}
    if not isinstance(trusted_provider_session_keys, Mapping):
        return {**base, "reason": "provider_session_unverified"}

    try:
        session = validate_provider_session_receipt(
            provider_session_receipt,
            trusted_keys=trusted_provider_session_keys,
            evaluated_at=now,
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return {**base, "reason": "provider_session_unverified"}

    if session.get("classification") != "VERIFIED_LIVE_SESSION" or session.get("accepted") is not True:
        return {**base, "reason": "provider_session_unverified"}

    if str(session.get("provider", "")).strip().lower() != expected_provider.strip().lower():
        return {**base, "reason": "provider_mismatch"}

    binding = session.get("account_fingerprint")
    if not valid_account_binding(binding):
        return {**base, "reason": "provider_account_binding_invalid"}
    if required_lane not in session.get("asset_permissions", []):
        return {**base, "reason": "lane_not_permitted"}

    try:
        scope = evaluate_account_scope(
            model=model,
            subject=subject,
            account_binding=binding,
            receipts=scope_receipts,
            key=account_receipt_key,
            now=now,
            trusted_issuers=trusted_account_issuers,
            capital_ceiling=capital_ceiling,
        )
    except (AttributeError, KeyError, TypeError, ValueError):
        return {**base, "reason": "account_scope_unverified"}

    if scope.get("status") != "ELIGIBLE_FOR_LIVE_GATE_REVIEW":
        reason = "account_binding_mismatch" if any(
            "account_binding_mismatch" in str(item)
            for item in scope.get("reasons", [])
        ) else "account_scope_unverified"
        return {**base, "reason": reason, "account_scope_status": scope.get("status")}

    return {
        **base,
        "status": "ELIGIBLE_FOR_LIVE_GATE_REVIEW",
        "reason": "signed account scope and independently authenticated provider session match",
        "model": model.value,
        "subject": subject,
        "provider": session["provider"],
        "account_binding": binding,
        "capital_ceiling": capital_ceiling,
        "provider_session_fingerprint": session["fingerprint"],
    }
