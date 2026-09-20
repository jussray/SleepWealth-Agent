import base64
import json

import httpx
import pytest

from integrations.cash_app_pay import CashAppPayClient, CashAppPayConfig, CashAppPayCredentials
from integrations.solana_rpc import SolanaRpcClient, SolanaRpcConfig, transaction_fingerprint
from mcp_gateway.action_ledger import ProductActionLedger
from mcp_gateway.authority import issue_product_action_authority
from mcp_gateway.continuity import issue_continuity_cookie
from mcp_gateway.dispatcher import ProviderDispatcher
from mcp_gateway.server import build_mcp_server

COOKIE_KEY = "c" * 32
AUTHORITY_KEY = "a" * 32
LEDGER_KEY = "l" * 32
CALLER_FP = "9" * 64
HUMAN_FP = "8" * 64
ADULT_FP = "7" * 64
SESSION_FP = "6" * 64
SUBJECT_FP = "5" * 64


def _authority(*, provider, environment, account_fp, action, resource_fp, idem, amount=None):
    return issue_product_action_authority(
        issuer_id="authority-issuer",
        issuer_key=AUTHORITY_KEY,
        subject_fingerprint=SUBJECT_FP,
        provider=provider,
        environment=environment,
        account_fingerprint=account_fp,
        action=action,
        resource_fingerprint=resource_fp,
        human_approval_fingerprint=HUMAN_FP,
        eligible_adult_receipt_fingerprint=ADULT_FP,
        provider_session_fingerprint=SESSION_FP,
        idempotency_key=idem,
        max_amount=amount,
        currency="USD" if amount is not None else None,
    )


def _cookie(*, provider, environment, account_fp, authority_fp, capability):
    return issue_continuity_cookie(
        issuer_id="cookie-issuer",
        issuer_key=COOKIE_KEY,
        caller_fingerprint=CALLER_FP,
        provider=provider,
        provider_subject_fingerprint=account_fp,
        source_sha="d" * 40,
        environment=environment,
        capabilities=(capability,),
        authority_fingerprint=authority_fp,
    )


