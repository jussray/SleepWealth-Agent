import json

import pytest

from broker.alpaca_readonly import AlpacaReadOnlyObserver, AlpacaReadOnlyObserverError
from broker.provider_identity import provider_account_fingerprint

TOKEN = "test-token-that-must-never-appear-in-receipts"
ACCOUNT_ID = "e6fe16f3-64a4-4921-8928-cadf02f92f98"
ACCOUNT_NUMBER = "010203ABCD"


def _active_account():
    return {
        "id": ACCOUNT_ID,
        "account_number": ACCOUNT_NUMBER,
        "status": "ACTIVE",
        "crypto_status": "ACTIVE",
        "account_blocked": False,
        "trading_blocked": False,
        "trade_suspended_by_user": False,
    }


@pytest.mark.asyncio
async def test_alpaca_observer_returns_safe_live_account_capabilities():
    captured = {}

    async def request_json(url, headers, timeout):
        captured.update({"url": url, "headers": headers, "timeout": timeout})
        return _active_account()

    receipt = await AlpacaReadOnlyObserver(
        oauth_token=TOKEN,
        request_json=request_json,
    ).observe()

    assert captured["url"] == "https://api.alpaca.markets/v2/account"
    assert captured["headers"]["Authorization"] == f"Bearer {TOKEN}"
    assert receipt["provider"] == "alpaca"
    assert receipt["environment"] == "live"
    assert receipt["asset_permissions"] == ["stock-market", "crypto"]
    assert receipt["execution_authorized"] is False
    assert receipt["order_submit_capability"] is False
    assert receipt["account_fingerprint"] == provider_account_fingerprint(
        "alpaca",
        {"account_id": ACCOUNT_ID, "account_number": ACCOUNT_NUMBER},
    )
    assert len(receipt["observation_fingerprint"]) == 64

    serialized = json.dumps(receipt)
    assert TOKEN not in serialized
    assert ACCOUNT_NUMBER not in serialized
    assert ACCOUNT_ID not in serialized


@pytest.mark.asyncio
async def test_blocked_account_exposes_no_trading_permissions():
    account = _active_account()
    account["trading_blocked"] = True

    async def request_json(_url, _headers, _timeout):
        return account

    receipt = await AlpacaReadOnlyObserver(
        oauth_token=TOKEN,
        request_json=request_json,
    ).observe()

    assert receipt["asset_permissions"] == []
    assert receipt["trading_blocked"] is True
    assert receipt["execution_authorized"] is False


@pytest.mark.asyncio
async def test_observer_refuses_paper_or_noncanonical_endpoint():
    observer = AlpacaReadOnlyObserver(
        oauth_token=TOKEN,
        base_url="https://paper-api.alpaca.markets",
        request_json=lambda *_args: _active_account(),
    )
    with pytest.raises(AlpacaReadOnlyObserverError, match="canonical live"):
        await observer.observe()


@pytest.mark.asyncio
async def test_observer_requires_stable_provider_account_identity():
    async def request_json(_url, _headers, _timeout):
        return {
            "status": "ACTIVE",
            "crypto_status": "ACTIVE",
            "trading_blocked": False,
        }

    with pytest.raises(AlpacaReadOnlyObserverError, match="stable account identity"):
        await AlpacaReadOnlyObserver(
            oauth_token=TOKEN,
            request_json=request_json,
        ).observe()


@pytest.mark.asyncio
async def test_observer_has_no_order_submission_surface():
    observer = AlpacaReadOnlyObserver(
        oauth_token=TOKEN,
        request_json=lambda *_args: _active_account(),
    )
    assert not hasattr(observer, "submit_order")
    assert not hasattr(observer, "cancel_order")
    assert not hasattr(observer, "transfer")
    assert not hasattr(observer, "fund")
