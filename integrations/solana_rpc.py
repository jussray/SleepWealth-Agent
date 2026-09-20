from __future__ import annotations

import base64
import hashlib
from dataclasses import dataclass
from typing import Any

import httpx

from broker.provider_identity import provider_account_fingerprint

SUPPORTED_NETWORKS = frozenset({"devnet", "testnet", "mainnet-beta"})


def transaction_fingerprint(transaction_base64: str) -> str:
    if not isinstance(transaction_base64, str) or not transaction_base64.strip():
        raise ValueError("transaction_base64 is required")
    try:
        raw = base64.b64decode(transaction_base64, validate=True)
    except Exception as exc:
        raise ValueError("transaction_base64 must be valid base64") from exc
    if not raw:
        raise ValueError("signed transaction must not be empty")
    return hashlib.sha256(raw).hexdigest()


@dataclass(frozen=True, slots=True)
class SolanaRpcConfig:
    endpoint: str
    network: str

    def __post_init__(self) -> None:
        if self.network not in SUPPORTED_NETWORKS:
            raise ValueError(f"unsupported Solana network: {self.network}")
        if not self.endpoint.startswith(("https://", "http://127.0.0.1", "http://localhost")):
            raise ValueError("Solana RPC endpoint must use HTTPS outside loopback")


class SolanaRpcClient:
    """Solana JSON-RPC adapter with an external-signer boundary.

    This client can observe balances/status, simulate an already-signed transaction,
    and broadcast an already-signed transaction. It never accepts, stores, derives,
    or uses a private key. The MCP/product authority layer must authorize broadcast
    before this method is called.
    """

    def __init__(
        self,
        config: SolanaRpcConfig,
        *,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.config = config
        self._client = client
        self.timeout_seconds = timeout_seconds

    def account_fingerprint(self, public_key: str) -> str:
        public_key = str(public_key or "").strip()
        if not public_key:
            raise ValueError("public_key is required")
        return provider_account_fingerprint(
            "solana-rpc",
            {"network": self.config.network, "public_key": public_key},
        )

    async def _rpc(self, method: str, params: list[Any]) -> Any:
        payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
        if self._client is not None:
            response = await self._client.post(self.config.endpoint, json=payload)
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.post(self.config.endpoint, json=payload)
        response.raise_for_status()
        body = response.json()
        if not isinstance(body, dict):
            raise RuntimeError("Solana RPC response is not an object")
        if body.get("error") is not None:
            raise RuntimeError(f"Solana RPC error: {body['error']}")
        if "result" not in body:
            raise RuntimeError("Solana RPC response is missing result")
        return body["result"]

    async def get_balance(self, public_key: str) -> dict[str, object]:
        result = await self._rpc("getBalance", [public_key, {"commitment": "confirmed"}])
        if not isinstance(result, dict) or "value" not in result:
            raise RuntimeError("Solana getBalance response is invalid")
        return {
            "provider": "solana-rpc",
            "network": self.config.network,
            "account_fingerprint": self.account_fingerprint(public_key),
            "lamports": result["value"],
            "execution_authorized": False,
        }

    async def simulate_signed_transaction(self, transaction_base64: str) -> dict[str, object]:
        fingerprint = transaction_fingerprint(transaction_base64)
        result = await self._rpc(
            "simulateTransaction",
            [
                transaction_base64,
                {
                    "encoding": "base64",
                    "sigVerify": True,
                    "commitment": "confirmed",
                },
            ],
        )
        return {
            "provider": "solana-rpc",
            "network": self.config.network,
            "transaction_fingerprint": fingerprint,
            "simulation": result,
            "broadcast": False,
        }

    async def broadcast_signed_transaction(self, transaction_base64: str) -> dict[str, object]:
        fingerprint = transaction_fingerprint(transaction_base64)
        signature = await self._rpc(
            "sendTransaction",
            [
                transaction_base64,
                {
                    "encoding": "base64",
                    "skipPreflight": False,
                    "preflightCommitment": "confirmed",
                    "maxRetries": 3,
                },
            ],
        )
        if not isinstance(signature, str) or not signature:
            raise RuntimeError("Solana sendTransaction did not return a transaction signature")
        return {
            "provider": "solana-rpc",
            "network": self.config.network,
            "transaction_fingerprint": fingerprint,
            "signature": signature,
            "broadcast": True,
        }

    async def get_signature_status(self, signature: str) -> dict[str, object]:
        result = await self._rpc(
            "getSignatureStatuses",
            [[signature], {"searchTransactionHistory": True}],
        )
        if not isinstance(result, dict):
            raise RuntimeError("Solana getSignatureStatuses response is invalid")
        values = result.get("value")
        status = values[0] if isinstance(values, list) and values else None
        return {
            "provider": "solana-rpc",
            "network": self.config.network,
            "signature": signature,
            "status": status,
            "execution_authorized": False,
        }
