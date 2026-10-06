from __future__ import annotations

from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, AsyncContextManager, Callable, Mapping

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

from broker.provider_identity import provider_account_fingerprint

DEFAULT_VYBE_MCP_ENDPOINT = "https://mcp.vybenetwork.xyz/mcp"
VYBE_REGISTRY_NAME = "io.github.vybenetwork/solana-mcp-vybe"
VYBE_ENVIRONMENT = "mainnet-readonly"

VYBE_READ_TOOLS = frozenset(
    {
        "list-endpoints",
        "search-endpoints",
        "get-endpoint",
        "query-vybe-api",
        "query-vybe-api-batch",
    }
)
VYBE_EXCLUDED_TOOLS = frozenset({"build-vybe-transaction", "pay-with-x402"})
VYBE_BATCH_READ_PATHS = frozenset(
    {
        "/v4/wallets/batch/token-balances",
        "/v4/wallets/batch/token-balances-ts",
        "/v4/wallets/batch/token-accounts-balance-ts",
        "/v4/wallets/batch/dust-accounts",
        "/v4/wallets/batch/empty-accounts",
    }
)


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _tool_snapshot(tool: object) -> dict[str, object]:
    if hasattr(tool, "model_dump"):
        raw = tool.model_dump(mode="json", by_alias=True, exclude_none=True)
    elif isinstance(tool, Mapping):
        raw = dict(tool)
    else:
        raw = {
            "name": getattr(tool, "name", None),
            "description": getattr(tool, "description", None),
            "inputSchema": getattr(tool, "inputSchema", None),
            "outputSchema": getattr(tool, "outputSchema", None),
            "annotations": getattr(tool, "annotations", None),
        }
    return {
        key: raw[key]
        for key in ("name", "description", "inputSchema", "outputSchema", "annotations")
        if key in raw and raw[key] is not None
    }


def _result_payload(result: object) -> object:
    structured = getattr(result, "structured_content", None)
    if structured is None:
        structured = getattr(result, "structuredContent", None)
    if structured is not None:
        return structured

    content = []
    for item in getattr(result, "content", []) or []:
        if hasattr(item, "model_dump"):
            content.append(item.model_dump(mode="json", by_alias=True, exclude_none=True))
        else:
            content.append(str(item))
    return {"content": content}


@dataclass(frozen=True, slots=True)
class VybeMcpConfig:
    endpoint: str = DEFAULT_VYBE_MCP_ENDPOINT
    bearer_token: str | None = None
    environment: str = VYBE_ENVIRONMENT

    def __post_init__(self) -> None:
        endpoint = str(self.endpoint or "").strip()
        if endpoint != DEFAULT_VYBE_MCP_ENDPOINT and not endpoint.startswith(
            ("http://127.0.0.1", "http://localhost")
        ):
            raise ValueError(
                "Vybe MCP endpoint must be the canonical HTTPS endpoint or loopback for tests"
            )
        if self.environment != VYBE_ENVIRONMENT:
            raise ValueError(f"Vybe environment must be {VYBE_ENVIRONMENT}")
        object.__setattr__(self, "endpoint", endpoint)

    @property
    def provider_fingerprint(self) -> str:
        return provider_account_fingerprint(
            "vybe-solana-mcp",
            {
                "registry_name": VYBE_REGISTRY_NAME,
                "endpoint": self.endpoint,
                "environment": self.environment,
            },
        )


