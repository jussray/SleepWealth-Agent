from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from typing import Any, Mapping

import httpx

from broker.provider_identity import provider_account_fingerprint


@dataclass(frozen=True, slots=True)
class CashAppPayCredentials:
    client_id: str
    key_id: str
    secret: str
    region: str

    def __post_init__(self) -> None:
        if not all(str(value or "").strip() for value in (self.client_id, self.key_id, self.secret, self.region)):
            raise ValueError("Cash App Pay client_id, key_id, secret, and region are required")
        if len(self.secret.encode("utf-8")) < 32:
            raise ValueError("Cash App Pay secret must be at least 32 bytes")


@dataclass(frozen=True, slots=True)
class CashAppPayConfig:
    environment: str

    def __post_init__(self) -> None:
        if self.environment not in {"sandbox", "production"}:
            raise ValueError("Cash App Pay environment must be sandbox or production")

    @property
    def base_url(self) -> str:
        return (
            "https://sandbox.api.cash.app"
            if self.environment == "sandbox"
            else "https://api.cash.app"
        )


class CashAppPayClient:
    """Cash App Pay partner client for customer-approved merchant payments.

    This adapter intentionally does not model arbitrary peer-to-peer Cash App
    transfers or direct consumer balance control. The production create-payment
    path requires a Cash App grant generated from customer approval plus the
    separate SleepWealth product authority gate at the MCP router.
    """

    def __init__(
        self,
        config: CashAppPayConfig,
        *,
        credentials: CashAppPayCredentials | None = None,
        client: httpx.AsyncClient | None = None,
        timeout_seconds: float = 15.0,
    ) -> None:
        self.config = config
        self.credentials = credentials
        self._client = client
        self.timeout_seconds = timeout_seconds

    def merchant_fingerprint(self, merchant_id: str) -> str:
        merchant_id = str(merchant_id or "").strip()
        if not merchant_id:
            raise ValueError("merchant_id is required")
        return provider_account_fingerprint(
            "cash-app-pay",
            {"environment": self.config.environment, "merchant_id": merchant_id},
        )

    @staticmethod
    def payment_resource_fingerprint(payload: Mapping[str, object]) -> str:
        canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

    def _network_headers(self, method: str, path: str, body_bytes: bytes) -> dict[str, str]:
        if self.credentials is None:
            raise RuntimeError("Cash App Pay Network API credentials are not configured")
        creds = self.credentials
        authorization = f"Client {creds.client_id} {creds.key_id}"
        host = self.config.base_url.removeprefix("https://")
        headers_to_sign = (
            "accept:application/json\n"
            f"authorization:{authorization}\n"
            "content-type:application/json\n"
            f"host:{host}"
        )
        body_digest = hashlib.sha256(body_bytes).hexdigest()
        raw_signature = f"{method.upper()}\n{path}\n{headers_to_sign}\n{body_digest}"
        signature = hmac.new(
            creds.secret.encode("utf-8"),
            raw_signature.encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()
        return {
            "Accept": "application/json",
            "Authorization": authorization,
            "Content-Type": "application/json",
            "Host": host,
            "X-Region": creds.region,
            "X-Signature": f"V1 {signature}",
        }

    async def _request(
        self,
        method: str,
        path: str,
        *,
        body: Mapping[str, object] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> dict[str, Any]:
        body_bytes = (
            json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
            if body is not None
            else b""
        )
        request_headers = dict(headers or {})
        url = f"{self.config.base_url}{path}"
        if self._client is not None:
            response = await self._client.request(
                method,
                url,
                content=body_bytes if body is not None else None,
                headers=request_headers,
            )
        else:
            async with httpx.AsyncClient(timeout=self.timeout_seconds) as client:
                response = await client.request(
                    method,
                    url,
                    content=body_bytes if body is not None else None,
                    headers=request_headers,
                )
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError("Cash App Pay response is not an object")
        return payload

    async def create_customer_request(
        self,
        *,
        client_id: str,
        merchant_id: str,
        amount_cents: int,
        reference_id: str,
        redirect_url: str,
        idempotency_key: str,
        channel: str = "IN_PERSON",
    ) -> dict[str, object]:
        if amount_cents <= 0:
            raise ValueError("amount_cents must be positive")
        if not all(str(value or "").strip() for value in (
            client_id,
            merchant_id,
            reference_id,
            redirect_url,
            idempotency_key,
        )):
            raise ValueError("customer request fields must not be empty")
        path = "/customer-request/v1/requests"
        body = {
            "idempotency_key": idempotency_key,
            "request": {
                "actions": [
                    {
                        "type": "ONE_TIME_PAYMENT",
                        "scope_id": merchant_id,
                        "amount": int(amount_cents),
                        "currency": "USD",
                    }
                ],
                "channel": channel,
                "redirect_url": redirect_url,
                "reference_id": reference_id,
            },
        }
        payload = await self._request(
            "POST",
            path,
            body=body,
            headers={
                "Accept": "application/json",
                "Authorization": f"Client {client_id}",
                "Content-Type": "application/json",
            },
        )
        return {
            "provider": "cash-app-pay",
            "environment": self.config.environment,
            "merchant_fingerprint": self.merchant_fingerprint(merchant_id),
            "customer_request": payload.get("request"),
            "payment_created": False,
        }

    async def create_payment(
        self,
        *,
        merchant_id: str,
        grant_id: str,
        amount_cents: int,
        reference_id: str,
        idempotency_key: str,
        capture: bool = True,
    ) -> dict[str, object]:
        if amount_cents <= 0:
            raise ValueError("amount_cents must be positive")
        if not all(str(value or "").strip() for value in (
            merchant_id,
            grant_id,
            reference_id,
            idempotency_key,
        )):
            raise ValueError("payment fields must not be empty")
        path = "/network/v1/payments"
        body = {
            "idempotency_key": idempotency_key,
            "payment": {
                "amount": int(amount_cents),
                "currency": "USD",
                "merchant_id": merchant_id,
                "grant_id": grant_id,
                "reference_id": reference_id,
                "capture": bool(capture),
            },
        }
        body_bytes = json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")
        payload = await self._request(
            "POST",
            path,
            body=body,
            headers=self._network_headers("POST", path, body_bytes),
        )
        return {
            "provider": "cash-app-pay",
            "environment": self.config.environment,
            "merchant_fingerprint": self.merchant_fingerprint(merchant_id),
            "resource_fingerprint": self.payment_resource_fingerprint(body),
            "payment": payload.get("payment"),
            "payment_created": True,
        }

    async def retrieve_payment(self, payment_id: str) -> dict[str, object]:
        payment_id = str(payment_id or "").strip()
        if not payment_id:
            raise ValueError("payment_id is required")
        path = f"/network/v1/payments/{payment_id}"
        payload = await self._request(
            "GET",
            path,
            headers=self._network_headers("GET", path, b""),
        )
        return {
            "provider": "cash-app-pay",
            "environment": self.config.environment,
            "payment": payload.get("payment"),
            "execution_authorized": False,
        }
