import pytest

from backend.external_observers import (
    external_crypto_sources_status,
    get_sideshift_public_catalog,
    normalize_pump_fun_public_evidence,
)


def test_external_crypto_sources_status_is_non_authorizing():
    result = external_crypto_sources_status()

    assert result["status"] == "ok"
    assert result["lane"] == "crypto"
    assert result["mode"] == "observation-only"
    assert result["read_only"] is True
    assert result["authority"] == "none"
    assert result["real_money"] is False
    assert result["live_execution"] is False
    assert set(result["sources"]) == {"pump.fun", "sideshift"}
    assert result["sources"]["pump.fun"]["network_access"] == "none"
    assert result["sources"]["sideshift"]["network_access"] == "GET /api/v2/coins only"


def test_pump_fun_http_helper_normalizes_without_network_or_authority():
    result = normalize_pump_fun_public_evidence(
        {
            "source_url": "https://pump.fun/coin/example",
            "symbol": "EXAMPLE",
            "mint": "ExampleMintAddress",
            "name": "Example Coin",
            "market_cap": 12345,
            "observed_at": "2026-09-13T22:00:00Z",
        }
    )

    observation = result["observation"]
    assert result["status"] == "observed"
    assert result["mode"] == "manual-public-evidence"
    assert result["authority"] == "none"
    assert result["real_money"] is False
    assert result["live_execution"] is False
    assert observation["source"] == "pump-fun-public-evidence"
    assert observation["network_request_performed"] is False
    assert observation["wallet_connection"] is False
    assert observation["trading_enabled"] is False
    assert observation["continuity_cookie"].startswith("sw-pump-observation-v1:")


def test_pump_fun_http_helper_rejects_wallet_or_order_fields():
    with pytest.raises(ValueError, match="reject execution/credential fields"):
        normalize_pump_fun_public_evidence(
            {
                "source_url": "https://pump.fun/coin/example",
                "symbol": "EXAMPLE",
                "wallet_address": "blocked",
            }
        )

    with pytest.raises(ValueError, match="reject execution/credential fields"):
        normalize_pump_fun_public_evidence(
            {
                "source_url": "https://pump.fun/coin/example",
                "symbol": "EXAMPLE",
                "order_id": "blocked",
            }
        )


def test_sideshift_http_helper_is_public_catalog_only():
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
            }
        ]

    result = get_sideshift_public_catalog(fetch_json=fake_fetch)
    catalog = result["catalog"]

    assert len(calls) == 1
    assert calls[0].endswith("/api/v2/coins")
    assert result["status"] == "ok"
    assert result["mode"] == "public-coin-catalog"
    assert result["authority"] == "none"
    assert result["real_money"] is False
    assert result["live_execution"] is False
    assert catalog["endpoint_scope"] == "GET /api/v2/coins only"
    assert catalog["account_secret_used"] is False
    assert catalog["quote_creation"] is False
    assert catalog["shift_creation"] is False
    assert catalog["wallet_connection"] is False
    assert [row["coin"] for row in catalog["coins"]] == ["btc"]
