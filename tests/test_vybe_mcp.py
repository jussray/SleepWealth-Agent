from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from integrations.vybe_mcp import (
    VYBE_ALLOWED_TOOLS,
    VYBE_EXCLUDED_TOOLS,
    VYBE_OAUTH_SCOPES,
    VYBE_PREPARE_WRITE_TOOLS,
    VYBE_READ_TOOLS,
    VybeMcpClient,
    VybeMcpConfig,
)
from mcp_gateway.providers import get_provider_manifest
from race.opportunity_evidence import opportunity_evidence_receipt


def _tool(name, *, schema=None, read_only=True, destructive=False):
    return {
        "name": name,
        "description": f"{name} test tool",
        "inputSchema": schema or {"type": "object"},
        "annotations": {
            "readOnlyHint": read_only,
            "destructiveHint": destructive,
            "idempotentHint": True,
            "openWorldHint": name.startswith("query-"),
        },
    }


class FakeTool:
    def __init__(self, payload):
        self.payload = payload
        self.name = payload["name"]

    def model_dump(self, **_kwargs):
        return dict(self.payload)


class FakeClient:
    def __init__(self, tools, result):
        self._tools = [FakeTool(tool) for tool in tools]
        self._result = result
        self.calls = []

    async def list_tools(self):
        return SimpleNamespace(tools=self._tools)

    async def call_tool(self, name, arguments):
        self.calls.append((name, arguments))
        return SimpleNamespace(structured_content=self._result, content=[])


def _factory(fake):
    @asynccontextmanager
    async def factory():
        yield fake

    return factory


@pytest.mark.asyncio
async def test_vybe_read_bridge_returns_fingerprinted_non_authorizing_observation():
    tools = [
        _tool("list-endpoints"),
        _tool("search-endpoints"),
        _tool("get-endpoint"),
        _tool("query-vybe-api"),
        _tool("query-vybe-api-batch"),
        _tool("build-vybe-transaction", read_only=False, destructive=True),
        _tool("pay-with-x402"),
    ]
    fake = FakeClient(tools, {"status": 200, "body": {"price": 123}})
    client = VybeMcpClient(VybeMcpConfig(), client_factory=_factory(fake))

    result = await client.call_read_tool(
        "query-vybe-api",
        {"path": "/v4/token/test", "query": {"limit": "1"}},
    )

    assert result["provider"] == "vybe-solana-mcp"
    assert result["environment"] == "mainnet-readonly"
    assert len(result["provider_fingerprint"]) == 64
    assert len(result["capability_fingerprint"]) == 64
    assert len(result["result_fingerprint"]) == 64
    assert result["execution_authorized"] is False
    assert result["allocation_authorized"] is False
    assert result["money_moving"] is False
    assert set(result["excluded_remote_tools"]) == VYBE_EXCLUDED_TOOLS
    assert fake.calls == [
        (
            "query-vybe-api",
            {"path": "/v4/token/test", "query": {"limit": "1"}},
        )
    ]

    receipt = opportunity_evidence_receipt(
        provider="vybe-solana-mcp",
        action="query-vybe-api",
        resource_fingerprint="a" * 64,
        provider_result=result,
    )
    assert receipt["continuity_cookie"].startswith("sw-opportunity-v1:")
    assert receipt["authorizes"] is False
    assert receipt["allocation_authorized"] is False
    assert receipt["execution_authorized"] is False
    assert "profitability" in receipt["does_not_prove"]


@pytest.mark.asyncio
async def test_vybe_prepare_write_returns_unsigned_nonexecuting_result():
    tools = [
        _tool("build-vybe-transaction", read_only=False, destructive=True),
    ]
    fake = FakeClient(tools, {"status": 200, "body": {"transaction": "unsigned-base64"}})
    client = VybeMcpClient(VybeMcpConfig(), client_factory=_factory(fake))

    result = await client.call_tool(
        "build-vybe-transaction",
        {"path": "/v4/trading/swap", "body": {"quote": "test"}},
    )

    assert result["capability_effect"] == "prepare-write"
    assert result["write_prepared"] is True
    assert result["execution_authorized"] is False
    assert result["signing_authorized"] is False
    assert result["broadcast_authorized"] is False
    assert result["money_moving"] is False
    assert fake.calls == [
        (
            "build-vybe-transaction",
            {"path": "/v4/trading/swap", "body": {"quote": "test"}},
        )
    ]


@pytest.mark.asyncio
async def test_vybe_x402_remains_excluded():
    fake = FakeClient([_tool("pay-with-x402")], {"ignored": True})
    client = VybeMcpClient(VybeMcpConfig(), client_factory=_factory(fake))

    with pytest.raises(ValueError, match="local allowlist"):
        await client.call_tool("pay-with-x402", {})

    assert fake.calls == []


@pytest.mark.asyncio
async def test_vybe_capability_fingerprint_renews_when_remote_schema_changes():
    base_tools = [_tool(name) for name in sorted(VYBE_READ_TOOLS)]
    first = FakeClient(base_tools, {"status": 200, "body": {"value": 1}})
    changed = [
        _tool(
            name,
            schema={"type": "object", "properties": {"newField": {"type": "string"}}}
            if name == "query-vybe-api"
            else None,
        )
        for name in sorted(VYBE_READ_TOOLS)
    ]
    second = FakeClient(changed, {"status": 200, "body": {"value": 1}})

    first_client = VybeMcpClient(VybeMcpConfig(), client_factory=_factory(first))
    second_client = VybeMcpClient(VybeMcpConfig(), client_factory=_factory(second))

    one = await first_client.call_read_tool(
        "query-vybe-api",
        {"path": "/v4/test", "query": {}},
    )
    two = await second_client.call_read_tool(
        "query-vybe-api",
        {"path": "/v4/test", "query": {}},
    )

    assert one["capability_fingerprint"] != two["capability_fingerprint"]
    assert one["provider_fingerprint"] == two["provider_fingerprint"]


@pytest.mark.asyncio
async def test_vybe_fails_closed_if_remote_read_tool_loses_readonly_annotation():
    fake = FakeClient(
        [_tool("query-vybe-api", read_only=False, destructive=True)],
        {"status": 200},
    )
    client = VybeMcpClient(VybeMcpConfig(), client_factory=_factory(fake))

    with pytest.raises(RuntimeError, match="read-only"):
        await client.call_read_tool(
            "query-vybe-api",
            {"path": "/v4/test", "query": {}},
        )

    assert fake.calls == []


def test_vybe_batch_reads_are_locally_allowlisted():
    client = VybeMcpClient(VybeMcpConfig(), client_factory=lambda: None)

    with pytest.raises(ValueError, match="batch path"):
        client._validate_arguments(
            "query-vybe-api-batch",
            {"path": "/v4/trading/swap", "body": {"wallets": ["x"]}},
        )


def test_vybe_provider_manifest_exposes_read_and_unsigned_prepare_write_only():
    manifest = get_provider_manifest("vybe-solana-mcp")

    assert manifest.provider_class == "solana-intelligence-provider"
    assert set(manifest.actions) == VYBE_ALLOWED_TOOLS
    assert set(manifest.write_preparation_actions) == VYBE_PREPARE_WRITE_TOOLS
    assert set(manifest.actions).isdisjoint(VYBE_EXCLUDED_TOOLS)
    assert manifest.authority_required_actions == ()
    assert manifest.money_moving_actions == ()
    assert VYBE_OAUTH_SCOPES == ("openid", "email", "mcp:read", "mcp:write")
