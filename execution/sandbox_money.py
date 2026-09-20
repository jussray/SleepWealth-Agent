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

        if not self.execution_manager.broker.is_paper_only():
            return await self._block(
                proposal_id,
                "sandbox authority refuses a broker that is not provably paper-only",
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

        result = await self.execution_manager.execute_approved(proposal_id)
        if result.get("reconciliation_required") is True:
            ledger_state = "reconcile_required"
        elif "error" in result:
            ledger_state = "blocked"
        else:
            ledger_state = "completed"
        self.ledger.classify(idempotency_key, ledger_state)

        await self.execution_manager.audit_logger.log(
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
        return {
            **result,
            "sandbox_authority": "CONSUMED",
            "sandbox_authority_receipt_id": receipt_id,
            "sandbox_authority_state": ledger_state,
            "sandbox_only": True,
            "live_execution_authorized": False,
        }

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
