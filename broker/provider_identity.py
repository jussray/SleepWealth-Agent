"""Canonical non-secret provider/account fingerprinting.

The fingerprint binds provider receipts without exposing raw brokerage account
identifiers. It is a continuity marker only. It never authenticates a person,
proves age, grants provider permission, or creates execution authority.
"""

from __future__ import annotations

import hashlib
import json
from typing import Mapping

SCHEMA = "sleepwealth-provider-account-v1"


def provider_account_fingerprint(
    provider: str,
    stable_identifiers: Mapping[str, object],
) -> str:
    """Hash one provider plus its stable account identifiers deterministically."""

    normalized_provider = str(provider or "").strip().lower()
    if not normalized_provider:
        raise ValueError("provider must not be empty")
    if not isinstance(stable_identifiers, Mapping) or not stable_identifiers:
        raise ValueError("stable account identifiers are required")

    normalized: dict[str, str] = {}
    for raw_key, raw_value in stable_identifiers.items():
        key = str(raw_key or "").strip().lower()
        value = str(raw_value or "").strip()
        if not key or not value:
            continue
        normalized[key] = value
    if not normalized:
        raise ValueError("at least one non-empty stable account identifier is required")

    payload = {
        "schema": SCHEMA,
        "provider": normalized_provider,
        "identifiers": dict(sorted(normalized.items())),
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
