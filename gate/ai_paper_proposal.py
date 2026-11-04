"""AI paper-proposal seam for Sleep Wealth.

An AI proposer may request one paper-only simulator cycle. It cannot approve
itself, choose a live or non-mock broker, or add fields. Human approval is a
caller argument (``human_approved``) that the proposal cannot set. Accepted
proposals are handed to the existing ``run_paper_dry_run`` path, which stays
mock-broker and paper-only. Nothing here can authorize live execution.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from market.lanes import normalize_lane

CONTRACT = "sleepwealth/ai-paper-proposal@v1"
ALLOWED_FIELDS = frozenset({"action", "lane", "symbol", "side", "qty", "rationale"})
ALLOWED_ACTIONS = frozenset({"paper_cycle"})
ALLOWED_SIDES = frozenset({"buy", "sell"})
# Conservative proposal-level cap. run_paper_dry_run still enforces the rules engine.
MAX_PAPER_QTY = 1.0

PaperCycleRunner = Callable[..., Awaitable[dict]]


def _fingerprint(proposal: Mapping[str, Any]) -> str:
    canonical = json.dumps(dict(proposal), sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _receipt(status: str, errors: list[str], fingerprint: str | None) -> dict[str, Any]:
    return {
        "contract": CONTRACT,
        "status": status,
        "errors": errors,
        "fingerprint": fingerprint,
        "paper_only": True,
        "broker": "mock",
        "live_execution_authorized": False,
        "authorizes_real_money": False,
    }


def evaluate_paper_proposal(proposal: Any) -> dict[str, Any]:
    """Validate an AI proposal. Pure function: no broker, network, or state access."""
    if not isinstance(proposal, Mapping):
        return _receipt("REJECTED", ["proposal_must_be_object"], None)

    fingerprint = _fingerprint(proposal)
    errors: list[str] = [f"unexpected_field:{key}" for key in proposal if key not in ALLOWED_FIELDS]

    if proposal.get("action") not in ALLOWED_ACTIONS:
        errors.append("action_not_allowlisted")

    # normalize_lane() defaults blank/None to the stock lane. An AI proposal must name its lane.
    raw_lane = proposal.get("lane")
    lane = None
    if not isinstance(raw_lane, str) or not raw_lane.strip():
        errors.append("lane_required")
    else:
        try:
            lane = normalize_lane(raw_lane)
        except ValueError:
            errors.append("unsupported_lane")

    symbol = proposal.get("symbol")
    if not isinstance(symbol, str) or not symbol.strip():
        errors.append("symbol_required")

    if proposal.get("side") not in ALLOWED_SIDES:
        errors.append("side_must_be_buy_or_sell")

    qty = proposal.get("qty")
    if isinstance(qty, bool) or not isinstance(qty, (int, float)) or not math.isfinite(qty):
        errors.append("qty_must_be_finite_number")
    elif not (0 < qty <= MAX_PAPER_QTY):
        errors.append("qty_outside_paper_cap")

    if errors:
        return _receipt("REJECTED", errors, fingerprint)

    accepted = _receipt("ACCEPTED_FOR_PAPER_CYCLE", [], fingerprint)
    accepted["normalized"] = {
        "lane": lane,
        "symbol": symbol.strip().upper(),
        "side": proposal["side"],
        "qty": float(qty),
    }
    return accepted


async def run_ai_paper_proposal(
    proposal: Any,
    *,
    human_approved: bool = False,
    run: PaperCycleRunner | None = None,
) -> dict[str, Any]:
    """Evaluate a proposal and, only with human approval, run one paper cycle."""
    decision = evaluate_paper_proposal(proposal)
    if decision["status"] != "ACCEPTED_FOR_PAPER_CYCLE":
        return {**decision, "cycle": None}
    if human_approved is not True:
        decision["status"] = "HOLD_HUMAN_APPROVAL_REQUIRED"
        decision["errors"] = ["human_approval_required"]
        return {**decision, "cycle": None}

    if run is None:
        from backend.server import run_paper_dry_run as run  # imported lazily; paper-only path

    normalized = decision["normalized"]
    cycle = await run(
        symbol=normalized["symbol"],
        qty=normalized["qty"],
        side=normalized["side"],
        lane=normalized["lane"],
    )
    return {**decision, "status": "PAPER_CYCLE_COMPLETE", "cycle": cycle}
