from __future__ import annotations

import os
from pathlib import Path

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings

from integrations.cash_app_pay import CashAppPayClient, CashAppPayConfig, CashAppPayCredentials
from integrations.solana_rpc import SolanaRpcClient, SolanaRpcConfig
from mcp_gateway.action_ledger import ProductActionLedger
from mcp_gateway.continuity import validate_continuity_cookie
from mcp_gateway.dispatcher import ProviderDispatcher


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise RuntimeError(f"required environment variable is missing: {name}")
    return value


def _csv_env(name: str) -> list[str]:
    return [value.strip() for value in os.getenv(name, "").split(",") if value.strip()]


def build_dispatcher_from_env() -> ProviderDispatcher:
    source_sha = _required_env("SLEEPWEALTH_SOURCE_SHA")
    cookie_issuer = _required_env("SLEEPWEALTH_MCP_COOKIE_ISSUER")
    cookie_key = _required_env("SLEEPWEALTH_MCP_COOKIE_KEY")
    authority_issuer = _required_env("SLEEPWEALTH_MCP_AUTHORITY_ISSUER")
    authority_key = _required_env("SLEEPWEALTH_MCP_AUTHORITY_KEY")
    ledger_key = _required_env("SLEEPWEALTH_MCP_LEDGER_KEY")
    ledger_path = Path(os.getenv("SLEEPWEALTH_MCP_LEDGER_PATH", ".sleepwealth/mcp-actions.json"))

    solana = None
    solana_url = os.getenv("SLEEPWEALTH_SOLANA_RPC_URL", "").strip()
    if solana_url:
        solana = SolanaRpcClient(
            SolanaRpcConfig(
                endpoint=solana_url,
                network=os.getenv("SLEEPWEALTH_SOLANA_NETWORK", "devnet").strip(),
            )
        )

    cash_app_pay = None
    cash_environment = os.getenv("SLEEPWEALTH_CASH_APP_ENV", "").strip()
    if cash_environment:
        credentials = None
        client_id = os.getenv("SLEEPWEALTH_CASH_APP_CLIENT_ID", "").strip()
        key_id = os.getenv("SLEEPWEALTH_CASH_APP_KEY_ID", "").strip()
        secret = os.getenv("SLEEPWEALTH_CASH_APP_SECRET", "").strip()
        region = os.getenv("SLEEPWEALTH_CASH_APP_REGION", "").strip()
        if any((client_id, key_id, secret, region)):
            if not all((client_id, key_id, secret, region)):
                raise RuntimeError("Cash App Pay credentials must be configured as one complete set")
            credentials = CashAppPayCredentials(
                client_id=client_id,
                key_id=key_id,
                secret=secret,
                region=region,
            )
        cash_app_pay = CashAppPayClient(
            CashAppPayConfig(cash_environment),
            credentials=credentials,
        )

    return ProviderDispatcher(
        source_sha=source_sha,
        continuity_keys={cookie_issuer: cookie_key},
        authority_keys={authority_issuer: authority_key},
        ledger=ProductActionLedger(ledger_path, ledger_key),
        solana=solana,
        cash_app_pay=cash_app_pay,
    )


def build_mcp_server(dispatcher: ProviderDispatcher) -> MCPServer:
    server = MCPServer(
        "SleepWealth Provider Gateway",
        instructions=(
            "Use capabilities first. Fingerprints/cookies are continuity markers, never credentials. "
            "Consequential provider actions require a separately trusted product authority receipt. "
            "Never send private keys or provider secrets through MCP payloads."
        ),
    )

    @server.tool()
    def sleepwealth_capabilities() -> dict[str, object]:
        """List provider capabilities, source identity, and authority boundaries."""
        return dispatcher.capabilities()

    @server.tool()
    def sleepwealth_validate_continuity(cookie: dict[str, object]) -> dict[str, object]:
        """Validate one authenticated non-authorizing continuity cookie."""
        return validate_continuity_cookie(
            cookie,
            trusted_keys=dispatcher.continuity_keys,
        ).to_dict()

    @server.tool()
    async def sleepwealth_dispatch(command: dict[str, object]) -> dict[str, object]:
        """Dispatch a provider action through continuity, authority, kill, and replay gates."""
        return await dispatcher.dispatch(command)

    return server


def build_server_from_env() -> MCPServer:
    return build_mcp_server(build_dispatcher_from_env())


def _transport_security(host: str) -> TransportSecuritySettings | None:
    if host in {"127.0.0.1", "localhost", "::1"}:
        return None
    allowed_hosts = _csv_env("SLEEPWEALTH_MCP_ALLOWED_HOSTS")
    if not allowed_hosts:
        raise RuntimeError(
            "non-loopback MCP requires SLEEPWEALTH_MCP_ALLOWED_HOSTS for DNS-rebinding protection"
        )
    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=allowed_hosts,
        allowed_origins=_csv_env("SLEEPWEALTH_MCP_ALLOWED_ORIGINS"),
    )


def main() -> None:
    server = build_server_from_env()
    transport = os.getenv("SLEEPWEALTH_MCP_TRANSPORT", "stdio").strip().lower()
    if transport == "stdio":
        server.run("stdio")
        return
    if transport != "streamable-http":
        raise RuntimeError("SLEEPWEALTH_MCP_TRANSPORT must be stdio or streamable-http")
    host = os.getenv("SLEEPWEALTH_MCP_HOST", "127.0.0.1").strip()
    port = int(os.getenv("SLEEPWEALTH_MCP_PORT", "8000"))
    server.run(
        "streamable-http",
        host=host,
        port=port,
        streamable_http_path="/mcp",
        transport_security=_transport_security(host),
    )


if __name__ == "__main__":
    main()
