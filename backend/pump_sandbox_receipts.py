"""Pump Live Box sandbox P&L and execution receipts.

This module records evidence about simulated execution only. It never grants
wallet, broker, signing, funding, transfer, or real-money authority.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
from math import isfinite
from typing import Any, Iterable, Mapping

from audit.logger import AuditLogger
from backend.practice_state_store import practice_state_store


def _fingerprint(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _finite_number(value: object, *, name: str, minimum: float | None = None) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError) as exc:
        raise RuntimeError(f"practice state {name} must be numeric") from exc
    if not isfinite(number):
        raise RuntimeError(f"practice state {name} must be finite")
    if minimum is not None and number < minimum:
        raise RuntimeError(f"practice state {name} must be >= {minimum}")
    return number


class PumpSandboxReceiptBook:
    """Build P&L snapshots, execution receipts, and durable sandbox practice state."""

    STATE_SCHEMA = "pump-practice-state-v1"

    def __init__(
        self,
        initial_cash: float,
        audit_path: str | None = None,
        practice_state_path: str | None = None,
    ):
        self.initial_cash = float(initial_cash)
        self.audit = AuditLogger(audit_path) if audit_path else None
        self.state_store = practice_state_store(practice_state_path)
        self._state_version: str | None = None
        self._state_persisted = False
        self.persistence_fault: str | None = None

    async def portfolio(self, broker) -> dict[str, Any]:
        account = await broker.get_account_summary()
        cash = float(account["cash"])
        equity = float(account["equity"])
        positions = {
            str(symbol).upper(): float(qty)
            for symbol, qty in sorted(broker.positions.items())
            if float(qty) != 0.0
        }
        prices = {
            symbol: float(broker.market_prices.get(symbol, 1.0))
            for symbol in positions
        }
        payload = {
            "initial_cash": self.initial_cash,
            "cash": cash,
            "equity": equity,
            "positions": positions,
            "prices": prices,
            "pnl_total": equity - self.initial_cash,
            "wallet_mode": "sandbox",
            "real_money": False,
            "live_execution": False,
        }
        fingerprint = _fingerprint(payload)
        return {
            **account,
            **payload,
            "pnl_fingerprint": fingerprint,
            "pnl_cookie": f"pump-sandbox-pnl-v1:{fingerprint[:24]}",
            "practice_state_persistence_required": self.state_store is not None,
            "practice_state_persisted": self._state_persisted,
            "practice_state_persistence_ok": self.persistence_fault is None,
            "practice_state_transport": (
                self.state_store.kind if self.state_store is not None else "none"
            ),
            "authority": "sandbox-simulation-only",
            "status": "ok",
        }

    def _state_payload(self, broker, receipts: Iterable[Mapping[str, object]]) -> dict[str, Any]:
        return {
            "schema": self.STATE_SCHEMA,
            "initial_cash": self.initial_cash,
            "broker": {
                "cash": float(broker.cash),
                "positions": {
                    str(symbol).upper(): float(qty)
                    for symbol, qty in sorted(broker.positions.items())
                    if float(qty) != 0.0
                },
                "market_prices": {
                    str(symbol).upper(): float(price)
                    for symbol, price in sorted(broker.market_prices.items())
                },
                "order_counter": int(broker.order_counter),
            },
            "execution_receipts": [dict(receipt) for receipt in receipts],
            "authority": "sandbox-simulation-only",
            "real_money": False,
            "live_execution": False,
        }

    async def persist_state(
        self,
        broker,
        receipts: Iterable[Mapping[str, object]],
    ) -> dict[str, object]:
        if self.state_store is None:
            return {
                "classification": "UNCONFIGURED",
                "persisted": False,
                "reason": "no durable practice state store configured",
                "real_money": False,
                "live_execution": False,
            }
        payload = self._state_payload(broker, receipts)
        fingerprint = _fingerprint(payload)
        snapshot = {
            **payload,
            "state_fingerprint": fingerprint,
            "state_cookie": f"pump-practice-state-v1:{fingerprint[:24]}",
        }
        try:
            version = await asyncio.to_thread(
                self.state_store.write,
                snapshot,
                self._state_version,
            )
        except Exception as exc:  # simulated execution already happened; report separately
            self._state_persisted = False
            self.persistence_fault = str(exc)
            return {
                "classification": "BLOCKED",
                "persisted": False,
                "transport": self.state_store.kind,
                "reason": f"simulated execution occurred but durable practice state was not accepted: {exc}",
                "trusted": False,
                "real_money": False,
                "live_execution": False,
            }
        self._state_version = version
        self._state_persisted = True
        self.persistence_fault = None
        remote = self.state_store.kind == "remote-http"
        return {
            "classification": "PERSISTED_UNANCHORED",
            "persisted": True,
            "state_fingerprint": fingerprint,
            "state_cookie": snapshot["state_cookie"],
            "transport": self.state_store.kind,
            "trusted": False,
            "reason": (
                "conditional remote sandbox snapshot persisted; no independent trust anchor claimed"
                if remote
                else "atomic local sandbox snapshot persisted; no independent trust anchor claimed"
            ),
            "real_money": False,
            "live_execution": False,
        }

    def _read_state_sync(self) -> dict[str, object] | None:
        if self.state_store is None:
            return None
        record = self.state_store.read()
        if record is None:
            self._state_version = None
            self._state_persisted = False
            return None
        self._state_version = record.version
        value = record.snapshot
        supplied = str(value.get("state_fingerprint") or "").lower()
        payload = {
            key: item
            for key, item in value.items()
            if key not in {"state_fingerprint", "state_cookie"}
        }
        if len(supplied) != 64 or supplied != _fingerprint(payload):
            raise RuntimeError("practice state fingerprint mismatch")
        if value.get("state_cookie") != f"pump-practice-state-v1:{supplied[:24]}":
            raise RuntimeError("practice state continuity cookie mismatch")
        if payload.get("schema") != self.STATE_SCHEMA:
            raise RuntimeError("practice state schema mismatch")
        if payload.get("authority") != "sandbox-simulation-only":
            raise RuntimeError("practice state authority boundary changed")
        if payload.get("real_money") is not False or payload.get("live_execution") is not False:
            raise RuntimeError("practice state claims live or real-money capability")
        persisted_initial = _finite_number(payload.get("initial_cash"), name="initial_cash", minimum=0.0)
        if abs(persisted_initial - self.initial_cash) > 1e-9:
            raise RuntimeError("practice state initial cash does not match configured sandbox")
        broker_state = payload.get("broker")
        rows = payload.get("execution_receipts")
        if not isinstance(broker_state, dict):
            raise RuntimeError("practice state broker snapshot is missing")
        if not isinstance(rows, list) or not all(isinstance(row, dict) for row in rows):
            raise RuntimeError("practice state execution receipts are invalid")
        self._state_persisted = True
        self.persistence_fault = None
        return payload

    async def restore_state(self, broker) -> list[dict[str, object]]:
        payload = await asyncio.to_thread(self._read_state_sync)
        if payload is None:
            return []
        broker_state = payload["broker"]
        assert isinstance(broker_state, dict)
        cash = _finite_number(broker_state.get("cash"), name="cash", minimum=0.0)
        positions_raw = broker_state.get("positions")
        prices_raw = broker_state.get("market_prices")
        if not isinstance(positions_raw, dict) or not isinstance(prices_raw, dict):
            raise RuntimeError("practice state positions/prices are invalid")
        positions: dict[str, float] = {}
        for symbol, qty in positions_raw.items():
            key = str(symbol).upper().strip()
            if not key:
                raise RuntimeError("practice state contains an empty position symbol")
            positions[key] = _finite_number(qty, name=f"position[{key}]", minimum=0.0)
        prices: dict[str, float] = {}
        for symbol, price in prices_raw.items():
            key = str(symbol).upper().strip()
            if not key:
                raise RuntimeError("practice state contains an empty price symbol")
            prices[key] = _finite_number(price, name=f"price[{key}]", minimum=1e-12)
        try:
            order_counter = int(broker_state.get("order_counter", 0))
        except (TypeError, ValueError) as exc:
            raise RuntimeError("practice state order counter is invalid") from exc
        if order_counter < 0:
            raise RuntimeError("practice state order counter must be non-negative")

        broker.cash = cash
        broker.positions = positions
        broker.market_prices = prices
        broker.order_counter = order_counter
        broker.orders = {}
        rows = [dict(row) for row in payload["execution_receipts"]]
        wallet = await self.portfolio(broker)
        if rows:
            last = rows[-1]
            try:
                receipt_cash = float(last.get("sandbox_cash"))
                receipt_equity = float(last.get("sandbox_equity"))
                receipt_pnl = float(last.get("sandbox_pnl_total"))
            except (TypeError, ValueError) as exc:
                raise RuntimeError("practice state final receipt outcome is invalid") from exc
            if (
                not isfinite(receipt_cash)
                or not isfinite(receipt_equity)
                or not isfinite(receipt_pnl)
                or abs(receipt_cash - float(wallet["cash"])) > 1e-9
                or abs(receipt_equity - float(wallet["equity"])) > 1e-9
                or abs(receipt_pnl - float(wallet["pnl_total"])) > 1e-9
                or str(last.get("pnl_fingerprint") or "").lower()
                != str(wallet.get("pnl_fingerprint") or "").lower()
            ):
                raise RuntimeError("practice state final outcome continuity mismatch")
        elif (
            abs(float(wallet["cash"]) - self.initial_cash) > 1e-9
            or wallet["positions"]
            or abs(float(wallet["pnl_total"])) > 1e-9
        ):
            raise RuntimeError("practice state has portfolio mutations without execution receipts")
        return rows

    async def record_execution(
        self,
        *,
        request,
        proposal_fingerprint: str,
        approval_fingerprint: str | None,
        execution: dict[str, Any],
        wallet: dict[str, Any],
    ) -> dict[str, Any]:
        event = {
            "event": "pump_sandbox_execution_observed",
            "classification": "SIMULATED_EXECUTION_RECEIPT",
            "proposal_id": request.proposal_id,
            "symbol": request.order.symbol,
            "side": request.order.side,
            "qty": float(request.order.qty),
            "proposal_fingerprint": proposal_fingerprint,
            "approval_fingerprint": approval_fingerprint,
            "pump_observation_fingerprint": request.evaluation["pump_observation_fingerprint"],
            "pump_public_evidence_fingerprint": request.evaluation[
                "pump_public_evidence_fingerprint"
            ],
            "pump_mirror_fingerprint": request.evaluation["pump_mirror_fingerprint"],
            "simulated_fill_fingerprint": execution.get("continuity_fingerprint"),
            "simulated_fill_cookie": execution.get("continuity_cookie"),
            "filled_price": execution.get("filled_price"),
            "filled_qty": execution.get("filled_qty"),
            "sandbox_cash": wallet["cash"],
            "sandbox_equity": wallet["equity"],
            "sandbox_pnl_total": wallet["pnl_total"],
            "pnl_fingerprint": wallet["pnl_fingerprint"],
            "authority": "sandbox-simulation-only",
            "real_money": False,
            "live_execution": False,
        }
        receipt_fingerprint = _fingerprint(event)
        audit = {
            "classification": "UNCONFIGURED",
            "trusted": False,
            "reason": "no audit path configured for this sandbox session",
        }
        if self.audit is not None:
            try:
                entry_hash = await self.audit.log(event)
                audit = {
                    "classification": "OBSERVED_UNANCHORED",
                    "trusted": False,
                    "entry_hash": entry_hash,
                    "terminal_hash": self.audit.observed_terminal_hash(),
                    "reason": (
                        "append-only hash-chain entry recorded; no independent trust anchor "
                        "is claimed by this receipt"
                    ),
                }
            except Exception as exc:  # execution already occurred; report audit failure separately
                audit = {
                    "classification": "BLOCKED",
                    "trusted": False,
                    "reason": f"simulated execution occurred but audit append failed: {exc}",
                }

        return {
            **event,
            "receipt_fingerprint": receipt_fingerprint,
            "receipt_cookie": f"pump-sandbox-execution-v1:{receipt_fingerprint[:24]}",
            "audit": audit,
        }
