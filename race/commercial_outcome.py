"""Non-authorizing, fail-closed commercial outcome evidence.

This records supplied evidence identifiers, not verified provider transactions.
"""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation

from race.identity import product_identity_receipt

CONTRACT = "sleepwealth/commercial-outcome@v1"


def _money(value: object, field: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise ValueError(f"{field} must be a decimal amount")
    try:
        amount = Decimal(str(value))
    except InvalidOperation as exc:
        raise ValueError(f"{field} must be a decimal amount") from exc
    if not amount.is_finite() or amount < 0 or amount.as_tuple().exponent < -2:
        raise ValueError(f"{field} must be nonnegative with at most two decimals")
    return amount


def _evidence(value: object, field: str) -> str:
    digest = str(value or "").strip().lower()
    if len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
        raise ValueError(f"{field} must be a SHA-256 evidence digest")
    return digest


def commercial_outcome_receipt(
    *, lane: str, currency: str, gross_revenue: object, costs: object,
    payment_evidence_sha256: str | None = None,
    delivery_evidence_sha256: str | None = None,
    evidence_verified: bool = False,
) -> dict[str, object]:
    """Never self-certify payment or delivery from user-provided identifiers."""
    lane = lane.strip().lower()
    currency = currency.strip().upper()
    if not lane or currency != "USD":
        raise ValueError("nonempty lane and USD currency required")
    gross = _money(gross_revenue, "gross_revenue")
    expense = _money(costs, "costs")
    payment = _evidence(payment_evidence_sha256, "payment_evidence_sha256") if payment_evidence_sha256 else None
    delivery = _evidence(delivery_evidence_sha256, "delivery_evidence_sha256") if delivery_evidence_sha256 else None
    if evidence_verified:
        raise ValueError("self-attested evidence cannot be promoted to VERIFIED")
    net = gross - expense
    subject = {
        "contract": CONTRACT,
        "product_fingerprint": product_identity_receipt()["fingerprint"],
        "lane": lane,
        "currency": currency,
        "gross_revenue": str(gross.quantize(Decimal("0.01"))),
        "costs": str(expense.quantize(Decimal("0.01"))),
        "net_profit": str(net.quantize(Decimal("0.01"))),
        "payment_evidence_sha256": payment,
        "delivery_evidence_sha256": delivery,
        "truth_state": "UNVERIFIED",
    }
    fingerprint = hashlib.sha256(json.dumps(subject, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return {
        **subject, "fingerprint": fingerprint,
        "continuity_cookie": f"sw-commercial-v1:{fingerprint[:32]}",
        "authorizes": False, "allocation_authorized": False,
        "execution_authorized": False, "profit_verified": False,
        "next_gate": "Independently reconcile payment, delivery, refunds and costs before claiming verified profit.",
    }
