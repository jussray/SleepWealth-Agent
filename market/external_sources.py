"""Read-only external crypto source adapters.

These adapters intentionally do not expose trading, wallet, quote, shift, deposit,
settlement, or account-secret operations. They may contribute observation/catalog
evidence to Sleep Wealth paper simulations, but they never create execution authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from typing import Any, Callable
from urllib.parse import urlparse
from urllib.request import Request, urlopen


SIDESHIFT_COINS_URL = "https://sideshift.ai/api/v2/coins"

_SENSITIVE_OR_EXECUTION_KEYS = {
    "affiliateid",
    "depositaddress",
    "depositmemo",
    "order",
    "orderid",
    "privatekey",
    "quote",
    "quoteid",
    "refundaddress",
    "refundmemo",
    "secret",
    "sessionsecret",
    "settleaddress",
    "settlememo",
    "shift",
    "shiftid",
    "wallet",
    "walletaddress",
    "x-sideshift-secret",
}


def _normalized_key(value: str) -> str:
    return "".join(ch for ch in str(value).lower() if ch.isalnum() or ch == "-")


def _assert_observation_only_payload(payload: dict[str, Any]) -> None:
    blocked = sorted(
        key
        for key in payload
        if _normalized_key(key) in _SENSITIVE_OR_EXECUTION_KEYS
    )
    if blocked:
        raise ValueError(
            "external crypto observers reject execution/credential fields: "
            + ", ".join(blocked)
        )


@dataclass(frozen=True)
class ExternalCryptoSourceCapability:
    name: str
    mode: str
    network_access: str
    read_only: bool = True
    authority: str = "none"
    real_money: bool = False
    wallet_connection: bool = False
    trading_enabled: bool = False
    quote_creation: bool = False
    shift_creation: bool = False
    automated_scraping: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mode": self.mode,
            "network_access": self.network_access,
            "read_only": self.read_only,
            "authority": self.authority,
            "real_money": self.real_money,
            "wallet_connection": self.wallet_connection,
            "trading_enabled": self.trading_enabled,
            "quote_creation": self.quote_creation,
            "shift_creation": self.shift_creation,
            "automated_scraping": self.automated_scraping,
        }


def external_crypto_source_capabilities() -> dict[str, dict[str, Any]]:
    """Return the explicit capability ceiling for supported external crypto sources."""
    return {
        "pump.fun": ExternalCryptoSourceCapability(
            name="pump.fun",
            mode="manual-public-evidence",
            network_access="none",
            automated_scraping=False,
        ).to_dict(),
        "sideshift": ExternalCryptoSourceCapability(
            name="SideShift",
            mode="public-coin-catalog",
            network_access="GET /api/v2/coins only",
        ).to_dict(),
    }


class PumpFunPublicEvidenceObserver:
    """Normalize user-supplied public Pump.fun observations without crawling Pump.fun."""

    source_name = "pump-fun-public-evidence"
    source_classification = "user-supplied-public-evidence"
    automated_network_access = False

    def observe(self, evidence: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(evidence, dict):
            raise TypeError("Pump.fun evidence must be a JSON object")
        _assert_observation_only_payload(evidence)

        source_url = str(evidence.get("source_url", "")).strip()
        parsed = urlparse(source_url)
        if parsed.scheme != "https" or parsed.hostname not in {"pump.fun", "www.pump.fun"}:
            raise ValueError("Pump.fun public evidence requires an https://pump.fun source_url")

        symbol = str(evidence.get("symbol", "")).strip()
        mint = str(evidence.get("mint", "")).strip()
        name = str(evidence.get("name", "")).strip()
        if not symbol and not mint:
            raise ValueError("Pump.fun public evidence requires symbol or mint")

        observed_at = str(evidence.get("observed_at", "")).strip()
        payload = {
            "source_url": source_url,
            "symbol": symbol,
            "mint": mint,
            "name": name,
            "market_cap": evidence.get("market_cap"),
            "observed_at": observed_at,
        }
        fingerprint = sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()

        return {
            **payload,
            "source": self.source_name,
            "source_classification": self.source_classification,
            "classification": "OBSERVED",
            "recorded_at": datetime.now(timezone.utc).isoformat(),
            "fingerprint": fingerprint,
            "continuity_cookie": f"sw-pump-observation-v1:{fingerprint[:32]}",
            "read_only": True,
            "authority": "none",
            "real_money": False,
            "wallet_connection": False,
            "trading_enabled": False,
            "automated_scraping": False,
            "network_request_performed": False,
        }


class SideShiftPublicCoinCatalogObserver:
    """Read SideShift's public supported-coin catalog and nothing else."""

    source_name = "sideshift-public-coin-catalog"
    source_classification = "external-public-catalog"
    endpoint = SIDESHIFT_COINS_URL

    @staticmethod
    def _fetch_json(url: str) -> Any:
        if url != SIDESHIFT_COINS_URL:
            raise ValueError("SideShift observer is restricted to the public /v2/coins endpoint")
        request = Request(
            url,
            method="GET",
            headers={
                "Accept": "application/json",
                "User-Agent": "SleepWealth-ReadOnly-Catalog/1.0",
            },
        )
        with urlopen(request, timeout=10) as response:  # nosec B310 - fixed https endpoint
            return json.loads(response.read().decode("utf-8"))

    def list_supported_coins(
        self,
        fetch_json: Callable[[str], Any] | None = None,
    ) -> dict[str, Any]:
        fetcher = fetch_json or self._fetch_json
        raw = fetcher(self.endpoint)
        if not isinstance(raw, list):
            raise ValueError("SideShift public coin catalog must return a list")

        coins: list[dict[str, Any]] = []
        for row in raw:
            if not isinstance(row, dict):
                continue
            _assert_observation_only_payload(row)
            networks = row.get("networks")
            if not isinstance(networks, list):
                networks = []
            coins.append(
                {
                    "coin": str(row.get("coin", row.get("id", ""))).strip(),
                    "name": str(row.get("name", "")).strip(),
                    "networks": [str(network) for network in networks],
                    "fixed_only": row.get("fixedOnly", False),
                    "deposit_variable_only": row.get("depositVariableOnly", False),
                    "settle_variable_only": row.get("settleVariableOnly", False),
                }
            )

        fingerprint = sha256(
            json.dumps(coins, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
        ).hexdigest()
        return {
            "source": self.source_name,
            "source_classification": self.source_classification,
            "endpoint_scope": "GET /api/v2/coins only",
            "classification": "OBSERVED",
            "coins": coins,
            "fingerprint": fingerprint,
            "continuity_cookie": f"sw-sideshift-catalog-v1:{fingerprint[:32]}",
            "read_only": True,
            "authority": "none",
            "real_money": False,
            "wallet_connection": False,
            "trading_enabled": False,
            "quote_creation": False,
            "shift_creation": False,
            "account_secret_used": False,
        }
