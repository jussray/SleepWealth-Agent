import asyncio

from backend import vybe_proof


class FakeVybe:
    def __init__(self, _config):
        self.calls = []

    async def call_read_tool(self, name, args):
        self.calls.append((name, args))
        if name == "get-endpoint":
            return {
                "provider": "vybe-solana-mcp",
                "environment": "mainnet-readonly",
                "registry_name": "io.github.vybenetwork/solana-mcp-vybe",
                "endpoint": "https://mcp.vybenetwork.xyz/mcp",
                "provider_fingerprint": "a" * 64,
                "capability_fingerprint": "b" * 64,
                "result_fingerprint": "c" * 64,
                "observed_at": "2026-10-06T12:00:00+00:00",
                "execution_authorized": False,
                "allocation_authorized": False,
                "money_moving": False,
            }
        return {
            "provider": "vybe-solana-mcp",
            "environment": "mainnet-readonly",
            "registry_name": "io.github.vybenetwork/solana-mcp-vybe",
            "endpoint": "https://mcp.vybenetwork.xyz/mcp",
            "provider_fingerprint": "a" * 64,
            "capability_fingerprint": "b" * 64,
            "result_fingerprint": "d" * 64,
            "observed_at": "2026-10-06T12:00:01+00:00",
            "execution_authorized": False,
            "allocation_authorized": False,
            "money_moving": False,
        }


def test_vybe_vercel_proof_is_preview_only_by_default(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "production")
    monkeypatch.setenv("SLEEPWEALTH_VYBE_PROOF_ENABLED", "true")
    monkeypatch.setenv("SLEEPWEALTH_VYBE_MCP_BEARER_TOKEN", "secret")

    status, payload = asyncio.run(vybe_proof.deployed_vybe_proof())

    assert status == 403
    assert payload["classification"] == "PRODUCTION_PROOF_DISABLED"
    assert payload["execution_authorized"] is False


def test_vybe_vercel_proof_fails_closed_without_oauth(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "preview")
    monkeypatch.setenv("SLEEPWEALTH_VYBE_PROOF_ENABLED", "true")
    monkeypatch.delenv("SLEEPWEALTH_VYBE_MCP_BEARER_TOKEN", raising=False)

    status, payload = asyncio.run(vybe_proof.deployed_vybe_proof())

    assert status == 503
    assert payload["classification"] == "VYBE_OAUTH_NOT_CONFIGURED"
    assert payload["raw_market_data_exposed"] is False


def test_vybe_vercel_proof_returns_fingerprints_not_market_payload(monkeypatch):
    monkeypatch.setenv("VERCEL_ENV", "preview")
    monkeypatch.setenv("SLEEPWEALTH_VYBE_PROOF_ENABLED", "true")
    monkeypatch.setenv("SLEEPWEALTH_VYBE_MCP_BEARER_TOKEN", "secret")
    monkeypatch.setattr(vybe_proof, "VybeMcpClient", FakeVybe)

    status, payload = asyncio.run(vybe_proof.deployed_vybe_proof())

    assert status == 200
    assert payload["classification"] == "VERIFIED_LIVE_READ"
    assert payload["provider_fingerprint"] == "a" * 64
    assert payload["capability_fingerprint"] == "b" * 64
    assert payload["endpoint_contract_fingerprint"] == "c" * 64
    assert payload["result_fingerprint"] == "d" * 64
    assert payload["opportunity_evidence"]["authorizes"] is False
    assert payload["opportunity_evidence"]["allocation_authorized"] is False
    assert payload["opportunity_evidence"]["execution_authorized"] is False
    assert payload["raw_market_data_exposed"] is False
    assert "price" not in str(payload).lower()
    assert "secret" not in str(payload)
