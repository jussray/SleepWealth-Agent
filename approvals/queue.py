import hashlib
import json
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import List, Optional

from broker.base import Order

try:
    import fcntl
except ImportError:  # pragma: no cover - persistent mode fails closed below
    fcntl = None


STATE_VERSION = 1


class ApprovalStatus(str, Enum):
    PENDING = "pending"
    APPROVED = "approved"
    EXECUTING = "executing"
    REJECTED = "rejected"
    STALE = "stale"
    RECONCILE_REQUIRED = "reconcile_required"
    EXECUTED = "executed"


def approval_fingerprint(order: Order, evaluation: dict) -> str:
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


def _parse_datetime(value: object) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _json_copy(value):
    return json.loads(json.dumps(value, default=str))


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
    approval_session_id: Optional[str] = None
    execution_started_at: Optional[datetime] = None
    execution_session_id: Optional[str] = None
    executed_at: Optional[datetime] = None
    order_id: Optional[str] = None


class ApprovalQueue:
    """Human-in-the-loop gate for simulated actions.

    When state_path is set, proposal state is atomically persisted. Approval and
    in-flight execution are session-bound so restarts fail closed instead of
    replaying unfinished work.
    """

    def __init__(self, state_path: str | None = None, session_id: str | None = None):
        self.queue: List[ApprovalRequest] = []
        self._counter = 0
        self.state_path = Path(state_path) if state_path else None
        self.session_id = session_id or uuid.uuid4().hex

        if self.state_path is not None:
            if fcntl is None:
                raise RuntimeError("persistent approval state requires POSIX file locking")
            if self.state_path.parent != Path("."):
                self.state_path.parent.mkdir(parents=True, exist_ok=True)
            with self._locked_state():
                self._load_locked()
                if self._recover_foreign_inflight_locked():
                    self._persist_locked()

    @contextmanager
    def _locked_state(self):
        if self.state_path is None:
            yield
            return
        lock_path = self.state_path.with_name(self.state_path.name + ".lock")
        with open(lock_path, "a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _serialize_request(request: ApprovalRequest) -> dict:
        return {
            "proposal_id": request.proposal_id,
            "order": {
                "symbol": request.order.symbol,
                "qty": request.order.qty,
                "side": request.order.side,
                "asset_class": request.order.asset_class,
            },
            "evaluation": _json_copy(request.evaluation),
            "status": request.status.value,
            "reason": request.reason,
            "created_at": request.created_at.isoformat(),
            "approved_at": request.approved_at.isoformat() if request.approved_at else None,
            "approved_fingerprint": request.approved_fingerprint,
            "approval_session_id": request.approval_session_id,
            "execution_started_at": (
                request.execution_started_at.isoformat()
                if request.execution_started_at
                else None
            ),
            "execution_session_id": request.execution_session_id,
            "executed_at": request.executed_at.isoformat() if request.executed_at else None,
            "order_id": request.order_id,
        }

    @staticmethod
    def _deserialize_request(payload: dict) -> ApprovalRequest:
        order = payload.get("order") or {}
        return ApprovalRequest(
            proposal_id=str(payload["proposal_id"]),
            order=Order(
                str(order["symbol"]),
                float(order["qty"]),
                str(order["side"]),
                str(order.get("asset_class", "stocks")),
            ),
            evaluation=_json_copy(payload.get("evaluation") or {}),
            status=ApprovalStatus(payload.get("status", ApprovalStatus.PENDING.value)),
            reason=payload.get("reason"),
            created_at=_parse_datetime(payload.get("created_at")) or datetime.now(timezone.utc),
            approved_at=_parse_datetime(payload.get("approved_at")),
            approved_fingerprint=payload.get("approved_fingerprint"),
            approval_session_id=payload.get("approval_session_id"),
            execution_started_at=_parse_datetime(payload.get("execution_started_at")),
            execution_session_id=payload.get("execution_session_id"),
            executed_at=_parse_datetime(payload.get("executed_at")),
            order_id=payload.get("order_id"),
        )

    def _load_locked(self) -> None:
        if self.state_path is None or not self.state_path.exists():
            self.queue = []
            self._counter = 0
            return
        try:
            payload = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"approval state is unreadable: {exc}") from exc
        if not isinstance(payload, dict) or payload.get("version") != STATE_VERSION:
            raise RuntimeError("approval state version is missing or unsupported")
        requests = payload.get("requests")
        counter = payload.get("counter")
        if not isinstance(requests, list) or not isinstance(counter, int) or counter < 0:
            raise RuntimeError("approval state shape is invalid")
        try:
            self.queue = [self._deserialize_request(item) for item in requests if isinstance(item, dict)]
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(f"approval state request is invalid: {exc}") from exc
        if len(self.queue) != len(requests):
            raise RuntimeError("approval state contains a non-object request")
        self._counter = counter

    def _persist_locked(self) -> None:
        if self.state_path is None:
            return
        payload = {
            "version": STATE_VERSION,
            "counter": self._counter,
            "requests": [self._serialize_request(request) for request in self.queue],
        }
        encoded = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        temp_path = self.state_path.with_name(
            f".{self.state_path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp"
        )
        try:
            with open(temp_path, "wb") as temp_file:
                temp_file.write(encoded)
                temp_file.flush()
                os.fsync(temp_file.fileno())
            os.replace(temp_path, self.state_path)
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def _recover_foreign_inflight_locked(self) -> bool:
        changed = False
        for request in self.queue:
            if (
                request.status is ApprovalStatus.APPROVED
                and request.approval_session_id != self.session_id
            ):
                request.status = ApprovalStatus.STALE
                request.reason = "approval invalidated by process/session restart"
                request.approved_fingerprint = None
                request.approval_session_id = None
                changed = True
            elif (
                request.status is ApprovalStatus.EXECUTING
                and request.execution_session_id != self.session_id
            ):
                request.status = ApprovalStatus.RECONCILE_REQUIRED
                request.reason = (
                    "execution was in flight across process/session restart; "
                    "manual reconciliation required"
                )
                changed = True
        return changed

    def _refresh_locked(self) -> None:
        if self.state_path is not None:
            self._load_locked()

    def _find(self, proposal_id: str) -> Optional[ApprovalRequest]:
        return next((request for request in self.queue if request.proposal_id == proposal_id), None)

    def add(self, order: Order, evaluation: dict) -> str:
        with self._locked_state():
            self._refresh_locked()
            self._counter += 1
            proposal_id = f"PROP-{self._counter}"
            self.queue.append(ApprovalRequest(proposal_id, order, _json_copy(evaluation)))
            self._persist_locked()
            return proposal_id

    def get(self, proposal_id: str) -> Optional[ApprovalRequest]:
        with self._locked_state():
            self._refresh_locked()
            return self._find(proposal_id)

    def get_pending(self) -> List[ApprovalRequest]:
        with self._locked_state():
            self._refresh_locked()
            return [request for request in self.queue if request.status is ApprovalStatus.PENDING]

    def approve(self, proposal_id: str, reason: str | None = None) -> bool:
        with self._locked_state():
            self._refresh_locked()
            request = self._find(proposal_id)
            if not request or request.status is not ApprovalStatus.PENDING:
                return False
            request.status = ApprovalStatus.APPROVED
            request.approved_at = datetime.now(timezone.utc)
            request.approved_fingerprint = approval_fingerprint(request.order, request.evaluation)
            request.approval_session_id = self.session_id
            request.reason = reason
            self._persist_locked()
            return True

    def approval_is_intact(self, proposal_id: str) -> bool:
        with self._locked_state():
            self._refresh_locked()
            request = self._find(proposal_id)
            if not request or not request.approved_fingerprint:
                return False
            if (
                request.status is ApprovalStatus.APPROVED
                and request.approval_session_id != self.session_id
            ):
                return False
            return request.approved_fingerprint == approval_fingerprint(
                request.order, request.evaluation
            )

    def reject(self, proposal_id: str, reason: str) -> bool:
        with self._locked_state():
            self._refresh_locked()
            request = self._find(proposal_id)
            if not request or request.status is not ApprovalStatus.PENDING:
                return False
            request.status = ApprovalStatus.REJECTED
            request.reason = reason
            self._persist_locked()
            return True

    def begin_execution(self, proposal_id: str) -> bool:
        with self._locked_state():
            self._refresh_locked()
            request = self._find(proposal_id)
            if not request or request.status is not ApprovalStatus.APPROVED:
                return False
            if request.approval_session_id != self.session_id:
                return False
            if request.approved_fingerprint != approval_fingerprint(
                request.order, request.evaluation
            ):
                return False
            request.status = ApprovalStatus.EXECUTING
            request.execution_started_at = datetime.now(timezone.utc)
            request.execution_session_id = self.session_id
            self._persist_locked()
            return True

    def mark_execution_rejected(self, proposal_id: str, reason: str) -> bool:
        with self._locked_state():
            self._refresh_locked()
            request = self._find(proposal_id)
            if not request or request.status is not ApprovalStatus.EXECUTING:
                return False
            if request.execution_session_id != self.session_id:
                return False
            request.status = ApprovalStatus.REJECTED
            request.reason = reason
            self._persist_locked()
            return True

    def mark_reconcile_required(self, proposal_id: str, reason: str) -> bool:
        with self._locked_state():
            self._refresh_locked()
            request = self._find(proposal_id)
            if not request or request.status is not ApprovalStatus.EXECUTING:
                return False
            request.status = ApprovalStatus.RECONCILE_REQUIRED
            request.reason = reason
            self._persist_locked()
            return True

    def mark_executed(self, proposal_id: str, order_id: str | None = None) -> bool:
        with self._locked_state():
            self._refresh_locked()
            request = self._find(proposal_id)
            if not request or request.status is not ApprovalStatus.EXECUTING:
                return False
            if request.execution_session_id != self.session_id:
                return False
            request.status = ApprovalStatus.EXECUTED
            request.executed_at = datetime.now(timezone.utc)
            request.order_id = order_id
            self._persist_locked()
            return True
