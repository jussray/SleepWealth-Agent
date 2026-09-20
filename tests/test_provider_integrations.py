import base64
import hashlib
import hmac
import json

import httpx
import pytest

from integrations.cash_app_pay import CashAppPayClient, CashAppPayConfig, CashAppPayCredentials
from integrations.solana_rpc import SolanaRpcClient, SolanaRpcConfig, transaction_fingerprint


@pytest.mark.asyncio
async def test_solana_broadcast_uses_signed_transaction_without_private_key():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        seen.update(payload)
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "sig-123"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = SolanaRpcClient(
            SolanaRpcConfig("https://rpc.example.test", "mainnet-beta"),
            client=http_client,
        )
        transaction = base64.b64encode(b"already-signed-transaction").decode()
        result = await client.broadcast_signed_transaction(transaction)

    assert seen["method"] == "sendTransaction"
    assert seen["params"][0] == transaction
    assert seen["params"][1]["skipPreflight"] is False
    assert result["transaction_fingerprint"] == transaction_fingerprint(transaction)
    assert result["signature"] == "sig-123"
    assert "private" not in json.dumps(seen).lower()


@pytest.mark.asyncio
async def test_solana_observation_is_non_authorizing():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content)
        assert payload["method"] == "getBalance"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": {"value": 123}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = SolanaRpcClient(
            SolanaRpcConfig("https://rpc.example.test", "devnet"),
            client=http_client,
        )
        result = await client.get_balance("PublicKey111")

    assert result["lamports"] == 123
    assert result["execution_authorized"] is False
    assert len(result["account_fingerprint"]) == 64


@pytest.mark.asyncio
async def test_cash_app_payment_request_is_hmac_signed_over_exact_body():
    secret = "s" * 32
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["method"] = request.method
        captured["path"] = request.url.raw_path.decode()
        captured["headers"] = dict(request.headers)
        captured["body"] = request.content
        return httpx.Response(201, json={"payment": {"id": "PWC-test", "status": "AUTHORIZED"}})

    transport = httpx.MockTransport(handler)
    credentials = CashAppPayCredentials(
        client_id="client-1",
        key_id="key-1",
        secret=secret,
        region="PDX",
    )
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = CashAppPayClient(
            CashAppPayConfig("production"),
            credentials=credentials,
            client=http_client,
        )
        result = await client.create_payment(
            merchant_id="merchant-1",
            grant_id="grant-1",
            amount_cents=1250,
            reference_id="order-1",
            idempotency_key="idem-1",
        )

    assert captured["method"] == "POST"
    assert captured["path"] == "/network/v1/payments"
    headers = captured["headers"]
    authorization = "Client client-1 key-1"
    assert headers["authorization"] == authorization
    assert headers["x-region"] == "PDX"

    body_digest = hashlib.sha256(captured["body"]).hexdigest()
    signed_headers = (
        "accept:application/json\n"
        f"authorization:{authorization}\n"
        "content-type:application/json\n"
        "host:api.cash.app"
    )
    raw = f"POST\n/network/v1/payments\n{signed_headers}\n{body_digest}"
    expected = hmac.new(secret.encode(), raw.encode(), hashlib.sha256).hexdigest()
    assert headers["x-signature"] == f"V1 {expected}"
    assert result["payment_created"] is True
    assert result["payment"]["id"] == "PWC-test"
    assert "secret" not in json.dumps(result).lower()


@pytest.mark.asyncio
async def test_cash_app_customer_request_uses_client_id_and_requires_customer_approval():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["Authorization"] == "Client client-public"
        body = json.loads(request.content)
        action = body["request"]["actions"][0]
        assert action["type"] == "ONE_TIME_PAYMENT"
        assert action["amount"] == 500
        return httpx.Response(
            201,
            json={"request": {"id": "GRR-test", "status": "PENDING", "actions": [action]}},
        )

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        client = CashAppPayClient(CashAppPayConfig("sandbox"), client=http_client)
        result = await client.create_customer_request(
            client_id="client-public",
            merchant_id="merchant-1",
            amount_cents=500,
            reference_id="cart-1",
            redirect_url="https://example.test/return",
            idempotency_key="req-1",
        )

    assert result["customer_request"]["status"] == "PENDING"
    assert result["payment_created"] is False
