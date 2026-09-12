import asyncio
import json
from datetime import datetime, timezone
from typing import Callable
from urllib.parse import quote
from urllib.request import Request, urlopen


STOCK_LANE_INSTRUMENT_TYPES = {"EQUITY", "ETF", "MUTUALFUND"}


class YahooPublicChartProvider:
    """Read-only stock/fund observations. Crypto-native instruments are rejected."""

    source_name = "yahoo-public-chart"
    source_classification = "external-public-delayed"
    max_age_seconds = 5 * 24 * 60 * 60

    def __init__(self, fetch_json: Callable[[str], dict] | None = None, timeout: float = 10.0):
        self._fetch_json = fetch_json or self._download_json
        self.timeout = timeout

    def _download_json(self, url: str) -> dict:
        request = Request(
            url,
            headers={
                "User-Agent": "SleepWealth/0.5 read-only-stock-observer",
                "Accept": "application/json",
            },
        )
        with urlopen(request, timeout=self.timeout) as response:
            return json.load(response)

    def _read_symbol(self, symbol: str) -> dict:
        normalized = str(symbol).strip().upper()
        if not normalized or len(normalized) > 14:
            raise ValueError("market symbol is invalid")

        encoded = quote(normalized, safe="-^.")
        url = (
            f"https://query1.finance.yahoo.com/v8/finance/chart/{encoded}"
            "?range=5d&interval=1d&includePrePost=false&events=div%2Csplits"
        )
        payload = self._fetch_json(url)
        chart = payload.get("chart") if isinstance(payload, dict) else None
        results = chart.get("result") if isinstance(chart, dict) else None
        error = chart.get("error") if isinstance(chart, dict) else None
        if error or not results:
            raise ValueError(f"external market source returned no observation for {normalized}")

        result = results[0]
        meta = result.get("meta") or {}
        instrument_type = str(meta.get("instrumentType") or "").strip().upper()
        if instrument_type not in STOCK_LANE_INSTRUMENT_TYPES:
            observed = instrument_type or "UNKNOWN"
            raise ValueError(
                f"{normalized} is not eligible for the stock lane: instrument type {observed}"
            )

        timestamps = result.get("timestamp") or []
        indicators = result.get("indicators") or {}
        quotes = indicators.get("quote") or []
        closes = quotes[0].get("close") if quotes and isinstance(quotes[0], dict) else []
        closes = closes or []

        pair = None
        for timestamp, close in reversed(list(zip(timestamps, closes))):
            try:
                price = float(close)
            except (TypeError, ValueError):
                continue
            if price > 0:
                pair = (int(timestamp), price)
                break
        if pair is None:
            raise ValueError(f"external market source returned no usable close for {normalized}")

        timestamp, price = pair
        return {
            "symbol": str(meta.get("symbol") or normalized).upper(),
            "price": price,
            "bid": None,
            "ask": None,
            "currency": meta.get("currency") or "USD",
            "timestamp": datetime.fromtimestamp(timestamp, tz=timezone.utc),
            "source_name": self.source_name,
            "source_classification": self.source_classification,
            "instrument_type": instrument_type,
            "lane": "stock-market",
            "crypto_native": False,
        }

    async def get_market_data(self, symbol: str) -> dict:
        return await asyncio.to_thread(self._read_symbol, symbol)
