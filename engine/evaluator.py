from datetime import datetime, timezone

from broker.base import Order
from portfolio.models import AccountState

ASSUMED_PRICE = 100.0


class ProposalEvaluator:
    """TRUTHMODE gate: is this order actually supported by the rules?"""

    def __init__(self, rules: dict):
        self.rules = rules
        self.floor_cash = rules.get("floor_cash", 5.0)
        self.approved_symbols = set(rules.get("approved_symbols", []))
        self.max_position_size = rules.get("max_position_size", 1000.0)
        self.ceiling = rules.get("ceiling", {}).get("current", 5.0)

    def evaluate(self, order: Order, account: AccountState, price: float = ASSUMED_PRICE) -> dict:
        reasons: list[str] = []
        cost = order.qty * price

        if self.approved_symbols and order.symbol not in self.approved_symbols:
            reasons.append(f"{order.symbol} not in approved_symbols")

        if cost > self.ceiling:
            reasons.append(f"cost ${cost:.2f} exceeds ceiling ${self.ceiling:.2f}")

        if cost > self.max_position_size:
            reasons.append(f"cost ${cost:.2f} exceeds max_position_size")

        if order.side == "buy" and (account.balance.cash - cost) < self.floor_cash:
            reasons.append(f"would breach cash floor of ${self.floor_cash:.2f}")

        if not account.safe_to_trade():
            reasons.append("account below cash floor")

        risk_score = (cost / account.balance.cash * 100.0) if account.balance.cash else 100.0

        return {
            "allowed": not reasons,
            "reason": "; ".join(reasons) if reasons else "OK",
            "risk_score": round(risk_score, 2),
            "estimated_cost": cost,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
