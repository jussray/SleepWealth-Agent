"""Bind Pump public evidence to an exact practice-sandbox price.

This module performs no Pump network access, wallet access, signing, transfer,
or real-money execution. It consumes the existing manual/public evidence
observer and mirrors one bound price into the paper-only crypto sandbox.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from typing import Any

from broker.crypto_sandbox import CryptoSandboxBroker
from execution.modes import LIVE_MODE, PRACTICE_MODE, get_execution_mode
from market.external_sources import PumpFunPublicEvidenceObserver


def _digest(payload: dict[str, Any]) -> str:
    return sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class PumpShadowObservation:
    symbol: str
    mint: str
    price: float
    public_evidence_fingerprint: str
    fingerprint: str
    source: str
    source_classification: str
    observed_at: str
    read_only: bool = True
    authority: str = "none"
    real_money: bool = False
    wallet_connection: bool = False
    transaction_signing: bool = False
    automated_scraping: bool = False


@dataclass(frozen=True, slots=True)
class PumpShadowReceipt:
    observation_fingerprint: str
    public_evidence_fingerprint: str
    symbol: str
    mint: str
    mirrored_price: float
    sandbox_wallet: str
    mirror_fingerprint: str
    live_mode: str = LIVE_MODE
    practice_mode: str = PRACTICE_MODE
    real_money: bool = False
    wallet_connection: bool = False
    transaction_signing: bool = False
    live_execution: bool = False
    authority: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PumpFunPracticeShadowBridge:
    """Create a non-authorizing Pump observation and mirror it into practice."""

    def __init__(self, observer: PumpFunPublicEvidenceObserver | None = None):
        self.observer = observer or PumpFunPublicEvidenceObserver()

    def observe(self, evidence: dict[str, Any]) -> PumpShadowObservation:
        live_mode = get_execution_mode(LIVE_MODE)
        if live_mode.real_execution_enabled or live_mode.simulated_execution_enabled:
            raise RuntimeError("live mode authority widened unexpectedly")

        normalized = self.observer.observe(evidence)
        symbol = str(normalized.get("symbol", "")).strip().upper()
        mint = str(normalized.get("mint", "")).strip()
        if not symbol or not mint:
            raise ValueError("Pump shadow observation requires both symbol and mint")

        if "price" not in evidence or evidence["price"] is None or evidence["price"] == "":
            raise ValueError("Pump shadow observation requires price")
        price = float(evidence["price"])
        if not isfinite(price) or price <= 0:
            raise ValueError("Pump shadow price must be finite and greater than zero")

        payload = {
            "schema": "pump-practice-shadow-v1",
            "public_evidence_fingerprint": normalized["fingerprint"],
            "symbol": symbol,
            "mint": mint,
            "price": price,
            "observed_at": normalized.get("observed_at", ""),
            "read_only": True,
            "authority": "none",
        }
        return PumpShadowObservation(
            symbol=symbol,
            mint=mint,
            price=price,
            public_evidence_fingerprint=normalized["fingerprint"],
            fingerprint=_digest(payload),
            source=normalized["source"],
            source_classification=normalized["source_classification"],
            observed_at=str(normalized.get("observed_at", "")),
        )

    @staticmethod
    def mirror_to_practice(
        observation: PumpShadowObservation,
        sandbox: CryptoSandboxBroker,
    ) -> PumpShadowReceipt:
        practice_mode = get_execution_mode(PRACTICE_MODE)
        if not practice_mode.simulated_execution_enabled or practice_mode.real_execution_enabled:
            raise RuntimeError("practice mode authority boundary is invalid")
        if not observation.read_only or observation.authority != "none" or observation.real_money:
            raise PermissionError("only non-authorizing read-only observations may be mirrored")
        if not sandbox.is_paper_only():
            raise PermissionError("Pump shadow bridge requires a paper-only sandbox")

        sandbox.set_market_price(observation.symbol, observation.price)
        payload = {
            "observation_fingerprint": observation.fingerprint,
            "public_evidence_fingerprint": observation.public_evidence_fingerprint,
            "symbol": observation.symbol,
            "mint": observation.mint,
            "mirrored_price": observation.price,
            "sandbox_wallet": sandbox.wallet_id,
            "real_money": False,
        }
        return PumpShadowReceipt(
            observation_fingerprint=observation.fingerprint,
            public_evidence_fingerprint=observation.public_evidence_fingerprint,
            symbol=observation.symbol,
            mint=observation.mint,
            mirrored_price=observation.price,
            sandbox_wallet=sandbox.wallet_id,
            mirror_fingerprint=_digest(payload),
        )
