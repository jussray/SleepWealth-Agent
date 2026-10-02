"""Crypto sandbox broker with governed crypto capabilities and no real-money capability."""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
import json
from math import isfinite
from typing import List

from .base import BaseBroker, Order, Position

DEFAULT_CRYPTO_PRICE = 1.0
WORKING_ORDER_STATES = {"PendingSubmit", "PreSubmitted", "Submitted", "ApiPending"}


@dataclass
class CryptoSandboxBroker(BaseBroker):
    """In-memory crypto wallet/broker used to exercise the governed execution path safely.

    The sandbox implements the product capability surface (launch, mint, wallet, trade,
    spend, transfer) without granting live-money authority. A future live adapter must
    remain a separate authority decision and cannot inherit authority from these methods.
    """

    paper_mode: bool = True
    initial_cash: float = 100.0
    wallet_id: str = "SANDBOX-WALLET"

    cash: float = 0.0
    positions: dict[str, float] = field(default_factory=dict)
    orders: dict[str, dict] = field(default_factory=dict)
    market_prices: dict[str, float] = field(default_factory=dict)
    launched_assets: dict[str, dict] = field(default_factory=dict)
    capability_receipts: list[dict] = field(default_factory=list)
    order_counter: int = 0
    capability_counter: int = 0

    source_name = "crypto-sandbox-market"
    source_classification = "synthetic-fixture"

    def _price(self, symbol: str) -> float:
        return float(self.market_prices.get(str(symbol).upper(), DEFAULT_CRYPTO_PRICE))

    @staticmethod
    def _positive_number(value: float, *, field_name: str) -> float:
        value = float(value)
        if not isfinite(value) or value <= 0:
            raise ValueError(f"{field_name} must be finite and greater than zero")
        return value

    def _capability_receipt(self, action: str, **payload) -> dict:
        self.capability_counter += 1
        timestamp = datetime.now(timezone.utc)
        stable_payload = {
            "action_id": f"CRYPTO-CAP-{self.capability_counter}",
            "action": action,
            "wallet_id": self.wallet_id,
            "wallet_mode": "sandbox",
            "real_money": False,
            "live_execution": False,
            "timestamp": timestamp.isoformat(),
            **payload,
        }
        fingerprint = sha256(
            json.dumps(stable_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        receipt = {
            **stable_payload,
            "continuity_fingerprint": fingerprint,
            "continuity_cookie": f"crypto-sandbox-capability:{action}:{fingerprint[:16]}",
        }
        self.capability_receipts.append(receipt)
        return receipt

    def capability_matrix(self) -> dict:
        """Return implemented capabilities independently from live authority."""
        return {
            "launch": {"implemented": True, "mode": "sandbox", "method": "launch_asset"},
            "mint": {"implemented": True, "mode": "sandbox", "method": "mint_asset"},
            "wallet": {"implemented": True, "mode": "sandbox", "method": "wallet"},
            "trade": {"implemented": True, "mode": "sandbox", "method": "trade"},
            "spend": {"implemented": True, "mode": "sandbox", "method": "spend"},
            "transfer": {"implemented": True, "mode": "sandbox", "method": "transfer_asset"},
            "live_authority": False,
        }

    def set_market_price(self, symbol: str, price: float) -> None:
        price = self._positive_number(price, field_name="sandbox crypto price")
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
            "live_execution": False,
            "capabilities": self.capability_matrix(),
            "timestamp": datetime.now(timezone.utc),
        }

    async def wallet(self) -> dict:
        summary = await self.get_account_summary()
        summary["positions"] = dict(self.positions)
        summary["launched_assets"] = dict(self.launched_assets)
        return summary

    async def launch_asset(self, symbol: str, name: str | None = None) -> dict:
        symbol = str(symbol).strip().upper()
        if not symbol:
            raise ValueError("symbol is required")
        if symbol in self.launched_assets:
            return {
                "status": "rejected",
                "reason": "asset already launched in sandbox",
                "symbol": symbol,
                "real_money": False,
                "live_execution": False,
            }
        receipt = self._capability_receipt(
            "launch",
            symbol=symbol,
            name=(str(name).strip() if name else symbol),
        )
        self.launched_assets[symbol] = {
            "symbol": symbol,
            "name": receipt["name"],
            "status": "launched",
            "launch_fingerprint": receipt["continuity_fingerprint"],
        }
        return {"status": "launched", **receipt}

    async def mint_asset(self, symbol: str, qty: float) -> dict:
        symbol = str(symbol).strip().upper()
        qty = self._positive_number(qty, field_name="mint quantity")
        if symbol not in self.launched_assets:
            return {
                "status": "rejected",
                "reason": "asset must be launched in sandbox before minting",
                "symbol": symbol,
                "real_money": False,
                "live_execution": False,
            }
        self.positions[symbol] = self.positions.get(symbol, 0.0) + qty
        receipt = self._capability_receipt("mint", symbol=symbol, qty=qty)
        return {"status": "minted", "balance": self.positions[symbol], **receipt}

    async def spend(self, amount: float, purpose: str = "sandbox action") -> dict:
        amount = self._positive_number(amount, field_name="spend amount")
        if amount > self.cash:
            return {
                "status": "rejected",
                "reason": "insufficient sandbox cash",
                "amount": amount,
                "real_money": False,
                "live_execution": False,
            }
        self.cash -= amount
        receipt = self._capability_receipt("spend", amount=amount, purpose=str(purpose))
        return {"status": "spent", "cash_remaining": self.cash, **receipt}

    async def transfer_asset(self, symbol: str, qty: float, destination_wallet_id: str) -> dict:
        symbol = str(symbol).strip().upper()
        qty = self._positive_number(qty, field_name="transfer quantity")
        destination_wallet_id = str(destination_wallet_id).strip()
        if not destination_wallet_id:
            raise ValueError("destination_wallet_id is required")
        held = float(self.positions.get(symbol, 0.0))
        if qty > held:
            return {
                "status": "rejected",
                "reason": "insufficient sandbox asset balance",
                "symbol": symbol,
                "qty": qty,
                "real_money": False,
                "live_execution": False,
            }
        self.positions[symbol] = held - qty
        receipt = self._capability_receipt(
            "transfer",
            symbol=symbol,
            qty=qty,
            destination_wallet_id=destination_wallet_id,
        )
        return {"status": "transferred", "balance": self.positions[symbol], **receipt}

    async def trade(self, symbol: str, qty: float, side: str) -> dict:
        return await self.submit_order(Order(symbol=symbol, qty=qty, side=side, asset_class="crypto"))

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
            "live_execution": False,
            "continuity_fingerprint": fingerprint,
            "continuity_cookie": f"crypto-sandbox:{fingerprint[:16]}",
            "timestamp": timestamp,
        }
        self.orders[order_id] = record
        return {"order_id": order_id, **record}

    async def cancel_order(self, order_id: str) -> bool:
        record = self.orders.get(order_id)
        if not isinstance(record, dict) or record.get("status") not in WORKING_ORDER_STATES:
            return False
        record["status"] = "Cancelled"
        record["cancelled_at"] = datetime.now(timezone.utc)
        return True

    async def cancel_all(self) -> bool:
        cancelled = False
        for order_id in list(self.orders):
            if await self.cancel_order(order_id):
                cancelled = True
        return cancelled

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

    def paper_proof(self) -> dict:
        return {
            "port": None,
            "managed_accounts": [self.wallet_id],
            "configured_paper": True,
            "provably_paper": True,
        }