@pytest.mark.asyncio
async def test_solana_mainnet_broadcast_requires_exact_authority_and_replay_is_blocked(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["method"] == "sendTransaction"
        return httpx.Response(200, json={"jsonrpc": "2.0", "id": 1, "result": "sig-live"})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        solana = SolanaRpcClient(
            SolanaRpcConfig("https://rpc.example.test", "mainnet-beta"),
            client=http_client,
        )
        public_key = "SignerPublicKey111"
        transaction = base64.b64encode(b"signed-mainnet-transaction").decode()
        account_fp = solana.account_fingerprint(public_key)
        resource_fp = transaction_fingerprint(transaction)
        authority = _authority(
            provider="solana-rpc",
            environment="mainnet-beta",
            account_fp=account_fp,
            action="broadcast-signed-transaction",
            resource_fp=resource_fp,
            idem="sol-1",
        )
        cookie = _cookie(
            provider="solana-rpc",
            environment="mainnet-beta",
            account_fp=account_fp,
            authority_fp=authority["fingerprint"],
            capability="broadcast-signed-transaction",
        )
        dispatcher = ProviderDispatcher(
            continuity_keys={"cookie-issuer": COOKIE_KEY},
            authority_keys={"authority-issuer": AUTHORITY_KEY},
            ledger=ProductActionLedger(tmp_path / "ledger.json", LEDGER_KEY),
            solana=solana,
        )
        command = {
            "provider": "solana-rpc",
            "environment": "mainnet-beta",
            "action": "broadcast-signed-transaction",
            "idempotency_key": "sol-1",
            "continuity_cookie": cookie,
            "authority_receipt": authority,
            "payload": {"public_key": public_key, "transaction_base64": transaction},
        }
        result = await dispatcher.dispatch(command)
        replay = await dispatcher.dispatch(command)

    assert result["ok"] is True
    assert result["classification"] == "PROVIDER_ACTION_EXECUTED"
    assert result["provider_result"]["signature"] == "sig-live"
    assert result["resource_fingerprint"] == resource_fp
    assert replay["ok"] is False
    assert replay["classification"] == "AUTHORITY_STATE_BLOCKED"


@pytest.mark.asyncio
async def test_solana_broadcast_without_authority_never_calls_rpc(tmp_path):
    called = False

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal called
        called = True
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        solana = SolanaRpcClient(
            SolanaRpcConfig("https://rpc.example.test", "mainnet-beta"),
            client=http_client,
        )
        public_key = "SignerPublicKey111"
        account_fp = solana.account_fingerprint(public_key)
        cookie = issue_continuity_cookie(
            issuer_id="cookie-issuer",
            issuer_key=COOKIE_KEY,
            caller_fingerprint=CALLER_FP,
            provider="solana-rpc",
            provider_subject_fingerprint=account_fp,
            source_sha="d" * 40,
            environment="mainnet-beta",
            capabilities=("broadcast-signed-transaction",),
        )
        dispatcher = ProviderDispatcher(
            continuity_keys={"cookie-issuer": COOKIE_KEY},
            authority_keys={"authority-issuer": AUTHORITY_KEY},
            ledger=ProductActionLedger(tmp_path / "ledger.json", LEDGER_KEY),
            solana=solana,
        )
        result = await dispatcher.dispatch(
            {
                "provider": "solana-rpc",
                "environment": "mainnet-beta",
                "action": "broadcast-signed-transaction",
                "idempotency_key": "sol-2",
                "continuity_cookie": cookie,
                "payload": {
                    "public_key": public_key,
                    "transaction_base64": base64.b64encode(b"signed-tx").decode(),
                },
            }
        )

    assert result["classification"] == "MISSING_AUTHORITY"
    assert called is False


@pytest.mark.asyncio
async def test_cash_app_payment_binds_customer_grant_amount_and_idempotency(tmp_path):
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["payment"]["grant_id"] == "GRG-approved"
        assert body["payment"]["amount"] == 500
        return httpx.Response(201, json={"payment": {"id": "PWC-1", "status": "AUTHORIZED"}})

    transport = httpx.MockTransport(handler)
    async with httpx.AsyncClient(transport=transport) as http_client:
        cash = CashAppPayClient(
            CashAppPayConfig("production"),
            credentials=CashAppPayCredentials(
                client_id="client-1",
                key_id="key-1",
                secret="s" * 32,
                region="PDX",
            ),
            client=http_client,
        )
        merchant = "merchant-1"
        account_fp = cash.merchant_fingerprint(merchant)
        payment_body = {
            "idempotency_key": "cash-1",
            "payment": {
                "amount": 500,
                "currency": "USD",
                "merchant_id": merchant,
                "grant_id": "GRG-approved",
                "reference_id": "order-1",
                "capture": True,
            },
        }
        resource_fp = cash.payment_resource_fingerprint(payment_body)
        authority = _authority(
            provider="cash-app-pay",
            environment="production",
            account_fp=account_fp,
            action="create-payment",
            resource_fp=resource_fp,
            idem="cash-1",
            amount=5.0,
        )
        cookie = _cookie(
            provider="cash-app-pay",
            environment="production",
            account_fp=account_fp,
            authority_fp=authority["fingerprint"],
            capability="create-payment",
        )
        dispatcher = ProviderDispatcher(
            continuity_keys={"cookie-issuer": COOKIE_KEY},
            authority_keys={"authority-issuer": AUTHORITY_KEY},
            ledger=ProductActionLedger(tmp_path / "cash-ledger.json", LEDGER_KEY),
            cash_app_pay=cash,
        )
        result = await dispatcher.dispatch(
            {
                "provider": "cash-app-pay",
                "environment": "production",
                "action": "create-payment",
                "idempotency_key": "cash-1",
                "continuity_cookie": cookie,
                "authority_receipt": authority,
                "payload": {
                    "merchant_id": merchant,
                    "grant_id": "GRG-approved",
                    "amount_cents": 500,
                    "reference_id": "order-1",
                    "idempotency_key": "cash-1",
                    "capture": True,
                },
            }
        )

    assert result["ok"] is True
    assert result["provider_result"]["payment"]["id"] == "PWC-1"
    assert result["account_fingerprint"] == account_fp


@pytest.mark.asyncio
async def test_mcp_server_exposes_only_capabilities_continuity_and_dispatch(tmp_path):
    dispatcher = ProviderDispatcher(
        continuity_keys={"cookie-issuer": COOKIE_KEY},
        authority_keys={"authority-issuer": AUTHORITY_KEY},
        ledger=ProductActionLedger(tmp_path / "ledger.json", LEDGER_KEY),
    )
    server = build_mcp_server(dispatcher)
    tools = await server.list_tools()
    names = {tool.name for tool in tools}
    assert names == {
        "sleepwealth_capabilities",
        "sleepwealth_validate_continuity",
        "sleepwealth_dispatch",
    }
    assert not any("issue" in name or "mint" in name for name in names)
