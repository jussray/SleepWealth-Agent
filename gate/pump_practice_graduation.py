"""Pump practice evidence graduation for human eligibility review only.

This module evaluates simulation coverage and receipt integrity. It never grants
wallet, broker, signing, funding, transfer, minting, or real-money authority.
Profit/loss is reported as an observed outcome, not as an execution gate or a
claim that live trading would be safe, eligible, or profitable.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from math import isfinite
from typing import Iterable, Mapping


@dataclass(frozen=True, slots=True)
class PracticeCheck:
    code: str
    classification: str
    reason: str
    source: str
    blocking: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "classification": self.classification,
            "reason": self.reason,
            "source": self.source,
            "blocking": self.blocking,
        }


def _digest(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _is_sha256(value: object) -> bool:
    text = str(value or "").lower()
    return len(text) == 64 and all(char in "0123456789abcdef" for char in text)


def _receipt_fingerprint_is_intact(receipt: Mapping[str, object]) -> bool:
    supplied = receipt.get("receipt_fingerprint")
    if not _is_sha256(supplied):
        return False
    payload = {
        key: value
        for key, value in receipt.items()
        if key not in {"receipt_fingerprint", "receipt_cookie", "audit"}
    }
    return str(supplied).lower() == _digest(payload)


def _count_round_trips(receipts: Iterable[Mapping[str, object]]) -> tuple[int, bool]:
    positions: dict[str, float] = {}
    round_trips = 0
    valid = True
    for receipt in receipts:
        symbol = str(receipt.get("symbol") or "").upper()
        side = str(receipt.get("side") or "").lower()
        try:
            qty = float(receipt.get("qty") or 0.0)
        except (TypeError, ValueError):
            return round_trips, False
        if not symbol or side not in {"buy", "sell"} or not isfinite(qty) or qty <= 0:
            return round_trips, False
        before = positions.get(symbol, 0.0)
        after = before + qty if side == "buy" else before - qty
        if after < -1e-9:
            valid = False
            after = 0.0
        if side == "sell" and before > 1e-9 and abs(after) <= 1e-9:
            round_trips += 1
        positions[symbol] = after
    return round_trips, valid


def _final_outcome_continuity(
    rows: list[dict[str, object]],
    final_portfolio: Mapping[str, object],
    *,
    outcome_observed: bool,
    pnl_total: float,
    equity: float,
) -> bool:
    """Bind the latest simulated execution receipt to the current sandbox state."""

    if not rows or not outcome_observed:
        return False
    last = rows[-1]
    try:
        receipt_pnl = float(last.get("sandbox_pnl_total", float("nan")))
        receipt_equity = float(last.get("sandbox_equity", float("nan")))
    except (TypeError, ValueError):
        return False
    return (
        isfinite(receipt_pnl)
        and isfinite(receipt_equity)
        and abs(receipt_pnl - pnl_total) <= 1e-9
        and abs(receipt_equity - equity) <= 1e-9
        and str(last.get("pnl_fingerprint") or "").lower()
        == str(final_portfolio.get("pnl_fingerprint") or "").lower()
    )


def evaluate_pump_practice_graduation(
    receipts: Iterable[Mapping[str, object]],
    final_portfolio: Mapping[str, object],
    *,
    minimum_executions: int = 20,
    minimum_round_trips: int = 3,
) -> dict[str, object]:
    """Return a fail-closed, non-executable practice-evidence receipt.

    The default floors are evidence-coverage defaults only. They are not
    financial advice and do not imply that satisfying them makes live trading
    appropriate, safe, profitable, eligible, or authorized.
    """

    minimum_executions = int(minimum_executions)
    minimum_round_trips = int(minimum_round_trips)
    if minimum_executions < 1:
        raise ValueError("minimum_executions must be at least 1")
    if minimum_round_trips < 0:
        raise ValueError("minimum_round_trips must be non-negative")

    rows = [dict(receipt) for receipt in receipts]
    execution_count = len(rows)
    round_trips, sequence_valid = _count_round_trips(rows)

    receipt_integrity = all(
        receipt.get("event") == "pump_sandbox_execution_observed"
        and receipt.get("classification") == "SIMULATED_EXECUTION_RECEIPT"
        and receipt.get("authority") == "sandbox-simulation-only"
        and receipt.get("real_money") is False
        and receipt.get("live_execution") is False
        and _is_sha256(receipt.get("proposal_fingerprint"))
        and _is_sha256(receipt.get("pump_observation_fingerprint"))
        and _is_sha256(receipt.get("simulated_fill_fingerprint"))
        and _receipt_fingerprint_is_intact(receipt)
        for receipt in rows
    ) and sequence_valid

    audit_chain_captured = bool(rows) and all(
        isinstance(receipt.get("audit"), Mapping)
        and receipt["audit"].get("classification") == "OBSERVED_UNANCHORED"
        and receipt["audit"].get("trusted") is False
        and _is_sha256(receipt["audit"].get("entry_hash"))
        for receipt in rows
    )

    try:
        pnl_total = float(final_portfolio.get("pnl_total", 0.0))
        equity = float(final_portfolio.get("equity", 0.0))
    except (TypeError, ValueError):
        pnl_total = float("nan")
        equity = float("nan")
    outcome_observed = (
        isfinite(pnl_total)
        and isfinite(equity)
        and _is_sha256(final_portfolio.get("pnl_fingerprint"))
        and final_portfolio.get("real_money") is False
        and final_portfolio.get("live_execution") is False
        and final_portfolio.get("wallet_mode") == "sandbox"
    )
    final_continuity = _final_outcome_continuity(
        rows,
        final_portfolio,
        outcome_observed=outcome_observed,
        pnl_total=pnl_total,
        equity=equity,
    )

    checks = (
        PracticeCheck(
            code="SIMULATED_EXECUTION_SAMPLE",
            classification="VERIFIED" if execution_count >= minimum_executions else "BLOCKED",
            reason=f"{execution_count} simulated executions observed; floor is {minimum_executions}",
            source="pump-sandbox-execution-receipts",
        ),
        PracticeCheck(
            code="COMPLETED_ROUND_TRIPS",
            classification="VERIFIED" if round_trips >= minimum_round_trips else "BLOCKED",
            reason=f"{round_trips} completed simulated round trips observed; floor is {minimum_round_trips}",
            source="pump-sandbox-execution-receipts",
        ),
        PracticeCheck(
            code="RECEIPT_INTEGRITY",
            classification="VERIFIED" if receipt_integrity and rows else "BLOCKED",
            reason=(
                "all simulated execution receipts preserve fingerprints and sandbox-only authority"
                if receipt_integrity and rows
                else "one or more simulated execution receipts are missing or failed integrity/boundary checks"
            ),
            source="pump-sandbox-execution-receipts",
        ),
        PracticeCheck(
            code="AUDIT_CHAIN_CAPTURED",
            classification="VERIFIED" if audit_chain_captured else "BLOCKED",
            reason=(
                "each simulated execution has an unanchored append-only audit receipt"
                if audit_chain_captured
                else "complete per-execution audit-chain evidence is not present"
            ),
            source="pump-sandbox-audit",
        ),
        PracticeCheck(
            code="FINAL_OUTCOME_OBSERVED",
            classification="VERIFIED" if outcome_observed else "BLOCKED",
            reason=(
                f"final sandbox outcome observed with P&L {pnl_total:.6f} and equity {equity:.6f}"
                if outcome_observed
                else "final sandbox P&L/equity receipt is missing or invalid"
            ),
            source="pump-sandbox-pnl",
        ),
        PracticeCheck(
            code="FINAL_OUTCOME_CONTINUITY",
            classification="VERIFIED" if final_continuity else "BLOCKED",
            reason=(
                "current sandbox P&L/equity is bound to the latest simulated execution receipt"
                if final_continuity
                else "current sandbox outcome no longer matches the latest simulated execution receipt"
            ),
            source="pump-sandbox-pnl",
        ),
        PracticeCheck(
            code="SIMULATED_PNL_SIGNAL",
            classification=(
                "OBSERVED_POSITIVE"
                if outcome_observed and pnl_total > 0
                else "OBSERVED_NONPOSITIVE" if outcome_observed else "UNKNOWN"
            ),
            reason=(
                f"simulated cumulative P&L is {pnl_total:.6f}; this is informational only"
                if outcome_observed
                else "simulated cumulative P&L is not available"
            ),
            source="pump-sandbox-pnl",
            blocking=False,
        ),
    )

    blocking_checks = [check for check in checks if check.blocking]
    practice_evidence_complete = all(
        check.classification == "VERIFIED" for check in blocking_checks
    )
    metrics = {
        "execution_count": execution_count,
        "minimum_executions": minimum_executions,
        "completed_round_trips": round_trips,
        "minimum_round_trips": minimum_round_trips,
        "pnl_total": pnl_total if outcome_observed else None,
        "equity": equity if outcome_observed else None,
    }
    fingerprint = _digest(
        {
            "schema": "pump-practice-graduation-v2",
            "checks": [check.to_dict() for check in checks],
            "metrics": metrics,
            "platform_eligibility_verified": False,
        }
    )
    return {
        "schema": "pump-practice-graduation-v2",
        "event": "pump_practice_graduation_evaluated",
        "classification": (
            "READY_FOR_ELIGIBILITY_REVIEW"
            if practice_evidence_complete
            else "PRACTICE_REQUIRED"
        ),
        "review_ready": practice_evidence_complete,
        "practice_evidence_complete": practice_evidence_complete,
        "live_review_ready": False,
        "platform_eligibility_verified": False,
        "eligibility_review_required": True,
        "eligibility": {
            "classification": "UNVERIFIED",
            "source": "external-eligibility-review-required",
            "reason": (
                "simulation evidence cannot establish age, account, jurisdiction, identity, "
                "or platform eligibility"
            ),
        },
        "checks": [check.to_dict() for check in checks],
        "blockers": [
            check.code
            for check in blocking_checks
            if check.classification != "VERIFIED"
        ],
        "metrics": metrics,
        "fingerprint": fingerprint,
        "continuity_cookie": f"pump-practice-graduation-v2:{fingerprint[:24]}",
        "manual_adult_review_required": True,
        "execution_authorized": False,
        "submit_capability": False,
        "money_movement_capability": False,
        "real_money": False,
        "live_execution": False,
        "authority": "none",
        "truth": (
            "Practice-complete means the configured simulation-evidence coverage is complete. "
            "It does not establish platform eligibility, authorize trading, prove future "
            "profitability, or make live execution safe."
        ),
    }
