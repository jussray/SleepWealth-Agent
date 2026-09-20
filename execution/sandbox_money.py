from __future__ import annotations

import math
from datetime import datetime
from typing import Mapping

from approvals.queue import ApprovalQueue, ApprovalStatus
from authority.money_movement import (
    SandboxAuthorityLedger,
    SandboxMoneyAction,
    validate_sandbox_money_authority,
)
from broker.provider_identity import provider_account_fingerprint
from execution.executor import ExecutionManager


class SandboxMoneyExecutionManager:
    """Compose signed money authority onto the existing paper execution path.

    The underlying ExecutionManager remains responsible for fresh-market checks,
    risk gates, broker submission, approval-state transitions, audit logging, and
    reconciliation. This wrapper adds exact account/order scope, short-lived signed
    authority, revocation, kill-switch, and replay/idempotency controls.

    It refuses any broker that is not provably paper-only. Nothing in this class
    can submit a real-money order, fund/transfer assets, or sign a wallet message.
    """

    def __init__(
        self,
        execution_manager: ExecutionManager,
        approval_queue: ApprovalQueue,
        *,
        subject: str,
        provider: str,
        account_fingerprint: str,
        trusted_authority_keys: Mapping[str, object],
        ledger: SandboxAuthorityLedger,
    ) -> None:
        if not subject.strip() or not provider.strip():
            raise ValueError("sandbox subject and provider are required")
        if len(account_fingerprint) != 64:
            raise ValueError("sandbox account fingerprint must be a SHA-256 value")
        self.execution_manager = execution_manager
        self.approval_queue = approval_queue
        self.subject = subject
        self.provider = provider.strip().lower()
        self.account_fingerprint = account_fingerprint.lower()
        self.trusted_authority_keys = trusted_authority_keys
        self.ledger = ledger

    async def execute_authorized(
        self,
        receipt: Mapping[str, object] | None,
        *,
        evaluated_at: datetime | None = None,
    ) -> dict[str, object]:
        decision = validate_sandbox_money_authority(
            receipt,
            self.trusted_authority_keys,
            evaluated_at=evaluated_at,
        )
        if not decision.accepted:
            return await self._block(
                decision.proposal_id or "unknown",
                decision.reason,
                classification=decision.classification,
                receipt_id=decision.receipt_id,
            )

        assert receipt is not None
        proposal_id = str(receipt["proposal_id"])
        receipt_id = str(receipt["receipt_id"])
        idempotency_key = str(receipt["idempotency_key"])

        paper_ok, paper_reason = self._paper_broker_is_proved()
        if not paper_ok:
            return await self._block(
                proposal_id,
                paper_reason,
                classification="LIVE_BROKER_REFUSED",
                receipt_id=receipt_id,
            )
        if str(receipt.get("subject", "")) != self.subject:
            return await self._block(
                proposal_id,
                "sandbox authority subject does not match this runtime",
                classification="SUBJECT_CONFLICT",
                receipt_id=receipt_id,
            )
        if str(receipt.get("provider", "")).lower() != self.provider:
            return await self._block(
                proposal_id,
                "sandbox authority provider does not match this runtime",
                classification="PROVIDER_CONFLICT",
                receipt_id=receipt_id,
            )
        if str(receipt.get("account_fingerprint", "")).lower() != self.account_fingerprint:
            return await self._block(
                proposal_id,
                "sandbox authority account fingerprint does not match this runtime",
                classification="ACCOUNT_CONFLICT",
                receipt_id=receipt_id,
            )

        proposal = self.approval_queue.get(proposal_id)
        if proposal is None:
            return await self._block(
                proposal_id,
                "approved proposal does not exist",
                classification="PROPOSAL_MISSING",
                receipt_id=receipt_id,
            )
        if proposal.status is not ApprovalStatus.APPROVED:
            return await self._block(
                proposal_id,
                f"proposal status is {proposal.status.value}, not approved",
                classification="APPROVAL_NOT_CURRENT",
                receipt_id=receipt_id,
            )
        if not self.approval_queue.approval_is_intact(proposal_id):
            return await self._block(
                proposal_id,
                "human approval fingerprint is no longer intact",
                classification="APPROVAL_STALE",
                receipt_id=receipt_id,
            )
        if str(receipt.get("approval_fingerprint", "")).lower() != str(
            proposal.approved_fingerprint or ""
        ).lower():
            return await self._block(
                proposal_id,
                "authority receipt does not bind the current human approval",
                classification="APPROVAL_CONFLICT",
                receipt_id=receipt_id,
            )

        order = proposal.order
        order_matches = (
            receipt.get("action") == SandboxMoneyAction.ORDER_SUBMIT.value
            and str(receipt.get("symbol", "")).upper() == order.symbol.upper()
            and str(receipt.get("asset_class", "")) == order.asset_class
            and str(receipt.get("side", "")).lower() == order.side.lower()
            and self._same_number(receipt.get("quantity"), order.qty)
        )
        if not order_matches:
            return await self._block(
                proposal_id,
                "authority receipt order scope does not match the approved proposal",
                classification="ORDER_SCOPE_CONFLICT",
                receipt_id=receipt_id,
            )

        reviewed_ceiling = proposal.evaluation.get("ceiling")
        if not self._same_number(receipt.get("max_notional"), reviewed_ceiling):
            return await self._block(
                proposal_id,
                "authority notional ceiling does not match the human-reviewed ceiling",
                classification="CEILING_CONFLICT",
                receipt_id=receipt_id,
            )

        if await self.execution_manager.risk_gates.kill_switch():
            return await self._block(
                proposal_id,
                "dynamic risk kill switch is engaged",
                classification="RISK_KILL_SWITCH",
                receipt_id=receipt_id,
            )

        reserved, reason = self.ledger.reserve(receipt_id, idempotency_key)
        if not reserved:
            return await self._block(
                proposal_id,
                reason,
                classification="AUTHORITY_STATE_BLOCKED",
                receipt_id=receipt_id,
            )

        try:
            await self.execution_manager.audit_logger.log(
                {
                    "event": "sandbox_money_authority_reserved",
                    "proposal_id": proposal_id,
                    "receipt_id": receipt_id,
                    "authority_fingerprint": receipt.get("fingerprint"),
                    "provider": self.provider,
                    "account_fingerprint": self.account_fingerprint,
                    "idempotency_key": idempotency_key,
                    "sandbox_only": True,
                    "live_execution_authorized": False,
                }
            )
        except Exception as exc:
            state_error = self._best_effort_classify(idempotency_key, "blocked")
            return {
                "error": f"sandbox authority reservation audit failed: {type(exc).__name__}: {exc}",
                "classification": "AUTHORITY_AUDIT_BLOCKED",
                "sandbox_authority_state": "blocked",
                "sandbox_authority_state_error": state_error,
                "sandbox_only": True,
                "live_execution_authorized": False,
            }

        active, active_reason = self._reserved_authority_still_active(
            receipt_id,
            idempotency_key,
        )
        if not active:
            state_error = self._best_effort_classify(idempotency_key, "blocked")
            result = await self._block(
                proposal_id,
                active_reason,
                classification="AUTHORITY_STATE_CHANGED",
                receipt_id=receipt_id,
            )
            if state_error:
                result["sandbox_authority_state_error"] = state_error
            return result

        result = await self.execution_manager.execute_approved(proposal_id)
        if result.get("reconciliation_required") is True:
            ledger_state = "reconcile_required"
        elif "error" in result:
            ledger_state = "blocked"
        else:
            ledger_state = "completed"

        try:
            self.ledger.classify(idempotency_key, ledger_state)
        except Exception as exc:
            state_error = f"{type(exc).__name__}: {exc}"
            audit_error = None
            try:
                await self.execution_manager.audit_logger.log(
                    {
                        "event": "sandbox_money_authority_reconcile_required",
                        "proposal_id": proposal_id,
                        "receipt_id": receipt_id,
                        "idempotency_key": idempotency_key,
                        "reason": "execution result exists but authority ledger state could not persist",
                        "authority_state_error": state_error,
                        "execution_order_id": result.get("order_id"),
                        "sandbox_only": True,
                        "live_execution_authorized": False,
                    }
                )
            except Exception as audit_exc:
                audit_error = f"{type(audit_exc).__name__}: {audit_exc}"
            return {
                **result,
                "sandbox_authority": "CONSUMED_STATE_DEGRADED",
                "sandbox_authority_receipt_id": receipt_id,
                "sandbox_authority_state": "reconcile_required",
                "sandbox_authority_ledger_persisted": False,
                "sandbox_authority_state_error": state_error,
                "sandbox_authority_audit_persisted": audit_error is None,
                "sandbox_authority_audit_error": audit_error,
                "reconciliation_required": True,
                "sandbox_only": True,
                "live_execution_authorized": False,
            }

        try:
            authority_audit_hash = await self.execution_manager.audit_logger.log(
                {
                    "event": "sandbox_money_authority_consumed",
                    "proposal_id": proposal_id,
                    "receipt_id": receipt_id,
                    "idempotency_key": idempotency_key,
                    "authority_state": ledger_state,
                    "execution_order_id": result.get("order_id"),
                    "reconciliation_required": result.get("reconciliation_required", False),
                    "sandbox_only": True,
                    "live_execution_authorized": False,
                }
            )
        except Exception as exc:
            return {
                **result,
                "sandbox_authority": "CONSUMED_AUDIT_DEGRADED",
                "sandbox_authority_receipt_id": receipt_id,
                "sandbox_authority_state": ledger_state,
                "sandbox_authority_ledger_persisted": True,
                "sandbox_authority_audit_persisted": False,
                "sandbox_authority_audit_error": f"{type(exc).__name__}: {exc}",
                "sandbox_only": True,
                "live_execution_authorized": False,
            }

        return {
            **result,
            "sandbox_authority": "CONSUMED",
            "sandbox_authority_receipt_id": receipt_id,
            "sandbox_authority_state": ledger_state,
            "sandbox_authority_ledger_persisted": True,
            "sandbox_authority_audit_persisted": True,
            "sandbox_authority_audit_hash": authority_audit_hash,
            "sandbox_only": True,
            "live_execution_authorized": False,
        }

    def _paper_broker_is_proved(self) -> tuple[bool, str]:
        broker = self.execution_manager.broker
        try:
            paper_only = broker.is_paper_only()
            proof = broker.paper_proof()
        except Exception as exc:
            return False, f"paper broker proof unavailable: {type(exc).__name__}: {exc}"
        if paper_only is not True:
            return False, "sandbox authority refuses a broker that is not paper-only"
        if not isinstance(proof, dict):
            return False, "sandbox authority requires structured paper broker proof"
        if proof.get("configured_paper") is not True or proof.get("provably_paper") is not True:
            return False, "sandbox authority requires configured and provable paper broker evidence"
        accounts = proof.get("managed_accounts")
        if not isinstance(accounts, list) or len(accounts) != 1 or not str(accounts[0]).strip():
            return False, "sandbox authority requires exactly one proved paper account"
        try:
            observed_account_fingerprint = provider_account_fingerprint(
                self.provider,
                {"account_id": accounts[0]},
            )
        except ValueError as exc:
            return False, f"paper account identity is invalid: {exc}"
        if observed_account_fingerprint != self.account_fingerprint:
            return False, "sandbox runtime account fingerprint does not match broker paper proof"
        return True, "paper broker and account proof verified"

    def _reserved_authority_still_active(
        self,
        receipt_id: str,
        idempotency_key: str,
    ) -> tuple[bool, str]:
        state = self.ledger.snapshot()
        if state.get("kill_switch") is True:
            return False, "sandbox authority kill switch changed after reservation"
        revoked = state.get("revoked_receipts")
        if isinstance(revoked, list) and receipt_id in {str(value) for value in revoked}:
            return False, "sandbox authority receipt was revoked after reservation"
        idempotency = state.get("idempotency")
        if not isinstance(idempotency, dict):
            return False, "sandbox authority idempotency state is unavailable"
        reservation = idempotency.get(idempotency_key)
        if not isinstance(reservation, dict):
            return False, "sandbox authority reservation disappeared"
        if reservation.get("receipt_id") != receipt_id:
            return False, "sandbox authority reservation changed receipt identity"
        if reservation.get("state") != "reserved":
            return False, "sandbox authority reservation is not executable"
        return True, "reserved authority remains active"

    def _best_effort_classify(self, idempotency_key: str, state: str) -> str | None:
        try:
            self.ledger.classify(idempotency_key, state)
        except Exception as exc:
            return f"{type(exc).__name__}: {exc}"
        return None

    async def _block(
        self,
        proposal_id: str,
        reason: str,
        *,
        classification: str,
        receipt_id: str | None,
    ) -> dict[str, object]:
        await self.execution_manager.audit_logger.log(
            {
                "event": "sandbox_money_authority_blocked",
                "proposal_id": proposal_id,
                "receipt_id": receipt_id,
                "classification": classification,
                "reason": reason,
                "sandbox_only": True,
                "live_execution_authorized": False,
            }
        )
        return {
            "error": reason,
            "classification": classification,
            "sandbox_only": True,
            "live_execution_authorized": False,
        }

    @staticmethod
    def _same_number(left: object, right: object) -> bool:
        if isinstance(left, bool) or isinstance(right, bool):
            return False
        try:
            left_number = float(left)
            right_number = float(right)
        except (TypeError, ValueError):
            return False
        return (
            math.isfinite(left_number)
            and math.isfinite(right_number)
            and left_number == right_number
        )
