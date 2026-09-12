from approvals.queue import ApprovalQueue, ApprovalStatus
from audit.logger import AuditLogger
from broker.base import BaseBroker, Order
from risk.gates import RiskGates


class ExecutionManager:
    """OODA 'Act' stage. Order of operations: gate -> approval -> broker -> audit."""

    def __init__(
        self,
        broker: BaseBroker,
        approval_queue: ApprovalQueue,
        audit_logger: AuditLogger,
        risk_gates: RiskGates,
    ):
        self.broker = broker
        self.approval_queue = approval_queue
        self.audit_logger = audit_logger
        self.risk_gates = risk_gates
        self.active_orders: dict[str, str] = {}

    async def propose_order(self, order: Order, evaluation: dict) -> str:
        proposal_id = self.approval_queue.add(order, evaluation)
        await self.audit_logger.log({
            "event": "proposal_created",
            "proposal_id": proposal_id,
            "order": {"symbol": order.symbol, "qty": order.qty, "side": order.side},
            "evaluation": evaluation,
        })
        return proposal_id

    async def execute_approved(self, proposal_id: str) -> dict:
        proposal = self.approval_queue.get(proposal_id)
        if not proposal:
            return {"error": f"proposal {proposal_id} not found"}

        if proposal.status is not ApprovalStatus.APPROVED:
            await self.audit_logger.log({
                "event": "execution_blocked",
                "proposal_id": proposal_id,
                "reason": f"status is {proposal.status.value}, not approved",
            })
            return {"error": f"proposal {proposal_id} is not approved"}

        gate = await self.risk_gates.preflight_check()
        if not gate["passed"]:
            await self.audit_logger.log({
                "event": "execution_blocked",
                "proposal_id": proposal_id,
                "reason": gate["reason"],
            })
            return {"error": f"risk gate blocked: {gate['reason']}"}

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
            })
            return {"error": f"order rejected: {result.get('reason')}"}

        order_id = result.get("order_id")
        self.active_orders[order_id] = proposal_id
        self.approval_queue.mark_executed(proposal_id, order_id)

        receipt = {**result, "order_id": order_id, "status": result.get("status", "submitted")}
        await self.audit_logger.log({
            "event": "order_submitted",
            "proposal_id": proposal_id,
            "order_id": order_id,
            "status": receipt["status"],
            "filled_price": receipt.get("filled_price"),
            "filled_qty": receipt.get("filled_qty"),
            "fill_classification": receipt.get("fill_classification"),
        })

        return receipt

    async def check_order_status(self, order_id: str) -> dict:
        return await self.broker.get_order_status(order_id)
