import asyncio
import csv
import io
import time
from dataclasses import dataclass
from typing import Callable
from urllib.request import Request, urlopen


NASDAQ_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt"
OTHER_LISTED_URL = "https://www.nasdaqtrader.com/dynamic/SymDir/otherlisted.txt"


@dataclass(frozen=True)
class ListedSecurity:
    symbol: str
    name: str
    exchange: str
    asset_type: str
    source: str

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "exchange": self.exchange,
            "asset_type": self.asset_type,
            "source": self.source,
            "lane": "stock-market",
            "crypto_native": False,
            "read_only": True,
            "authority": "none",
        }


class NasdaqTraderUniverseProvider:
    """Read-only U.S. listed-security directory. No quote or execution methods."""

    source_name = "nasdaq-trader-symbol-directory"
    source_classification = "external-public-directory"

    def __init__(
        self,
        fetch_text: Callable[[str], str] | None = None,
        timeout: float = 10.0,
        cache_ttl_seconds: int = 15 * 60,
    ):
        self._fetch_text = fetch_text or self._download_text
        self.timeout = timeout
        self.cache_ttl_seconds = cache_ttl_seconds
        self._cache: tuple[float, list[ListedSecurity]] | None = None

    def _download_text(self, url: str) -> str:
        request = Request(
            url,
            headers={
                "User-Agent": "SleepWealth/0.5 stock-market-directory",
                "Accept": "text/plain",
            },
        )
        with urlopen(request, timeout=self.timeout) as response:
            return response.read().decode("utf-8", errors="replace")

    @staticmethod
    def _rows(text: str) -> list[dict[str, str]]:
        lines = [line for line in text.splitlines() if line and not line.startswith("File Creation Time")]
        if not lines:
            return []
        return [dict(row) for row in csv.DictReader(io.StringIO("\n".join(lines)), delimiter="|")]

    @staticmethod
    def _exchange_name(code: str, fallback: str) -> str:
        return {
            "N": "NYSE",
            "A": "NYSE American",
            "P": "NYSE Arca",
            "Z": "Cboe BZX",
            "V": "IEX",
        }.get(code, fallback)

    def _load_sync(self) -> list[ListedSecurity]:
        now = time.monotonic()
        if self._cache and (now - self._cache[0]) < self.cache_ttl_seconds:
            return self._cache[1]

        securities: dict[str, ListedSecurity] = {}

        for row in self._rows(self._fetch_text(NASDAQ_LISTED_URL)):
            symbol = (row.get("Symbol") or "").strip().upper()
            if not symbol or (row.get("Test Issue") or "N").strip().upper() == "Y":
                continue
            securities[symbol] = ListedSecurity(
                symbol=symbol,
                name=(row.get("Security Name") or symbol).strip(),
                exchange="NASDAQ",
                asset_type="fund" if (row.get("ETF") or "N").strip().upper() == "Y" else "equity",
                source=self.source_name,
            )

        for row in self._rows(self._fetch_text(OTHER_LISTED_URL)):
            symbol = (row.get("NASDAQ Symbol") or row.get("ACT Symbol") or "").strip().upper()
            if not symbol or (row.get("Test Issue") or "N").strip().upper() == "Y":
                continue
            exchange_code = (row.get("Exchange") or "").strip().upper()
            securities[symbol] = ListedSecurity(
                symbol=symbol,
                name=(row.get("Security Name") or symbol).strip(),
                exchange=self._exchange_name(exchange_code, exchange_code or "OTHER"),
                asset_type="fund" if (row.get("ETF") or "N").strip().upper() == "Y" else "equity",
                source=self.source_name,
            )

        result = sorted(securities.values(), key=lambda item: item.symbol)
        if not result:
            raise ValueError("U.S. stock-market directory returned no securities")
        self._cache = (now, result)
        return result

    async def list_securities(self) -> list[ListedSecurity]:
        return await asyncio.to_thread(self._load_sync)

    async def search(self, query: str = "", limit: int = 25) -> list[dict]:
        query = str(query).strip().upper()
        limit = max(1, min(int(limit), 100))
        securities = await self.list_securities()
        if query:
            securities = [
                item
                for item in securities
                if query in item.symbol or query in item.name.upper()
            ]
        return [item.to_dict() for item in securities[:limit]]

    async def resolve(self, symbol: str) -> dict | None:
        normalized = str(symbol).strip().upper()
        for item in await self.list_securities():
            if item.symbol == normalized:
                return item.to_dict()
        return None
