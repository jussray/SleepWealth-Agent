"""Read-only Interactive Brokers session observer.

This module can observe a locally running TWS / IB Gateway session without
exposing any order-entry methods. It intentionally does not implement
``BaseBroker`` because observation must not be substitutable for execution.

The resulting receipt proves only what the process actually observed. In
particular, ``readonly=True`` is a client-side request to ib_async; it is not
accepted as proof that TWS / IB Gateway itself has its Read-Only API setting
enabled. That provider-side enforcement remains UNKNOWN until a separate,
independently verified receipt exists.
"""

from __future__ import annotations

import hashlib
import ipaddress
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Callable


class IBKRReadOnlyObserverError(RuntimeError):
    """Raised when the read-only observer cannot safely inspect a session."""


def _hash_account(account: str) -> str:
    return hashlib.sha256(account.encode("utf-8")).hexdigest()


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_loopback(host: str) -> bool:
    normalized = str(host).strip().lower()
    if normalized == "localhost":
        return True
    try:
        return ipaddress.ip_address(normalized).is_loopback
    except ValueError:
        return False


@dataclass(slots=True)
class IBKRReadOnlyObserver:
    """Observe account/session existence through a local read-only API client.

    No username, password, token, order, transfer, funding, or signing material
    is accepted by this class. The caller must already have TWS / IB Gateway
    running locally and authenticated through its own supported login flow.
    """

    host: str = "127.0.0.1"
    port: int = 4002
    client_id: int = 91
    timeout: float = 4.0
    client_factory: Callable[[], Any] | None = None

    def _validate(self) -> None:
        if not _is_loopback(self.host):
            raise IBKRReadOnlyObserverError(
                "IBKR read-only observation is restricted to a loopback TWS / IB Gateway endpoint"
            )
        if not 1 <= int(self.port) <= 65535:
            raise IBKRReadOnlyObserverError("IBKR API port must be between 1 and 65535")
        if int(self.client_id) <= 0:
            raise IBKRReadOnlyObserverError(
                "IBKR observer client_id must be greater than zero; client_id=0 is not permitted"
            )
        if float(self.timeout) <= 0:
            raise IBKRReadOnlyObserverError("IBKR observer timeout must be greater than zero")

    def _new_client(self):
        if self.client_factory is not None:
            return self.client_factory()
        try:
            from ib_async import IB
        except ImportError as exc:  # pragma: no cover - depends on optional install
            raise IBKRReadOnlyObserverError(
                "ib_async is not installed; install the optional ibkr-readonly dependency"
            ) from exc
        return IB()

    async def observe(self) -> dict[str, Any]:
        """Return a privacy-preserving, non-authorizing session receipt."""

        self._validate()
        client = self._new_client()
        observed_at = datetime.now(timezone.utc).isoformat()
        checks: list[dict[str, Any]] = [
            {
                "code": "LOCAL_LOOPBACK_ENDPOINT",
                "classification": "VERIFIED",
                "blocking": False,
                "reason": "observer is restricted to a loopback TWS / IB Gateway endpoint",
            },
            {
                "code": "CLIENT_READONLY_REQUEST",
                "classification": "VERIFIED",
                "blocking": False,
                "reason": "ib_async connection is requested with readonly=True",
            },
        ]
        connected = False

        try:
            await client.connectAsync(
                self.host,
                int(self.port),
                clientId=int(self.client_id),
                timeout=float(self.timeout),
                readonly=True,
            )
            connected = bool(client.isConnected())
            if not connected:
                raise IBKRReadOnlyObserverError("IBKR client returned without a connected session")

            accounts = tuple(str(account) for account in (client.managedAccounts() or ()))
            server_time = await client.reqCurrentTimeAsync()
            checks.extend(
                [
                    {
                        "code": "SESSION_CONNECTIVITY",
                        "classification": "VERIFIED",
                        "blocking": False,
                        "reason": "local IBKR API session responded to the observer",
                    },
                    {
                        "code": "MANAGED_ACCOUNT_VISIBILITY",
                        "classification": "VERIFIED" if accounts else "BLOCKED",
                        "blocking": True,
                        "reason": (
                            f"{len(accounts)} managed account(s) visible to the session"
                            if accounts
                            else "connected session exposed no managed accounts"
                        ),
                    },
                    {
                        "code": "TWS_READ_ONLY_ENFORCEMENT",
                        "classification": "UNKNOWN",
                        "blocking": True,
                        "reason": (
                            "client requested readonly=True, but that does not independently prove "
                            "the provider-side Read-Only API setting"
                        ),
                    },
                ]
            )

            safe_payload: dict[str, Any] = {
                "event": "ibkr_readonly_session_observed",
                "classification": "OBSERVED",
                "connected": True,
                "execution_authorized": False,
                "readonly_requested": True,
                "provider_readonly_enforcement": "UNKNOWN",
                "loopback_only": True,
                "client_id": int(self.client_id),
                "account_count": len(accounts),
                "account_fingerprints": sorted(_hash_account(account) for account in accounts),
                "server_time": str(server_time),
                "observed_at": observed_at,
                "checks": checks,
                "truth": (
                    "This receipt proves read-only observation context only. It grants no order, "
                    "transfer, funding, signing, or real-money execution authority."
                ),
            }
            safe_payload["fingerprint"] = _fingerprint(safe_payload)
            return safe_payload
        except IBKRReadOnlyObserverError:
            raise
        except Exception as exc:
            raise IBKRReadOnlyObserverError(f"IBKR read-only observation failed: {exc}") from exc
        finally:
            try:
                if connected or bool(client.isConnected()):
                    client.disconnect()
            except Exception:
                # Disconnect failure cannot turn an observation into execution authority.
                pass
