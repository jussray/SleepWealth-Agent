import pytest

from backend import server as server_module
from market.universe import NASDAQ_LISTED_URL, OTHER_LISTED_URL, NasdaqTraderUniverseProvider


NASDAQ_SAMPLE = """Symbol|Security Name|Market Category|Test Issue|Financial Status|Round Lot Size|ETF|NextShares
AAPL|Apple Inc. - Common Stock|Q|N|N|100|N|N
QQQ|Invesco QQQ Trust|Q|N|N|100|Y|N
ZTEST|Nasdaq Test Issue|Q|Y|N|100|N|N
File Creation Time: 0912202618:00|||||||
"""

OTHER_SAMPLE = """ACT Symbol|Security Name|Exchange|CQS Symbol|ETF|Round Lot Size|Test Issue|NASDAQ Symbol
IBM|International Business Machines Corporation|N|IBM|N|100|N|IBM
VTI|Vanguard Total Stock Market ETF|P|VTI|Y|100|N|VTI
ATEST|Other Test Issue|A|ATEST|N|100|Y|ATEST
File Creation Time: 0912202618:00|||||||
"""


def fake_fetch(url: str) -> str:
    if url == NASDAQ_LISTED_URL:
        return NASDAQ_SAMPLE
    if url == OTHER_LISTED_URL:
        return OTHER_SAMPLE
    raise AssertionError(url)


@pytest.mark.asyncio
async def test_directory_combines_us_exchange_listings_and_excludes_test_issues():
    provider = NasdaqTraderUniverseProvider(fetch_text=fake_fetch)
    rows = await provider.list_securities()

    assert [row.symbol for row in rows] == ["AAPL", "IBM", "QQQ", "VTI"]
    assert all(row.source == "nasdaq-trader-symbol-directory" for row in rows)
    assert all(row.to_dict()["lane"] == "stock-market" for row in rows)
    assert all(row.to_dict()["crypto_native"] is False for row in rows)


@pytest.mark.asyncio
async def test_directory_searches_symbol_and_security_name():
    provider = NasdaqTraderUniverseProvider(fetch_text=fake_fetch)

    by_symbol = await provider.search("IBM")
    assert [row["symbol"] for row in by_symbol] == ["IBM"]

    by_name = await provider.search("Vanguard")
    assert [row["symbol"] for row in by_name] == ["VTI"]
    assert by_name[0]["asset_type"] == "fund"


@pytest.mark.asyncio
async def test_directory_resolve_is_exact_and_read_only():
    provider = NasdaqTraderUniverseProvider(fetch_text=fake_fetch)

    row = await provider.resolve("aapl")
    assert row is not None
    assert row["symbol"] == "AAPL"
    assert row["exchange"] == "NASDAQ"
    assert row["read_only"] is True
    assert row["authority"] == "none"

    assert await provider.resolve("BTC-USD") is None

@pytest.mark.asyncio
async def test_server_stock_search_reuses_one_directory_instance(monkeypatch):
    calls = []

    def counting_fetch(url: str) -> str:
        calls.append(url)
        return fake_fetch(url)

    provider = NasdaqTraderUniverseProvider(fetch_text=counting_fetch)
    monkeypatch.setattr(server_module, "_STOCK_UNIVERSE_PROVIDER", provider)

    first = await server_module.search_stock_universe("AAPL")
    second = await server_module.search_stock_universe("Vanguard")

    assert [row["symbol"] for row in first["results"]] == ["AAPL"]
    assert [row["symbol"] for row in second["results"]] == ["VTI"]
    assert calls == [NASDAQ_LISTED_URL, OTHER_LISTED_URL]
