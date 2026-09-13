from dataclasses import dataclass, field
from datetime import datetime, timezone
from math import isfinite
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
    market_prices: dict = field(default_factory=dict)
    order_counter: int = 0

    source_name = "mock-market-observation"
    source_classification = "synthetic-fixture"
    max_age_seconds = 5 * 60

    def _price(self, symbol: str) -> float:
        return float(self.market_prices.get(str(symbol).upper(), MOCK_PRICE))

    def set_market_price(self, symbol: str, price: float) -> None:
        price = float(price)
        if not isfinite(price) or price <= 0:
            raise ValueError("mock market price must be finite and greater than zero")
        self.market_prices[str(symbol).upper()] = price

    async def connect(self) -> bool:
        self.cash = self.initial_cash
        print("[MOCK] connected (in-memory simulation)")
        return True

    async def get_account_summary(self) -> dict:
        equity = self.cash + sum(q * self._price(symbol) for symbol, q in self.positions.items())
        return {
            "cash": self.cash,
            "equity": equity,
            "timestamp": datetime.now(timezone.utc),
        }

    async def get_positions(self) -> List[Position]:
        return [
            Position(symbol=s, qty=q, avg_price=self._price(s))
            for s, q in self.positions.items()
            if q != 0
        ]

    async def submit_order(self, order: Order) -> dict:
        self.order_counter += 1
        order_id = f"MOCK-{self.order_counter}"

        if order.qty <= 0:
            return {"order_id": order_id, "status": "rejected", "reason": "qty must be > 0"}

        fill_price = self._price(order.symbol)
        cost = order.qty * fill_price

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
            "filled_price": fill_price,
            "filled_qty": order.qty,
            "fill_classification": "SIMULATED_AT_OBSERVED_PRICE",
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
        price = self._price(symbol)
        return {
            "symbol": symbol,
            "price": price,
            "bid": price,
            "ask": price,
            "timestamp": datetime.now(timezone.utc),
            "source_name": self.source_name,
            "source_classification": self.source_classification,
        }

    def is_paper_only(self) -> bool:
        return True
