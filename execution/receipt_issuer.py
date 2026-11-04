"""Trusted-runtime receipt issuer for account-scope gates.

Mints the subject-bound, expiring, HMAC-signed receipts that
execution/account_models.py verifies. Minting here does not grant authority:
a receipt only counts when the verifier also trusts its issuer and key.

The signing key is read from an environment variable and has no default.
A missing or short key fails closed.
"""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from execution.account_models import CUSTOMER_GATES, MIN_KEY_BYTES, POOLED_GATES, sign_receipt

KEY_ENV_VAR = "SLEEPWEALTH_RECEIPT_KEY"
KNOWN_GATES = frozenset(CUSTOMER_GATES) | frozenset(POOLED_GATES)
MAX_TTL_SECONDS = 24 * 60 * 60


def load_issuer_key(environ: Mapping[str, str] | None = None) -> bytes:
    """Return the issuer key from the environment, or fail closed."""
    env = os.environ if environ is None else environ
    raw = env.get(KEY_ENV_VAR)
    if not raw:
        raise RuntimeError(f"{KEY_ENV_VAR} is not set; refusing to mint receipts")
    key = raw.encode("utf-8")
    if len(key) < MIN_KEY_BYTES:
        raise RuntimeError(f"{KEY_ENV_VAR} must be at least {MIN_KEY_BYTES} bytes")
    return key


def mint_gate_receipt(
    *,
    gate: str,
    subject: str,
    issuer: str,
    key: bytes,
    now: datetime,
    ttl_seconds: int = MAX_TTL_SECONDS,
) -> dict[str, Any]:
    """Mint one signed receipt for a single gate and subject."""
    if gate not in KNOWN_GATES:
        raise ValueError(f"unknown gate: {gate}")
    if not isinstance(subject, str) or not subject.strip():
        raise ValueError("subject is required")
    if not isinstance(issuer, str) or not issuer.strip():
        raise ValueError("issuer is required")
    if isinstance(ttl_seconds, bool) or not isinstance(ttl_seconds, int):
        raise ValueError("ttl_seconds must be an integer")
    if not 0 < ttl_seconds <= MAX_TTL_SECONDS:
        raise ValueError(f"ttl_seconds must be between 1 and {MAX_TTL_SECONDS}")
    if now.tzinfo is None:
        raise ValueError("now must be timezone-aware")

    expires = (now.astimezone(timezone.utc) + timedelta(seconds=ttl_seconds)).replace(microsecond=0)
    fields = {
        "gate": gate,
        "subject": subject,
        "issued_by": issuer,
        "expires_at": expires.isoformat(),
    }
    return {**fields, "signature": sign_receipt(fields, key)}


def mint_scope_receipts(
    *,
    gates: list[str] | tuple[str, ...],
    subject: str,
    issuer: str,
    key: bytes,
    now: datetime,
    ttl_seconds: int = MAX_TTL_SECONDS,
) -> list[dict[str, Any]]:
    """Mint one receipt per gate for one subject. Duplicate gates are rejected."""
    if len(set(gates)) != len(gates):
        raise ValueError("duplicate gate in request")
    return [
        mint_gate_receipt(gate=g, subject=subject, issuer=issuer, key=key, now=now, ttl_seconds=ttl_seconds)
        for g in gates
    ]
