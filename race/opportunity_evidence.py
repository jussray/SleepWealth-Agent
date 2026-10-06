from __future__ import annotations

import hashlib
import json
from typing import Mapping

from race.identity import product_identity_receipt

OPPORTUNITY_EVIDENCE_CONTRACT = "sleepwealth/opportunity-evidence@v1"


def _digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _sha256(value: object, field: str) -> str:
    cleaned = str(value or "").strip().lower()
    if len(cleaned) != 64 or any(char not in "0123456789abcdef" for char in cleaned):
        raise ValueError(f"{field} must be a SHA-256 digest")
    return cleaned


def opportunity_evidence_receipt(
    *,
    provider: str,
    action: str,
    resource_fingerprint: str,
    provider_result: Mapping[str, object],
) -> dict[str, object]:
    product = product_identity_receipt()
    provider_fingerprint = _sha256(
        provider_result.get("provider_fingerprint"),
        "provider_fingerprint",
    )
    capability_fingerprint = _sha256(
        provider_result.get("capability_fingerprint"),
        "capability_fingerprint",
    )
    result_fingerprint = _sha256(
        provider_result.get("result_fingerprint"),
        "result_fingerprint",
    )
    resource_fingerprint = _sha256(resource_fingerprint, "resource_fingerprint")
    observed_at = str(provider_result.get("observed_at", "")).strip()
    if not observed_at:
        raise ValueError("provider_result observed_at is required")

    subject = {
        "contract": OPPORTUNITY_EVIDENCE_CONTRACT,
        "product_fingerprint": product["fingerprint"],
        "provider": str(provider).strip().lower(),
        "provider_fingerprint": provider_fingerprint,
        "capability_fingerprint": capability_fingerprint,
        "action": str(action).strip().lower(),
        "resource_fingerprint": resource_fingerprint,
        "result_fingerprint": result_fingerprint,
        "observed_at": observed_at,
    }
    fingerprint = _digest(subject)
    return {
        **subject,
        "fingerprint": fingerprint,
        "continuity_cookie": f"sw-opportunity-v1:{fingerprint[:32]}",
        "authorizes": False,
        "allocation_authorized": False,
        "execution_authorized": False,
        "claims": [
            "A provider observation was returned for this exact query/resource fingerprint.",
            "The observation belongs to a capability lane inside Sleep Wealth, not to product identity.",
        ],
        "does_not_prove": [
            "profitability",
            "future returns",
            "capital allocation authority",
            "transaction authority",
            "payment authority",
        ],
        "expires_when": [
            "provider capability fingerprint changes",
            "query/resource fingerprint changes",
            "source observation changes",
            "authority boundary changes",
        ],
    }
