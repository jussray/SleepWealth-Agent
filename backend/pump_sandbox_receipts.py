"""Pump Live Box sandbox P&L and execution receipts.

This module records evidence about simulated execution only. It never grants
wallet, broker, signing, funding, transfer, or real-money authority.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

from audit.logger import AuditLogger


def _fingerprint(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PumpSandboxReceiptBook:
    """Build P&L snapshots and hash-chained simulated-execution receipts."""

    def __init__(self, initial_cash: float, audit_path: str | None = None):
        self.initial_cash = float(initial_cash)
        self.audit = AuditLogger(audit_path) if audit_path else None

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
            "authority": "sandbox-simulation-only",
            "status": "ok",
        }

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
