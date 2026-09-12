import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any


@dataclass(frozen=True)
class MarketObservation:
    symbol: str
    price: float
    bid: float | None
    ask: float | None
    observed_at: str
    retrieved_at: str
    source: str
    source_classification: str
    instrument_type: str
    lane: str
    crypto_native: bool
    classification: str
    freshness: str
    age_seconds: int
    fingerprint: str
    continuity_cookie: str
    read_only: bool = True
    authority: str = "none"

    def to_dict(self) -> dict:
        return asdict(self)


def _canonical_hash(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _coerce_observed_at(value: Any) -> datetime:
    if isinstance(value, datetime):
        parsed = value
    elif value:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    else:
        parsed = datetime.now(timezone.utc)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


async def observe_market(provider: Any, symbol: str, source: str | None = None) -> MarketObservation:
    """Read one quote and emit non-secret continuity markers without granting execution authority."""
    data = await provider.get_market_data(symbol)
    if not isinstance(data, dict):
        raise ValueError("market provider returned no observation")

    try:
        price = float(data.get("price") or 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("market observation price is invalid") from exc
    if price <= 0:
        raise ValueError("market observation price must be greater than zero")

    def optional_float(value):
        if value in (None, ""):
            return None
        return float(value)

    observed = _coerce_observed_at(data.get("timestamp"))
    retrieved = datetime.now(timezone.utc)
    age_seconds = max(0, int((retrieved - observed).total_seconds()))
    max_age_seconds = int(getattr(provider, "max_age_seconds", 5 * 60))
    if age_seconds > max_age_seconds:
        raise ValueError(
            f"market observation for {str(symbol).upper()} is stale: {age_seconds}s > {max_age_seconds}s"
        )

    source_name = source or data.get("source_name") or getattr(provider, "source_name", "read-only-market-provider")
    source_classification = (
        data.get("source_classification")
        or getattr(provider, "source_classification", "external-or-injected")
    )
    normalized_symbol = str(data.get("symbol") or symbol).upper()
    instrument_type = str(data.get("instrument_type") or "UNKNOWN").strip().upper()
    lane = str(data.get("lane") or "unclassified").strip().lower()
    crypto_native = bool(data.get("crypto_native", lane == "crypto"))
    observed_at = observed.isoformat()
    retrieved_at = retrieved.isoformat()
    fingerprint = _canonical_hash(
        {
            "symbol": normalized_symbol,
            "price": round(price, 8),
            "bid": optional_float(data.get("bid")),
            "ask": optional_float(data.get("ask")),
            "observed_at": observed_at,
            "source": source_name,
            "source_classification": source_classification,
            "instrument_type": instrument_type,
            "lane": lane,
            "crypto_native": crypto_native,
            "classification": "OBSERVED",
        }
    )

    return MarketObservation(
        symbol=normalized_symbol,
        price=price,
        bid=optional_float(data.get("bid")),
        ask=optional_float(data.get("ask")),
        observed_at=observed_at,
        retrieved_at=retrieved_at,
        source=source_name,
        source_classification=source_classification,
        instrument_type=instrument_type,
        lane=lane,
        crypto_native=crypto_native,
        classification="OBSERVED",
        freshness="fresh",
        age_seconds=age_seconds,
        fingerprint=fingerprint,
        continuity_cookie=f"sw-market-v1:{fingerprint[:32]}",
    )
