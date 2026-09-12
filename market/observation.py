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
    source: str
    classification: str = "OBSERVED"
    read_only: bool = True

    def to_dict(self) -> dict:
        return asdict(self)


async def observe_market(provider: Any, symbol: str, source: str = "broker-market-data") -> MarketObservation:
    """Read a quote without granting the provider any execution authority."""
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

    timestamp = data.get("timestamp")
    if isinstance(timestamp, datetime):
        observed_at = timestamp.astimezone(timezone.utc).isoformat()
    elif timestamp:
        observed_at = str(timestamp)
    else:
        observed_at = datetime.now(timezone.utc).isoformat()

    return MarketObservation(
        symbol=str(data.get("symbol") or symbol).upper(),
        price=price,
        bid=optional_float(data.get("bid")),
        ask=optional_float(data.get("ask")),
        observed_at=observed_at,
        source=source,
    )
