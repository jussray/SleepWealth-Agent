from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable

PRODUCT_CONTRACT = "sleepwealth/autonomous-wealth-race@v2"
RACE_CONTINUITY_CONTRACT = "sleepwealth/race-continuity@v2"

_PRODUCT_IDENTITY = {
    "name": "Sleep Wealth",
    "kind": "autonomous-strategy-wealth-race",
    "purpose": (
        "Competing strategic engines discover, test, learn from, and allocate toward "
        "money-making opportunity lanes according to verified outcomes."
    ),
    "competitors": ["MuskEngine", "GatesEngine"],
    "opportunity_model": (
        "Markets, products, services, software, partnerships, and future proven "
        "capabilities are lanes inside the race, not the product identity."
    ),
    "execution_separation": (
        "Paper/mock is a current execution and safety boundary. It is not the product "
        "definition and must never replace the race identity."
    ),
    "authority_separation": (
        "Identity fingerprints and continuity cookies are non-secret state markers. "
        "They never grant financial, signing, transfer, trading, or payment authority."
    ),
}

_STRATEGY_FIELDS = (
    "risk_threshold",
    "max_drawdown_pct",
    "conviction_size",
    "cut_line",
    "position_size",
    "min_conviction",
    "take_profit",
    "stop",
)


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def product_identity_receipt() -> dict[str, object]:
    identity = dict(_PRODUCT_IDENTITY)
    fingerprint = _fingerprint(
        {"contract": PRODUCT_CONTRACT, "identity": identity}
    )
    return {
        "contract": PRODUCT_CONTRACT,
        "identity": identity,
        "fingerprint": fingerprint,
        "continuity_cookie": f"sw-product-v2:{fingerprint[:32]}",
        "authorizes": False,
    }


def engine_strategy_receipt(engine: object) -> dict[str, object]:
    product = product_identity_receipt()
    strategy = {
        field: getattr(engine, field)
        for field in _STRATEGY_FIELDS
        if hasattr(engine, field)
    }
    subject = {
        "product_fingerprint": product["fingerprint"],
        "engine": getattr(engine, "name", type(engine).__name__),
        "class": type(engine).__name__,
        "strategy": strategy,
    }
    fingerprint = _fingerprint(subject)
    return {
        **subject,
        "fingerprint": fingerprint,
        "continuity_cookie": f"sw-engine-v2:{fingerprint[:32]}",
        "authorizes": False,
    }


def race_continuity_receipt(engines: Iterable[object]) -> dict[str, object]:
    product = product_identity_receipt()
    engine_receipts = [engine_strategy_receipt(engine) for engine in engines]
    subject = {
        "contract": RACE_CONTINUITY_CONTRACT,
        "product_fingerprint": product["fingerprint"],
        "engine_fingerprints": [
            receipt["fingerprint"] for receipt in engine_receipts
        ],
    }
    fingerprint = _fingerprint(subject)
    return {
        "contract": RACE_CONTINUITY_CONTRACT,
        "product": product,
        "engines": engine_receipts,
        "fingerprint": fingerprint,
        "continuity_cookie": f"sw-race-v2:{fingerprint[:32]}",
        "authorizes": False,
    }
