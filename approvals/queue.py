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


@dataclass
class ApprovalRequest:
    proposal_id: str
    order: Order
    evaluation: dict
    status: ApprovalStatus = ApprovalStatus.PENDING
    reason: Optional[str] = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    approved_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    order_id: Optional[str] = None


class ApprovalQueue:
    """Human-in-the-loop gate. Nothing executes without passing through here."""

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
        req.reason = reason
        return True

    def reject(self, proposal_id: str, reason: str) -> bool:
        req = self.get(proposal_id)
        if not req:
            return False
        req.status = ApprovalStatus.REJECTED
        req.reason = reason
        return True

    def mark_executed(self, proposal_id: str, order_id: str | None = None) -> bool:
        req = self.get(proposal_id)
        if not req:
            return False
        req.status = ApprovalStatus.EXECUTED
        req.executed_at = datetime.now(timezone.utc)
        req.order_id = order_id
        return True
