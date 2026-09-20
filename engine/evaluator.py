from datetime import datetime, timezone

from broker.base import Order
from market.investor_lens import build_investor_lens_policy_receipt
from portfolio.models import AccountState


class ProposalEvaluator:
    """TRUTHMODE gate: is this paper order actually supported by the rules?"""

    def __init__(self, rules: dict):
        self.rules = rules
        self.floor_cash = rules.get("floor_cash", 5.0)
        self.approved_symbols = set(rules.get("approved_symbols", []))
        self.symbol_scope = str(rules.get("symbol_scope", "approved")).strip().lower()
        self.max_position_size = rules.get("max_position_size", 1000.0)
        self.ceiling = rules.get("ceiling", {}).get("current", 5.0)
        self.investor_lens = build_investor_lens_policy_receipt()

    def evaluate(self, order: Order, account: AccountState, price: float) -> dict:
        reasons: list[str] = []
        if price is None or float(price) <= 0:
            raise ValueError("a positive observed market price is required")
        price = float(price)
        cost = order.qty * price

        if self.symbol_scope == "approved":
            if self.approved_symbols and order.symbol not in self.approved_symbols:
                reasons.append(f"{order.symbol} not in approved_symbols")
        elif self.symbol_scope == "observable-market":
            pass
        else:
            reasons.append(f"unsupported symbol_scope {self.symbol_scope}")

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
            "observed_price": price,
            "symbol_scope": self.symbol_scope,
            "rules_version": self.rules.get("version"),
            "ceiling": self.ceiling,
            "max_position_size": self.max_position_size,
            "floor_cash": self.floor_cash,
            "investor_lens": self.investor_lens,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
