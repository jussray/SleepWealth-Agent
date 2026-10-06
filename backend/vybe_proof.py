from __future__ import annotations

import hashlib
import json
import os
from typing import Mapping

from integrations.vybe_mcp import (
    DEFAULT_VYBE_MCP_ENDPOINT,
    VybeMcpClient,
    VybeMcpConfig,
)
from race.opportunity_evidence import opportunity_evidence_receipt

# Neutral, documented Solana USDC mint used only as a bounded connectivity fixture.
# The proof response never exposes price/market payloads or recommends an asset.
_VYBE_PROOF_PATH = "/v4/tokens/EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v"
_VYBE_PROOF_METHOD = "GET"


def _bool_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _fingerprint(payload: object) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _blocked(reason: str, *, classification: str = "BLOCKED") -> dict[str, object]:
    return {
        "status": "blocked",
        "classification": classification,
        "reason": reason,
        "provider": "vybe-solana-mcp",
        "environment": "mainnet-readonly",
        "authorizes": False,
        "allocation_authorized": False,
        "execution_authorized": False,
        "money_moving": False,
        "raw_market_data_exposed": False,
    }


async def deployed_vybe_proof() -> tuple[int, dict[str, object]]:
    """Run one bounded, preview-safe Vybe read and return proof metadata only.

    This endpoint is deliberately not a general proxy. It binds to one documented
    read path, returns no raw market payload, and cannot construct/broadcast a
    transaction or perform payment.
    """

    vercel_env = os.getenv("VERCEL_ENV", "").strip().lower()
    if vercel_env == "production" and not _bool_env(
        "SLEEPWEALTH_VYBE_PROOF_ALLOW_PRODUCTION"
    ):
        return 403, _blocked(
            "Vybe deployment proof is preview-only unless a separate production override is set",
            classification="PRODUCTION_PROOF_DISABLED",
        )

    if not _bool_env("SLEEPWEALTH_VYBE_PROOF_ENABLED"):
        return 503, _blocked(
            "Vybe deployment proof is not enabled",
            classification="VYBE_PROOF_DISABLED",
        )

    token = os.getenv("SLEEPWEALTH_VYBE_MCP_BEARER_TOKEN", "").strip()
    if not token:
        return 503, _blocked(
            "Vybe OAuth bearer token is not configured in runtime secret storage",
            classification="VYBE_OAUTH_NOT_CONFIGURED",
        )

    client = VybeMcpClient(
        VybeMcpConfig(
            endpoint=os.getenv(
                "SLEEPWEALTH_VYBE_MCP_URL",
                DEFAULT_VYBE_MCP_ENDPOINT,
            ).strip(),
            bearer_token=token,
        )
    )

    contract = await client.call_read_tool(
        "get-endpoint",
        {"path": _VYBE_PROOF_PATH, "method": _VYBE_PROOF_METHOD},
    )
    observation = await client.call_read_tool(
        "query-vybe-api",
        {"path": _VYBE_PROOF_PATH, "query": {}},
    )

    resource = {
        "action": "query-vybe-api",
        "payload": {"path": _VYBE_PROOF_PATH, "query": {}},
    }
    resource_fingerprint = _fingerprint(resource)
    evidence = opportunity_evidence_receipt(
        provider="vybe-solana-mcp",
        action="query-vybe-api",
        resource_fingerprint=resource_fingerprint,
        provider_result=observation,
    )

    return 200, {
        "status": "ok",
        "classification": "VERIFIED_LIVE_READ",
        "provider": "vybe-solana-mcp",
        "environment": observation["environment"],
        "registry_name": observation["registry_name"],
        "endpoint": observation["endpoint"],
        "provider_fingerprint": observation["provider_fingerprint"],
        "capability_fingerprint": observation["capability_fingerprint"],
        "endpoint_contract_fingerprint": contract["result_fingerprint"],
        "resource_fingerprint": resource_fingerprint,
        "result_fingerprint": observation["result_fingerprint"],
        "observed_at": observation["observed_at"],
        "opportunity_evidence": evidence,
        "authorizes": False,
        "allocation_authorized": False,
        "execution_authorized": False,
        "money_moving": False,
        "raw_market_data_exposed": False,
    }
