import pytest

from market.external_sources import (
    PumpFunPublicEvidenceObserver,
    SIDESHIFT_COINS_URL,
    SideShiftPublicCoinCatalogObserver,
    external_crypto_source_capabilities,
)


def test_external_crypto_capability_ceiling_is_observation_only():
    sources = external_crypto_source_capabilities()

    assert set(sources) == {"pump.fun", "sideshift"}
    for source in sources.values():
        assert source["read_only"] is True
        assert source["authority"] == "none"
        assert source["real_money"] is False
        assert source["wallet_connection"] is False
        assert source["trading_enabled"] is False
        assert source["quote_creation"] is False
        assert source["shift_creation"] is False
        assert source["automated_scraping"] is False

    assert sources["pump.fun"]["network_access"] == "none"
    assert sources["sideshift"]["network_access"] == "GET /api/v2/coins only"


def test_pump_fun_observer_normalizes_manual_public_evidence_without_network():
    observer = PumpFunPublicEvidenceObserver()
    evidence = {
        "source_url": "https://pump.fun/coin/example",
        "symbol": "EXAMPLE",
        "mint": "ExampleMintAddress",
        "name": "Example Coin",
        "market_cap": 12345,
        "observed_at": "2026-09-13T22:00:00Z",
    }

    first = observer.observe(evidence)
    second = observer.observe(evidence)

    assert first["source"] == "pump-fun-public-evidence"
    assert first["source_classification"] == "user-supplied-public-evidence"
    assert first["classification"] == "OBSERVED"
    assert first["fingerprint"] == second["fingerprint"]
    assert first["continuity_cookie"].startswith("sw-pump-observation-v1:")
    assert first["read_only"] is True
    assert first["authority"] == "none"
    assert first["real_money"] is False
    assert first["wallet_connection"] is False
    assert first["trading_enabled"] is False
    assert first["automated_scraping"] is False
    assert first["network_request_performed"] is False


def test_pump_fun_observer_rejects_non_pump_source_and_execution_fields():
    observer = PumpFunPublicEvidenceObserver()

    with pytest.raises(ValueError, match="pump.fun source_url"):
        observer.observe({"source_url": "https://example.com/coin", "symbol": "NOPE"})

    with pytest.raises(ValueError, match="reject execution/credential fields"):
        observer.observe(
            {
                "source_url": "https://pump.fun/coin/example",
                "symbol": "EXAMPLE",
                "wallet_address": "not-accepted",
            }
        )

    with pytest.raises(ValueError, match="reject execution/credential fields"):
        observer.observe(
            {
                "source_url": "https://pump.fun/coin/example",
                "symbol": "EXAMPLE",
                "order_id": "not-accepted",
            }
        )


def test_sideshift_observer_fetches_only_public_coin_catalog_without_secret():
    observer = SideShiftPublicCoinCatalogObserver()
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return [
            {
                "coin": "btc",
                "name": "Bitcoin",
                "networks": ["bitcoin"],
                "fixedOnly": False,
                "depositVariableOnly": False,
                "settleVariableOnly": False,
            },
            {
                "coin": "eth",
                "name": "Ethereum",
                "networks": ["ethereum"],
                "fixedOnly": False,
                "depositVariableOnly": ["some-network"],
                "settleVariableOnly": False,
            },
        ]

    result = observer.list_supported_coins(fetch_json=fake_fetch)

    assert calls == [SIDESHIFT_COINS_URL]
    assert result["source"] == "sideshift-public-coin-catalog"
    assert result["source_classification"] == "external-public-catalog"
    assert result["endpoint_scope"] == "GET /api/v2/coins only"
    assert [coin["coin"] for coin in result["coins"]] == ["btc", "eth"]
    assert result["continuity_cookie"].startswith("sw-sideshift-catalog-v1:")
    assert result["read_only"] is True
    assert result["authority"] == "none"
    assert result["real_money"] is False
    assert result["wallet_connection"] is False
    assert result["trading_enabled"] is False
    assert result["quote_creation"] is False
    assert result["shift_creation"] is False
    assert result["account_secret_used"] is False


def test_sideshift_observer_rejects_secret_or_execution_fields_from_payload():
    observer = SideShiftPublicCoinCatalogObserver()

    with pytest.raises(ValueError, match="reject execution/credential fields"):
        observer.list_supported_coins(
            fetch_json=lambda _url: [
                {
                    "coin": "btc",
                    "name": "Bitcoin",
                    "networks": ["bitcoin"],
                    "x-sideshift-secret": "must-never-enter-observer",
                }
            ]
        )

    with pytest.raises(ValueError, match="public coin catalog must return a list"):
        observer.list_supported_coins(fetch_json=lambda _url: {"coin": "btc"})


def test_external_observers_do_not_expose_execution_methods():
    pump = PumpFunPublicEvidenceObserver()
    sideshift = SideShiftPublicCoinCatalogObserver()

    for observer in (pump, sideshift):
        assert not hasattr(observer, "submit_order")
        assert not hasattr(observer, "connect_wallet")
        assert not hasattr(observer, "request_quote")
        assert not hasattr(observer, "create_shift")
        assert not hasattr(observer, "deposit")
        assert not hasattr(observer, "settle")
