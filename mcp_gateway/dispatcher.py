from __future__ import annotations

import hashlib
import json
from typing import Mapping

from integrations.cash_app_pay import CashAppPayClient
from integrations.solana_rpc import SolanaRpcClient, transaction_fingerprint
from mcp_gateway.action_ledger import ProductActionLedger
from mcp_gateway.authority import validate_product_action_authority
from mcp_gateway.continuity import validate_continuity_cookie
from mcp_gateway.providers import get_provider_manifest, provider_manifests


def _resource_fingerprint(payload: Mapping[str, object]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class ProviderDispatcher:
    """MCP-facing provider router with continuity, authority, and replay gates.

    Secrets live inside provider clients. MCP commands contain only public/provider
    references, fingerprints, customer grants or already-signed transactions, and
    authenticated authority/continuity receipts.
    """

    def __init__(
        self,
        *,
        continuity_keys: Mapping[str, object],
        authority_keys: Mapping[str, object],
        ledger: ProductActionLedger,
        solana: SolanaRpcClient | None = None,
        cash_app_pay: CashAppPayClient | None = None,
    ) -> None:
        self.continuity_keys = dict(continuity_keys)
        self.authority_keys = dict(authority_keys)
        self.ledger = ledger
        self.solana = solana
        self.cash_app_pay = cash_app_pay

    def capabilities(self) -> dict[str, object]:
        return {
            "event": "mcp_provider_capabilities",
            "providers": provider_manifests(),
            "fingerprints_are_credentials": False,
            "continuity_cookies_authorize": False,
            "credentials_in_mcp_payloads": False,
            "money_moving_actions_require_product_authority": True,
        }

    async def dispatch(self, command: Mapping[str, object]) -> dict[str, object]:
        provider = str(command.get("provider", "")).strip().lower()
        environment = str(command.get("environment", "")).strip().lower()
        action = str(command.get("action", "")).strip().lower()
        payload = command.get("payload")
        if not provider or not environment or not action or not isinstance(payload, Mapping):
            return self._blocked("INVALID_COMMAND", "provider, environment, action, and payload are required")

        try:
            manifest = get_provider_manifest(provider)
        except ValueError as exc:
            return self._blocked("UNSUPPORTED_PROVIDER", str(exc))
        if environment not in manifest.environments:
            return self._blocked("ENVIRONMENT_CONFLICT", "provider does not support requested environment")
        if action not in manifest.actions:
            return self._blocked("ACTION_CONFLICT", "provider does not support requested action")
        if provider == "github-control":
            return self._blocked(
                "CONTROL_PLANE_ONLY",
                "GitHub is represented as an MCP/control-plane caller surface, not a dispatched money provider",
            )

        try:
            account_fingerprint, resource_fingerprint, requested_amount, currency = self._scope(
                provider,
                action,
                payload,
            )
        except (KeyError, TypeError, ValueError) as exc:
            return self._blocked("INVALID_SCOPE", str(exc))

        cookie = command.get("continuity_cookie")
        if not isinstance(cookie, Mapping):
            return self._blocked("MISSING_CONTINUITY", "continuity_cookie is required")
        continuity = validate_continuity_cookie(cookie, trusted_keys=self.continuity_keys)
        if not continuity.accepted:
            return self._blocked(continuity.classification, continuity.reason)
        if (
            continuity.provider != provider
            or continuity.environment != environment
            or continuity.provider_subject_fingerprint != account_fingerprint
        ):
            return self._blocked(
                "CONTINUITY_CONFLICT",
                "continuity provider/environment/account fingerprint does not match command",
            )

        money_moving = action in manifest.money_moving_actions
        authority = command.get("authority_receipt")
        authority_receipt_id: str | None = None
        idempotency_key = str(command.get("idempotency_key", "")).strip()
        if money_moving:
            if not isinstance(authority, Mapping):
                return self._blocked("MISSING_AUTHORITY", "money-moving action requires product authority")
            if not idempotency_key:
                return self._blocked("MISSING_IDEMPOTENCY", "money-moving action requires idempotency_key")
            authority_fingerprint = str(authority.get("fingerprint", "")).lower()
            cookie_authority = str(cookie.get("authority_fingerprint") or "").lower()
            if not authority_fingerprint or cookie_authority != authority_fingerprint:
                return self._blocked(
                    "AUTHORITY_COOKIE_CONFLICT",
                    "continuity cookie is not bound to the supplied product authority",
                )
            decision = validate_product_action_authority(
                authority,
                trusted_keys=self.authority_keys,
                provider=provider,
                environment=environment,
                account_fingerprint=account_fingerprint,
                action=action,
                resource_fingerprint=resource_fingerprint,
                idempotency_key=idempotency_key,
                requested_amount=requested_amount,
                currency=currency,
            )
            if not decision.accepted:
                return self._blocked(decision.classification, decision.reason)
            authority_receipt_id = str(decision.receipt_id)
            reserved, reason = self.ledger.reserve(
                provider=provider,
                receipt_id=authority_receipt_id,
                idempotency_key=idempotency_key,
                resource_fingerprint=resource_fingerprint,
            )
            if not reserved:
                return self._blocked("AUTHORITY_STATE_BLOCKED", reason)
            active, reason = self.ledger.reservation_is_active(
                provider=provider,
                receipt_id=authority_receipt_id,
                idempotency_key=idempotency_key,
                resource_fingerprint=resource_fingerprint,
            )
            if not active:
                self.ledger.classify(provider, idempotency_key, "blocked")
                return self._blocked("AUTHORITY_STATE_CHANGED", reason)

        try:
            result = await self._call(provider, action, payload)
        except Exception as exc:
            if money_moving:
                try:
                    self.ledger.classify(provider, idempotency_key, "reconcile_required")
                except Exception:
                    pass
                return {
                    **self._blocked(
                        "RECONCILE_REQUIRED",
                        f"provider outcome is unknown after dispatch error: {type(exc).__name__}: {exc}",
                    ),
                    "reconciliation_required": True,
                    "resource_fingerprint": resource_fingerprint,
                    "authority_receipt_id": authority_receipt_id,
                }
            return self._blocked("PROVIDER_ERROR", f"provider request failed: {type(exc).__name__}: {exc}")

        if money_moving:
            try:
                self.ledger.classify(provider, idempotency_key, "completed")
                ledger_persisted = True
                ledger_error = None
            except Exception as exc:
                ledger_persisted = False
                ledger_error = f"{type(exc).__name__}: {exc}"
            return {
                "ok": True,
                "classification": "PROVIDER_ACTION_EXECUTED",
                "provider": provider,
                "environment": environment,
                "action": action,
                "resource_fingerprint": resource_fingerprint,
                "account_fingerprint": account_fingerprint,
                "authority_receipt_id": authority_receipt_id,
                "idempotency_key": idempotency_key,
                "provider_result": result,
                "reconciliation_required": not ledger_persisted,
                "ledger_persisted": ledger_persisted,
                "ledger_error": ledger_error,
            }

        return {
            "ok": True,
            "classification": "PROVIDER_READ_EXECUTED",
            "provider": provider,
            "environment": environment,
            "action": action,
            "resource_fingerprint": resource_fingerprint,
            "account_fingerprint": account_fingerprint,
            "provider_result": result,
            "execution_authorized": False,
        }

    def _scope(
        self,
        provider: str,
        action: str,
        payload: Mapping[str, object],
    ) -> tuple[str, str, float | None, str | None]:
        if provider == "solana-rpc":
            if self.solana is None:
                raise ValueError("Solana provider is not configured")
            public_key = str(payload.get("public_key", "")).strip()
            if not public_key:
                raise ValueError("Solana payload requires public_key")
            account_fingerprint = self.solana.account_fingerprint(public_key)
            if action in {"simulate-signed-transaction", "broadcast-signed-transaction"}:
                resource = transaction_fingerprint(str(payload.get("transaction_base64", "")))
            else:
                resource = _resource_fingerprint(payload)
            return account_fingerprint, resource, None, None

        if provider == "cash-app-pay":
            if self.cash_app_pay is None:
                raise ValueError("Cash App Pay provider is not configured")
            merchant_id = str(payload.get("merchant_id", "")).strip()
            if not merchant_id:
                raise ValueError("Cash App Pay payload requires merchant_id")
            account_fingerprint = self.cash_app_pay.merchant_fingerprint(merchant_id)
            if action == "create-payment":
                body = self._cash_payment_body(payload)
                return (
                    account_fingerprint,
                    self.cash_app_pay.payment_resource_fingerprint(body),
                    int(payload["amount_cents"]) / 100.0,
                    "USD",
                )
            return account_fingerprint, _resource_fingerprint(payload), None, None

        raise ValueError(f"no scope resolver exists for provider {provider}")

    @staticmethod
    def _cash_payment_body(payload: Mapping[str, object]) -> dict[str, object]:
        return {
            "idempotency_key": str(payload["idempotency_key"]),
            "payment": {
                "amount": int(payload["amount_cents"]),
                "currency": "USD",
                "merchant_id": str(payload["merchant_id"]),
                "grant_id": str(payload["grant_id"]),
                "reference_id": str(payload["reference_id"]),
                "capture": bool(payload.get("capture", True)),
            },
        }

    async def _call(
        self,
        provider: str,
        action: str,
        payload: Mapping[str, object],
    ) -> dict[str, object]:
        if provider == "solana-rpc":
            assert self.solana is not None
            if action == "get-balance":
                return await self.solana.get_balance(str(payload["public_key"]))
            if action == "simulate-signed-transaction":
                return await self.solana.simulate_signed_transaction(str(payload["transaction_base64"]))
            if action == "broadcast-signed-transaction":
                return await self.solana.broadcast_signed_transaction(str(payload["transaction_base64"]))
            if action == "get-signature-status":
                return await self.solana.get_signature_status(str(payload["signature"]))

        if provider == "cash-app-pay":
            assert self.cash_app_pay is not None
            if action == "create-customer-request":
                return await self.cash_app_pay.create_customer_request(
                    client_id=str(payload["client_id"]),
                    merchant_id=str(payload["merchant_id"]),
                    amount_cents=int(payload["amount_cents"]),
                    reference_id=str(payload["reference_id"]),
                    redirect_url=str(payload["redirect_url"]),
                    idempotency_key=str(payload["idempotency_key"]),
                    channel=str(payload.get("channel", "IN_PERSON")),
                )
            if action == "create-payment":
                return await self.cash_app_pay.create_payment(
                    merchant_id=str(payload["merchant_id"]),
                    grant_id=str(payload["grant_id"]),
                    amount_cents=int(payload["amount_cents"]),
                    reference_id=str(payload["reference_id"]),
                    idempotency_key=str(payload["idempotency_key"]),
                    capture=bool(payload.get("capture", True)),
                )
            if action == "retrieve-payment":
                return await self.cash_app_pay.retrieve_payment(str(payload["payment_id"]))

        raise ValueError(f"unsupported provider action: {provider}/{action}")

    @staticmethod
    def _blocked(classification: str, reason: str) -> dict[str, object]:
        return {
            "ok": False,
            "classification": classification,
            "reason": reason,
            "provider_action_executed": False,
        }
