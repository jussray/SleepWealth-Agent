"""Lane boundaries for Sleep Wealth's paper-only market simulator."""

from typing import Any

STOCK_LANE = "stock-market"
CRYPTO_LANE = "crypto"
SUPPORTED_LANES = (STOCK_LANE, CRYPTO_LANE)

LANE_FIXTURE_TYPES = {
    STOCK_LANE: "EQUITY",
    CRYPTO_LANE: "CRYPTOCURRENCY",
}


def normalize_lane(value: str | None) -> str:
    lane = str(value or STOCK_LANE).strip().lower()
    if lane not in SUPPORTED_LANES:
        raise ValueError(f"unsupported market lane: {lane}")
    return lane


def get_lane_rules(rules: dict, lane: str) -> dict:
    lane = normalize_lane(lane)
    config = (rules.get("lanes") or {}).get(lane)
    if not isinstance(config, dict) or not config.get("enabled"):
        raise ValueError(f"{lane} lane is disabled")
    if config.get("paper_only") is not True:
        raise ValueError(f"{lane} lane must remain paper-only")
    return config


class LaneBoundFixtureProvider:
    """Attach deterministic lane metadata to the mock quote feed used by CI and Playwright."""

    def __init__(self, provider: Any, lane: str):
        self.provider = provider
        self.lane = normalize_lane(lane)
        self.source_name = getattr(provider, "source_name", "mock-market-observation")
        self.source_classification = getattr(provider, "source_classification", "synthetic-fixture")
        self.max_age_seconds = int(getattr(provider, "max_age_seconds", 5 * 60))

    async def get_market_data(self, symbol: str) -> dict:
        data = dict(await self.provider.get_market_data(symbol))
        data["lane"] = self.lane
        data["instrument_type"] = LANE_FIXTURE_TYPES[self.lane]
        data["crypto_native"] = self.lane == CRYPTO_LANE
        return data
