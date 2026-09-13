"""Crypto sandbox broker with wallet-like receipts and no real-money capability."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import List

from .base import BaseBroker, Order, Position

DEFAULT_CRYPTO_PRICE = 1.0


@dataclass
class CryptoSandboxBroker(BaseBroker):
    """In-memory crypto wallet/broker used to exercise the governed execution path safely."""

    paper_mode: bool = True
    initial_cash: float = 100.0
    wallet_id: str = "SANDBOX-WALLET"

    cash: float = 0.0
    positions: dict[str, float] = field(default_factory=dict)
    orders: dict[str, dict] = field(default_factory=dict)
    market_prices: dict[str, float] = field(default_factory=dict)
    order_counter: int = 0

    source_name = "crypto-sandbox-market"
    source_classification = "synthetic-fixture"

    def _price(self, symbol: str) -> float:
        return float(self.market_prices.get(str(symbol).upper(), DEFAULT_CRYPTO_PRICE))

    def set_market_price(self, symbol: str, price: float) -> None:
        price = float(price)
        if not isfinite(price) or price <= 0:
            raise ValueError("sandbox crypto price must be finite and greater than zero")
        self.market_prices[str(symbol).upper()] = price

    async def connect(self) -> bool:
        self.cash = float(self.initial_cash)
        return True

    async def get_account_summary(self) -> dict:
        equity = self.cash + sum(qty * self._price(symbol) for symbol, qty in self.positions.items())
        return {
            "cash": self.cash,
            "equity": equity,
            "wallet_id": self.wallet_id,
            "wallet_mode": "sandbox",
            "real_money": False,
            "timestamp": datetime.now(timezone.utc),
        }

    async def get_positions(self) -> List[Position]:
        return [
            Position(symbol=symbol, qty=qty, avg_price=self._price(symbol))
            for symbol, qty in self.positions.items()
            if qty != 0
        ]

    async def submit_order(self, order: Order) -> dict:
        self.order_counter += 1
        order_id = f"CRYPTO-SANDBOX-{self.order_counter}"

        if order.asset_class != "crypto":
            return {
                "order_id": order_id,
                "status": "rejected",
                "reason": "crypto sandbox accepts asset_class='crypto' only",
            }
        if order.qty <= 0:
            return {"order_id": order_id, "status": "rejected", "reason": "qty must be > 0"}

        symbol = str(order.symbol).upper()
        fill_price = self._price(symbol)
        cost = float(order.qty) * fill_price

        if order.side == "buy":
            if cost > self.cash:
                return {
                    "order_id": order_id,
                    "status": "rejected",
                    "reason": "insufficient sandbox cash",
                }
            self.cash -= cost
            self.positions[symbol] = self.positions.get(symbol, 0.0) + float(order.qty)
        elif order.side == "sell":
            held = self.positions.get(symbol, 0.0)
            if float(order.qty) > held:
                return {
                    "order_id": order_id,
                    "status": "rejected",
                    "reason": "insufficient sandbox asset balance",
                }
            self.cash += cost
            self.positions[symbol] = held - float(order.qty)
        else:
            return {
                "order_id": order_id,
                "status": "rejected",
                "reason": f"unknown side: {order.side}",
            }

        timestamp = datetime.now(timezone.utc)
        receipt_payload = {
            "wallet_id": self.wallet_id,
            "order_id": order_id,
            "symbol": symbol,
            "qty": float(order.qty),
            "side": order.side,
            "filled_price": fill_price,
            "real_money": False,
        }
        fingerprint = sha256(
            json.dumps(receipt_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        record = {
            "status": "filled",
            "filled_price": fill_price,
            "filled_qty": float(order.qty),
            "fill_classification": "SIMULATED_CRYPTO_WALLET_FILL",
            "wallet_id": self.wallet_id,
            "wallet_mode": "sandbox",
            "real_money": False,
            "continuity_fingerprint": fingerprint,
            "continuity_cookie": f"crypto-sandbox:{fingerprint[:16]}",
            "timestamp": timestamp,
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
        symbol = str(symbol).upper()
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
