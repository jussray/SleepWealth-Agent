"""Read-only observer for an already-authorized Alpaca live brokerage account.

The observer performs exactly one GET against Alpaca's live Trading API account
endpoint. It cannot place, cancel, replace, fund, transfer, or sign an order. Raw
account identifiers and OAuth credentials are never included in the receipt.

A successful observation proves only current provider/account state. It does not
prove the holder is 18+, grant trading authority, or prove that Sleep Wealth is
approved by Alpaca for third-party live trading.
"""

from __future__ import annotations

import hashlib
import inspect
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable

import httpx

ALPACA_LIVE_BASE_URL = "https://api.alpaca.markets"
ACCOUNT_PATH = "/v2/account"


class AlpacaReadOnlyObserverError(RuntimeError):
    """Raised when a live-account observation cannot be safely established."""


def _fingerprint(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _payload_fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


RequestJson = Callable[[str, dict[str, str], float], Any | Awaitable[Any]]


@dataclass(slots=True)
class AlpacaReadOnlyObserver:
    """Observe Alpaca live account state without exposing an execution method."""

    oauth_token: str
    timeout: float = 5.0
    base_url: str = ALPACA_LIVE_BASE_URL
    request_json: RequestJson | None = None

    def _validate(self) -> None:
        if self.base_url.rstrip("/") != ALPACA_LIVE_BASE_URL:
            raise AlpacaReadOnlyObserverError(
                "Alpaca observation is restricted to the canonical live Trading API endpoint"
            )
        if not isinstance(self.oauth_token, str) or not self.oauth_token.strip():
            raise AlpacaReadOnlyObserverError("Alpaca OAuth token is required for observation")
        if float(self.timeout) <= 0:
            raise AlpacaReadOnlyObserverError("Alpaca observer timeout must be greater than zero")

    async def _get_account(self) -> dict[str, Any]:
        url = f"{ALPACA_LIVE_BASE_URL}{ACCOUNT_PATH}"
        headers = {
            "Authorization": f"Bearer {self.oauth_token}",
            "Accept": "application/json",
            "User-Agent": "SleepWealth/read-only-account-observer",
        }
        if self.request_json is not None:
            result = self.request_json(url, headers, float(self.timeout))
            if inspect.isawaitable(result):
                result = await result
            if not isinstance(result, dict):
                raise AlpacaReadOnlyObserverError("Alpaca account response was not a JSON object")
            return dict(result)

        try:
            async with httpx.AsyncClient(timeout=float(self.timeout), follow_redirects=False) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                payload = response.json()
        except Exception as exc:  # pragma: no cover - requires external provider
            raise AlpacaReadOnlyObserverError(
                "Alpaca live-account observation failed without exposing provider credentials"
            ) from exc
        if not isinstance(payload, dict):
            raise AlpacaReadOnlyObserverError("Alpaca account response was not a JSON object")
        return dict(payload)

    async def observe(self) -> dict[str, Any]:
        """Return a privacy-preserving non-authorizing live-account observation."""

        self._validate()
        account = await self._get_account()

        account_id = str(account.get("id") or "").strip()
        account_number = str(account.get("account_number") or "").strip()
        if not account_id and not account_number:
            raise AlpacaReadOnlyObserverError(
                "Alpaca account response did not expose a stable account identity"
            )

        status = str(account.get("status") or "UNKNOWN").upper()
        crypto_status = str(account.get("crypto_status") or "UNKNOWN").upper()
        account_blocked = account.get("account_blocked") is True
        trading_blocked = account.get("trading_blocked") is True
        suspended = account.get("trade_suspended_by_user") is True
        blocked = account_blocked or trading_blocked or suspended

        permissions: list[str] = []
        if status == "ACTIVE" and not blocked:
            permissions.append("stock-market")
        if crypto_status == "ACTIVE" and not blocked:
            permissions.append("crypto")

        stable_identity = f"alpaca|{account_id}|{account_number}"
        safe_payload: dict[str, Any] = {
            "event": "provider_live_account_observed",
            "classification": "OBSERVED",
            "provider": "alpaca",
            "environment": "live",
            "connected": True,
            "source_endpoint": f"GET {ACCOUNT_PATH}",
            "account_fingerprint": _fingerprint(stable_identity),
            "account_status": status,
            "crypto_status": crypto_status,
            "account_blocked": account_blocked,
            "trading_blocked": trading_blocked,
            "trade_suspended_by_user": suspended,
            "asset_permissions": permissions,
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "execution_authorized": False,
            "order_submit_capability": False,
            "contains_credentials": False,
            "truth": (
                "This receipt proves a read-only observation of Alpaca live account state only. "
                "It does not prove age eligibility, app approval, or execution authority."
            ),
        }
        safe_payload["observation_fingerprint"] = _payload_fingerprint(safe_payload)
        return safe_payload
