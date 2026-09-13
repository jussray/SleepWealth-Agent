"""Pump live-observation to practice-sandbox bridge.

This module intentionally performs no Pump website scraping, wallet access,
transaction signing, or real-money execution. It accepts a permitted read-only
snapshot, canonicalizes it through the existing market observation primitive,
binds the Pump mint to that observation, and mirrors the observed price into the
crypto sandbox for practice only.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from hashlib import sha256
import json
from math import isfinite
from typing import Any

from broker.crypto_sandbox import CryptoSandboxBroker
from execution.modes import LIVE_MODE, PRACTICE_MODE, get_execution_mode
from market.observation import MarketObservation, observe_market


_ALLOWED_SOURCE_CLASSIFICATIONS = frozenset({"authorized-api", "public-chain-read-only", "user-supplied"})


def _digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class PumpLiveObservation:
    """Pump-specific identity binding over the canonical read-only market observation."""

    mint: str
    market: MarketObservation
    fingerprint: str

    @property
    def symbol(self) -> str:
        return self.market.symbol

    @property
    def price(self) -> float:
        return self.market.price

    @property
    def lane(self) -> str | None:
        return self.market.lane

    @property
    def crypto_native(self) -> bool:
        return self.market.crypto_native

    @property
    def instrument_type(self) -> str | None:
        return self.market.instrument_type

    @property
    def read_only(self) -> bool:
        return self.market.read_only

    @property
    def authority(self) -> str:
        return self.market.authority

    @property
    def source(self) -> str:
        return self.market.source

    @property
    def source_classification(self) -> str:
        return self.market.source_classification

    @property
    def market_fingerprint(self) -> str:
        return self.market.fingerprint


@dataclass(frozen=True, slots=True)
class PumpShadowReceipt:
    symbol: str
    mint: str
    live_mode: str
    practice_mode: str
    observation_fingerprint: str
    market_fingerprint: str
    mirrored_price: float
    mirror_fingerprint: str
    source: str
    source_classification: str
    real_money: bool = False
    wallet_access: bool = False
    transaction_signing: bool = False
    live_execution: bool = False
    authority: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PumpSnapshotProvider:
    """One-shot provider for a permitted externally supplied Pump snapshot."""

    max_age_seconds = 60

    def __init__(self, snapshot: dict[str, Any]):
        self.snapshot = self._validate_snapshot(snapshot)
        self.source_name = self.snapshot["source"]
        self.source_classification = self.snapshot["source_classification"]

    @staticmethod
    def _validate_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(snapshot, dict):
            raise ValueError("pump snapshot must be a mapping")
        required = ("mint", "symbol", "price", "timestamp", "source", "source_classification")
        missing = [
            key
            for key in required
            if key not in snapshot or snapshot[key] is None or snapshot[key] == ""
        ]
        if missing:
            raise ValueError(f"pump snapshot missing: {', '.join(missing)}")
        source_classification = str(snapshot["source_classification"]).strip().lower()
        if source_classification not in _ALLOWED_SOURCE_CLASSIFICATIONS:
            raise PermissionError(
                "pump snapshot source must be an authorized API, public-chain read-only source, "
                "or user-supplied observation; automated Pump website scraping is not supported"
            )
        price = float(snapshot["price"])
        if not isfinite(price) or price <= 0:
            raise ValueError("pump snapshot price must be finite and greater than zero")
        mint = str(snapshot["mint"]).strip()
        symbol = str(snapshot["symbol"]).strip().upper()
        source = str(snapshot["source"]).strip()
        if not mint or not symbol or not source:
            raise ValueError("pump snapshot identity fields must not be empty")
        return {
            **snapshot,
            "mint": mint,
            "symbol": symbol,
            "price": price,
            "source": source,
            "source_classification": source_classification,
        }

    async def get_market_data(self, symbol: str) -> dict[str, Any]:
        requested = str(symbol).strip().upper()
        if requested != self.snapshot["symbol"]:
            raise ValueError(f"snapshot is for {self.snapshot['symbol']}, not requested symbol {requested}")
        return {
            "symbol": self.snapshot["symbol"],
            "price": self.snapshot["price"],
            "bid": self.snapshot.get("bid"),
            "ask": self.snapshot.get("ask"),
            "timestamp": self.snapshot["timestamp"],
            "source_name": self.source_name,
            "source_classification": self.source_classification,
            "instrument_type": "PUMP_TOKEN",
            "lane": "crypto",
            "crypto_native": True,
            "mint": self.snapshot["mint"],
        }


class PumpShadowBridge:
    """Mirror a live read-only Pump observation into the crypto practice sandbox."""

    @staticmethod
    async def observe(snapshot: dict[str, Any]) -> PumpLiveObservation:
        live_mode = get_execution_mode(LIVE_MODE)
        if live_mode.real_execution_enabled or live_mode.simulated_execution_enabled:
            raise RuntimeError("live mode authority widened unexpectedly")
        provider = PumpSnapshotProvider(snapshot)
        market = await observe_market(provider, provider.snapshot["symbol"])
        fingerprint = _digest(
            {
                "schema": "pump-live-observation-v1",
                "mint": provider.snapshot["mint"],
                "market_fingerprint": market.fingerprint,
                "read_only": True,
                "authority": "none",
            }
        )
        return PumpLiveObservation(
            mint=provider.snapshot["mint"],
            market=market,
            fingerprint=fingerprint,
        )

    @staticmethod
    def mirror_to_practice(
        observation: PumpLiveObservation,
        *,
        sandbox: CryptoSandboxBroker,
    ) -> PumpShadowReceipt:
        practice_mode = get_execution_mode(PRACTICE_MODE)
        if not practice_mode.simulated_execution_enabled or practice_mode.real_execution_enabled:
            raise RuntimeError("practice mode authority boundary is invalid")
        if not observation.read_only or observation.authority != "none":
            raise PermissionError("only non-authorizing read-only observations may be mirrored")
        if observation.lane != "crypto" or not observation.crypto_native:
            raise ValueError("Pump shadow bridge accepts crypto-native observations only")
        if not observation.mint:
            raise ValueError("bound mint must not be empty")
        if not sandbox.is_paper_only():
            raise PermissionError("Pump shadow bridge requires a paper-only sandbox")

        sandbox.set_market_price(observation.symbol, observation.price)
        payload = {
            "symbol": observation.symbol,
            "mint": observation.mint,
            "observation_fingerprint": observation.fingerprint,
            "market_fingerprint": observation.market_fingerprint,
            "mirrored_price": observation.price,
            "sandbox_wallet": sandbox.wallet_id,
            "real_money": False,
        }
        mirror_fingerprint = _digest(payload)
        return PumpShadowReceipt(
            symbol=observation.symbol,
            mint=observation.mint,
            live_mode=LIVE_MODE,
            practice_mode=PRACTICE_MODE,
            observation_fingerprint=observation.fingerprint,
            market_fingerprint=observation.market_fingerprint,
            mirrored_price=observation.price,
            mirror_fingerprint=mirror_fingerprint,
            source=observation.source,
            source_classification=observation.source_classification,
        )
