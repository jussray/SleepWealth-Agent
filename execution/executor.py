from datetime import datetime, timezone

from approvals.queue import ApprovalQueue, ApprovalStatus
from audit.logger import AuditLogger
from broker.base import BaseBroker, Order
from engine.evaluator import ProposalEvaluator
from risk.gates import RiskGates


class ExecutionManager:
    """Simulation executor with approval integrity and fresh-evidence checks."""

    def __init__(
        self,
        broker: BaseBroker,
        approval_queue: ApprovalQueue,
        audit_logger: AuditLogger,
        risk_gates: RiskGates,
        evaluator: ProposalEvaluator,
        max_quote_age_seconds: float = 30.0,
    ):
        self.broker = broker
        self.approval_queue = approval_queue
        self.audit_logger = audit_logger
        self.risk_gates = risk_gates
        self.evaluator = evaluator
        self.max_quote_age_seconds = max_quote_age_seconds
        self.active_orders: dict[str, str] = {}

    async def propose_order(self, order: Order, evaluation: dict) -> str:
        proposal_id = self.approval_queue.add(order, evaluation)
        await self.audit_logger.log({
            "event": "proposal_created",
            "proposal_id": proposal_id,
            "order": self._order_payload(order),
            "evaluation": evaluation,
        })
        return proposal_id

    async def execute_approved(self, proposal_id: str) -> dict:
        proposal = self.approval_queue.get(proposal_id)
        if not proposal:
            return {"error": f"proposal {proposal_id} not found"}

        if proposal.status is not ApprovalStatus.APPROVED:
            return await self._block(
                proposal_id, f"status is {proposal.status.value}, not approved"
            )

        if not self.approval_queue.approval_is_intact(proposal_id):
            return await self._block(
                proposal_id, "approval fingerprint mismatch; order or evidence changed"
            )

        if not proposal.evaluation.get("allowed", False):
            return await self._block(proposal_id, "approved evaluation was not allowed")

        gate = await self.risk_gates.preflight_check()
        if not gate["passed"]:
            return await self._block(proposal_id, f"risk gate blocked: {gate['reason']}")

        try:
            market_data = await self.broker.get_market_data(proposal.order.symbol)
            price = self._execution_price(proposal.order, market_data)
            self._require_fresh_quote(market_data)
        except Exception as exc:
            return await self._block(proposal_id, f"market evidence unavailable: {exc}")

        account = self.risk_gates.portfolio_tracker.last_update
        if account is None:
            account = await self.risk_gates.portfolio_tracker.refresh()

        fresh_evaluation = self.evaluator.evaluate(proposal.order, account, price=price)
        if not fresh_evaluation["allowed"]:
            return await self._block(
                proposal_id,
                f"fresh evaluation blocked: {fresh_evaluation['reason']}",
                extra={"market_data": market_data, "fresh_evaluation": fresh_evaluation},
            )

        try:
            result = await self.broker.submit_order(proposal.order)
        except Exception as exc:
            await self.audit_logger.log({
                "event": "execution_error",
                "proposal_id": proposal_id,
                "error": str(exc),
            })
            return {"error": str(exc)}

        if result.get("status") == "rejected":
            await self.audit_logger.log({
                "event": "order_rejected",
                "proposal_id": proposal_id,
                "reason": result.get("reason"),
                "broker_result": result,
            })
            return {"error": f"order rejected: {result.get('reason')}"}

        order_id = result.get("order_id")
        if not order_id:
            return await self._block(proposal_id, "broker response missing order_id")

        self.active_orders[order_id] = proposal_id
        self.approval_queue.mark_executed(proposal_id, order_id)

        await self.audit_logger.log({
            "event": "order_submitted",
            "proposal_id": proposal_id,
            "order_id": order_id,
            "order": self._order_payload(proposal.order),
            "market_data": market_data,
            "fresh_evaluation": fresh_evaluation,
            "broker_result": result,
        })

        return {**result, "order_id": order_id, "status": result.get("status", "submitted")}

    async def check_order_status(self, order_id: str) -> dict:
        return await self.broker.get_order_status(order_id)

    async def _block(self, proposal_id: str, reason: str, extra: dict | None = None) -> dict:
        event = {"event": "execution_blocked", "proposal_id": proposal_id, "reason": reason}
        if extra:
            event.update(extra)
        await self.audit_logger.log(event)
        return {"error": reason}

    @staticmethod
    def _order_payload(order: Order) -> dict:
        return {
            "symbol": order.symbol,
            "qty": order.qty,
            "side": order.side,
            "asset_class": order.asset_class,
        }

    @staticmethod
    def _execution_price(order: Order, market_data: dict) -> float:
        side = order.side.lower()
        if side == "buy":
            price = market_data.get("ask") or market_data.get("price")
        elif side == "sell":
            price = market_data.get("bid") or market_data.get("price")
        else:
            raise ValueError(f"unknown side: {order.side}")
        if price is None or float(price) <= 0:
            raise ValueError("quote has no positive executable price")
        return float(price)

    def _require_fresh_quote(self, market_data: dict) -> None:
        timestamp = market_data.get("timestamp")
        if timestamp is None:
            raise ValueError("quote timestamp missing")
        if isinstance(timestamp, str):
            timestamp = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - timestamp.astimezone(timezone.utc)).total_seconds()
        if age < -5:
            raise ValueError("quote timestamp is in the future")
        if age > self.max_quote_age_seconds:
            raise ValueError(
                f"quote is stale ({age:.1f}s > {self.max_quote_age_seconds:.1f}s)"
            )