class VybeMcpClient:
    """Read-only bridge from Sleep Wealth to Solana MCP by Vybe.

    The bridge deliberately excludes transaction construction and x402 payment.
    OAuth credentials remain transport secrets and are never accepted through
    Sleep Wealth MCP command payloads.
    """

    def __init__(
        self,
        config: VybeMcpConfig,
        *,
        client_factory: Callable[[], AsyncContextManager[Any]] | None = None,
    ) -> None:
        self.config = config
        self._client_factory = client_factory

    @asynccontextmanager
    async def _connect(self):
        if self._client_factory is not None:
            async with self._client_factory() as client:
                yield client
            return

        token = str(self.config.bearer_token or "").strip()
        if not token:
            raise RuntimeError(
                "Vybe MCP OAuth bearer token is required for runtime live reads"
            )
        headers = {"Authorization": f"Bearer {token}"}
        timeout = httpx2.Timeout(30.0, read=300.0)
        async with httpx2.AsyncClient(headers=headers, timeout=timeout) as http_client:
            transport = streamable_http_client(
                self.config.endpoint,
                http_client=http_client,
            )
            async with Client(transport) as client:
                yield client

    def _validate_arguments(self, tool_name: str, arguments: Mapping[str, object]) -> None:
        if tool_name == "list-endpoints":
            if arguments:
                raise ValueError("list-endpoints does not accept arguments")
            return
        if tool_name == "search-endpoints":
            if not str(arguments.get("pattern", "")).strip():
                raise ValueError("search-endpoints requires pattern")
            return
        if tool_name == "get-endpoint":
            if not str(arguments.get("path", "")).strip() or not str(
                arguments.get("method", "")
            ).strip():
                raise ValueError("get-endpoint requires path and method")
            return
        if tool_name == "query-vybe-api":
            path = str(arguments.get("path", "")).strip()
            if not path.startswith("/v4/"):
                raise ValueError("query-vybe-api path must begin with /v4/")
            query = arguments.get("query", {})
            if not isinstance(query, Mapping):
                raise ValueError("query-vybe-api query must be an object")
            if any(not isinstance(value, str) for value in query.values()):
                raise ValueError("query-vybe-api query values must be strings")
            return
        if tool_name == "query-vybe-api-batch":
            path = str(arguments.get("path", "")).strip()
            if path not in VYBE_BATCH_READ_PATHS:
                raise ValueError("batch path is outside the local read-only allowlist")
            if not isinstance(arguments.get("body"), Mapping):
                raise ValueError("query-vybe-api-batch requires a body object")
            return
        raise ValueError(f"tool is outside the Vybe read-only allowlist: {tool_name}")

    async def call_read_tool(
        self,
        tool_name: str,
        arguments: Mapping[str, object],
    ) -> dict[str, object]:
        tool_name = str(tool_name or "").strip()
        if tool_name not in VYBE_READ_TOOLS:
            raise ValueError(f"tool is outside the Vybe read-only allowlist: {tool_name}")
        self._validate_arguments(tool_name, arguments)

        async with self._connect() as client:
            listed = await client.list_tools()
            snapshots = [_tool_snapshot(tool) for tool in listed.tools]
            by_name = {
                str(snapshot.get("name", "")): snapshot
                for snapshot in snapshots
                if snapshot.get("name")
            }
            requested = by_name.get(tool_name)
            if requested is None:
                raise RuntimeError(f"Vybe MCP did not advertise required tool: {tool_name}")

            annotations = requested.get("annotations")
            if not isinstance(annotations, Mapping):
                raise RuntimeError("Vybe MCP read tool is missing safety annotations")
            if annotations.get("readOnlyHint") is not True:
                raise RuntimeError("Vybe MCP tool no longer declares read-only behavior")
            if annotations.get("destructiveHint") is not False:
                raise RuntimeError("Vybe MCP tool no longer declares non-destructive behavior")

            capability_fingerprint = _canonical_digest(
                {
                    "registry_name": VYBE_REGISTRY_NAME,
                    "endpoint": self.config.endpoint,
                    "tools": sorted(snapshots, key=lambda item: str(item.get("name", ""))),
                }
            )
            result = await client.call_tool(tool_name, dict(arguments))
            payload = _result_payload(result)
            observed_at = datetime.now(timezone.utc).isoformat()

        return {
            "provider": "vybe-solana-mcp",
            "environment": self.config.environment,
            "registry_name": VYBE_REGISTRY_NAME,
            "endpoint": self.config.endpoint,
            "provider_fingerprint": self.config.provider_fingerprint,
            "capability_fingerprint": capability_fingerprint,
            "tool": tool_name,
            "result": payload,
            "result_fingerprint": _canonical_digest(payload),
            "observed_at": observed_at,
            "execution_authorized": False,
            "allocation_authorized": False,
            "money_moving": False,
            "excluded_remote_tools": sorted(VYBE_EXCLUDED_TOOLS),
        }
