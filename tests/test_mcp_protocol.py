import pytest
from mcp import Client

from mcp_gateway.action_ledger import ProductActionLedger
from mcp_gateway.dispatcher import ProviderDispatcher
from mcp_gateway.server import _transport_security, build_mcp_server

COOKIE_KEY = "c" * 32
AUTHORITY_KEY = "a" * 32
LEDGER_KEY = "l" * 32
SOURCE_SHA = "d" * 40


def _dispatcher(tmp_path) -> ProviderDispatcher:
    return ProviderDispatcher(
        source_sha=SOURCE_SHA,
        continuity_keys={"cookie-issuer": COOKIE_KEY},
        authority_keys={"authority-issuer": AUTHORITY_KEY},
        ledger=ProductActionLedger(tmp_path / "ledger.json", LEDGER_KEY),
    )


@pytest.mark.asyncio
async def test_real_mcp_protocol_round_trip_lists_and_calls_capabilities(tmp_path):
    server = build_mcp_server(_dispatcher(tmp_path))
    async with Client(server) as client:
        tools = await client.list_tools()
        names = {tool.name for tool in tools}
        assert names == {
            "sleepwealth_capabilities",
            "sleepwealth_validate_continuity",
            "sleepwealth_dispatch",
        }
        result = await client.call_tool("sleepwealth_capabilities", {})

    payload = result.structured_content
    assert payload["event"] == "mcp_provider_capabilities"
    assert payload["source_sha"] == SOURCE_SHA
    assert payload["authority_issuance_exposed_over_mcp"] is False
    assert payload["fingerprints_are_credentials"] is False


def test_remote_streamable_http_requires_explicit_host_allowlist(monkeypatch):
    monkeypatch.delenv("SLEEPWEALTH_MCP_ALLOWED_HOSTS", raising=False)
    with pytest.raises(RuntimeError, match="ALLOWED_HOSTS"):
        _transport_security("0.0.0.0")


def test_remote_streamable_http_uses_exact_host_and_origin_allowlists(monkeypatch):
    monkeypatch.setenv("SLEEPWEALTH_MCP_ALLOWED_HOSTS", "mcp.example.test,mcp.example.test:*")
    monkeypatch.setenv("SLEEPWEALTH_MCP_ALLOWED_ORIGINS", "https://app.example.test")
    security = _transport_security("0.0.0.0")
    assert security is not None
    assert security.enable_dns_rebinding_protection is True
    assert security.allowed_hosts == ["mcp.example.test", "mcp.example.test:*"]
    assert security.allowed_origins == ["https://app.example.test"]


def test_loopback_streamable_http_uses_sdk_safe_default(monkeypatch):
    monkeypatch.delenv("SLEEPWEALTH_MCP_ALLOWED_HOSTS", raising=False)
    assert _transport_security("127.0.0.1") is None
