import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import List, Optional

from broker.base import Order


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTED = "executed"


def approval_fingerprint(order: Order, evaluation: dict) -> str:
    """Bind approval to the exact simulated intent and reviewed evidence."""
    payload = {
        "order": {
            "symbol": order.symbol,
            "qty": order.qty,
            "side": order.side,
            "asset_class": order.asset_class,
        },
        "evaluation": evaluation,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass
class ApprovalRequest:
    proposal_id: str
    order: Order
    evaluation: dict
    status: ApprovalStatus = ApprovalStatus.PENDING
    reason: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: Optional[datetime] = None
    approved_fingerprint: Optional[str] = None
    executed_at: Optional[datetime] = None
    order_id: Optional[str] = None


class ApprovalQueue:
    """Human-in-the-loop gate for simulation actions."""

    def __init__(self):
        self.queue: List[ApprovalRequest] = []
        self._counter = 0

    def add(self, order: Order, evaluation: dict) -> str:
        self._counter += 1
        proposal_id = f"PROP-{self._counter}"
        self.queue.append(ApprovalRequest(proposal_id, order, evaluation))
        return proposal_id

    def get(self, proposal_id: str) -> Optional[ApprovalRequest]:
        return next((r for r in self.queue if r.proposal_id == proposal_id), None)

    def get_pending(self) -> List[ApprovalRequest]:
        return [r for r in self.queue if r.status is ApprovalStatus.PENDING]

    def approve(self, proposal_id: str, reason: str | None = None) -> bool:
        req = self.get(proposal_id)
        if not req or req.status is not ApprovalStatus.PENDING:
            return False
        req.status = ApprovalStatus.APPROVED
        req.approved_at = datetime.now(timezone.utc)
        req.approved_fingerprint = approval_fingerprint(req.order, req.evaluation)
        req.reason = reason
        return True

    def approval_is_intact(self, proposal_id: str) -> bool:
        req = self.get(proposal_id)
        if not req or not req.approved_fingerprint:
            return False
        return req.approved_fingerprint == approval_fingerprint(req.order, req.evaluation)

    def reject(self, proposal_id: str, reason: str) -> bool:
        req = self.get(proposal_id)
        if not req or req.status is not ApprovalStatus.PENDING:
            return False
        req.status = ApprovalStatus.REJECTED
        req.reason = reason
        return True

    def mark_executed(self, proposal_id: str, order_id: str | None = None) -> bool:
        req = self.get(proposal_id)
        if not req or req.status is not ApprovalStatus.APPROVED:
            return False
        req.status = ApprovalStatus.EXECUTED
        req.executed_at = datetime.now(timezone.utc)
        req.order_id = order_id
        return True
