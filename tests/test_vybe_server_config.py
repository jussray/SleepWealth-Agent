import pytest

from mcp_gateway.server import build_dispatcher_from_env


_REQUIRED = {
    "SLEEPWEALTH_SOURCE_SHA": "a" * 40,
    "SLEEPWEALTH_MCP_COOKIE_ISSUER": "cookie-issuer",
    "SLEEPWEALTH_MCP_COOKIE_KEY": "c" * 32,
    "SLEEPWEALTH_MCP_AUTHORITY_ISSUER": "authority-issuer",
    "SLEEPWEALTH_MCP_AUTHORITY_KEY": "a" * 32,
    "SLEEPWEALTH_MCP_LEDGER_KEY": "l" * 32,
}


def _base_env(monkeypatch, tmp_path):
    for name, value in _REQUIRED.items():
        monkeypatch.setenv(name, value)
    monkeypatch.setenv("SLEEPWEALTH_MCP_LEDGER_PATH", str(tmp_path / "ledger.json"))
    for name in (
        "SLEEPWEALTH_SOLANA_RPC_URL",
        "SLEEPWEALTH_CASH_APP_ENV",
        "SLEEPWEALTH_VYBE_MCP_BEARER_TOKEN",
        "SLEEPWEALTH_VYBE_MCP_URL",
    ):
        monkeypatch.delenv(name, raising=False)


def test_vybe_runtime_enablement_fails_closed_without_oauth_token(monkeypatch, tmp_path):
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SLEEPWEALTH_VYBE_MCP_ENABLED", "true")

    with pytest.raises(RuntimeError, match="VYBE_MCP_BEARER_TOKEN"):
        build_dispatcher_from_env()


def test_vybe_runtime_token_is_kept_inside_provider_client(monkeypatch, tmp_path):
    _base_env(monkeypatch, tmp_path)
    monkeypatch.setenv("SLEEPWEALTH_VYBE_MCP_ENABLED", "true")
    monkeypatch.setenv("SLEEPWEALTH_VYBE_MCP_BEARER_TOKEN", "runtime-oauth-token")

    dispatcher = build_dispatcher_from_env()

    assert dispatcher.vybe is not None
    assert dispatcher.vybe.config.environment == "mainnet-readonly"
    assert dispatcher.vybe.config.bearer_token == "runtime-oauth-token"
    capabilities = dispatcher.capabilities()
    rendered = str(capabilities)
    assert "runtime-oauth-token" not in rendered
    assert "build-vybe-transaction" not in rendered
    assert "pay-with-x402" not in rendered
