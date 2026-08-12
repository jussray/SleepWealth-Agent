from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List

from .base import BaseBroker, Order, Position

MOCK_PRICE = 100.0


@dataclass
class MockBroker(BaseBroker):
    """In-memory broker. No network. Always paper. Used for tests and CI."""

    paper_mode: bool = True
    initial_cash: float = 10000.0

    cash: float = 0.0
    positions: dict = field(default_factory=dict)
    orders: dict = field(default_factory=dict)
    order_counter: int = 0

    async def connect(self) -> bool:
        self.cash = self.initial_cash
        print("[MOCK] connected (in-memory simulation)")
        return True

    async def get_account_summary(self) -> dict:
        equity = self.cash + sum(q * MOCK_PRICE for q in self.positions.values())
        return {
            "cash": self.cash,
            "equity": equity,
            "timestamp": datetime.now(timezone.utc),
        }

    async def get_positions(self) -> List[Position]:
        return [
            Position(symbol=s, qty=q, avg_price=MOCK_PRICE)
            for s, q in self.positions.items()
            if q != 0
        ]

    async def submit_order(self, order: Order) -> dict:
        self.order_counter += 1
        order_id = f"MOCK-{self.order_counter}"

        if order.qty <= 0:
            return {"order_id": order_id, "status": "rejected", "reason": "qty must be > 0"}

        cost = order.qty * MOCK_PRICE

        if order.side == "buy":
            if cost > self.cash:
                return {"order_id": order_id, "status": "rejected", "reason": "insufficient cash"}
            self.cash -= cost
            self.positions[order.symbol] = self.positions.get(order.symbol, 0) + order.qty
        elif order.side == "sell":
            held = self.positions.get(order.symbol, 0)
            if order.qty > held:
                return {"order_id": order_id, "status": "rejected", "reason": "insufficient shares"}
            self.cash += cost
            self.positions[order.symbol] = held - order.qty
        else:
            return {"order_id": order_id, "status": "rejected", "reason": f"unknown side: {order.side}"}

        record = {
            "status": "filled",
            "filled_price": MOCK_PRICE,
            "filled_qty": order.qty,
            "timestamp": datetime.now(timezone.utc),
        }
        self.orders[order_id] = record
        return {"order_id": order_id, **record}

    async def cancel_order(self, order_id: str) -> bool:
        return self.orders.pop(order_id, None) is not None

    async def get_order_status(self, order_id: str) -> dict:
        if order_id not in self.orders:
            return {"status": "not_found"}
        return {"order_id": order_id, **self.orders[order_id]}

    async def get_market_data(self, symbol: str) -> dict:
        return {
            "symbol": symbol,
            "price": MOCK_PRICE,
            "bid": MOCK_PRICE - 0.5,
            "ask": MOCK_PRICE + 0.5,
            "timestamp": datetime.now(timezone.utc),
        }

    def is_paper_only(self) -> bool:
        return True
