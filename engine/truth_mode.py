from __future__ import annotations

from enum import StrEnum
from hashlib import sha256
import json
from typing import Any, Mapping, Sequence


TRUTH_DECISION_CONTRACT = "sleepwealth/truth-decision-loop@v1"


class ClaimState(StrEnum):
    VERIFIED = "VERIFIED"
    OBSERVED = "OBSERVED"
    INFERRED = "INFERRED"
    UNKNOWN = "UNKNOWN"
    BLOCKED = "BLOCKED"


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _marker(prefix: str, payload: Mapping[str, Any]) -> str:
    return f"{prefix}:{_canonical_digest(payload)}"


def _plane(state: ClaimState, summary: str) -> dict[str, str]:
    return {"state": state.value, "summary": summary}


def _finalize(payload: dict[str, Any]) -> dict[str, Any]:
    fingerprint = _marker("sw-truth-v1", payload)
    digest = fingerprint.rsplit(":", 1)[-1]
    return {
        **payload,
        "fingerprint": fingerprint,
        "continuity_cookie": f"sw-truth-cookie-v1:{digest}",
    }


def build_paper_cycle_truth_receipt(result: Mapping[str, Any]) -> dict[str, Any]:
    """Classify one paper cycle without promoting simulation into live truth."""

    status = str(result.get("status", "unknown")).strip().lower()
    stage = str(result.get("stage", "unknown")).strip().lower()
    continuity = result.get("continuity")
    continuity = continuity if isinstance(continuity, Mapping) else {}
    market = result.get("market_observation")
    market = market if isinstance(market, Mapping) else {}

    subject_payload = {
        "lane": result.get("lane"),
        "market_fingerprint": market.get("fingerprint"),
        "decision_fingerprint": continuity.get("decision_fingerprint"),
        "outcome_fingerprint": continuity.get("outcome_fingerprint"),
        "status": status,
        "stage": stage,
    }
    subject_fingerprint = _marker("sw-cycle-subject-v1", subject_payload)

    executed = status == "executed" and stage == "complete"
    if executed:
        execution = _plane(
            ClaimState.VERIFIED,
            "The mock broker returned an execution receipt for this paper cycle.",
        )
        outcome = _plane(
            ClaimState.VERIFIED,
            "The simulated outcome is bound to the current paper-cycle continuity receipt.",
        )
        decision = "MEASURE"
        next_gate = (
            "Measure repeated paper outcomes before changing sizing, promotion, "
            "or capital-allocation policy."
        )
    else:
        execution = _plane(
            ClaimState.BLOCKED,
            f"The paper cycle stopped at the {stage or 'unknown'} stage.",
        )
        outcome = _plane(
            ClaimState.UNKNOWN,
            "No successful paper outcome receipt exists for this cycle.",
        )
        decision = "HOLD_OR_REVIEW"
        next_gate = (
            "Resolve this blocking stage as its own receipt, then re-observe "
            "before retrying the paper cycle."
        )

    payload = {
        "schema": TRUTH_DECISION_CONTRACT,
        "subject": "sleepwealth-paper-cycle",
        "scope": "paper-simulation",
        "authority": "decision_support_only",
        "authorizes": False,
        "subject_fingerprint": subject_fingerprint,
        "fresh": True,
        "truth_planes": {
            "source": _plane(
                ClaimState.OBSERVED,
                "Market input was observed through the lane-bound read-only market path.",
            ),
            "execution": execution,
            "outcome": outcome,
        },
        "decision": decision,
        "proof": {
            "lane": result.get("lane"),
            "status": status,
            "stage": stage,
            "market_fingerprint": market.get("fingerprint"),
            "decision_fingerprint": continuity.get("decision_fingerprint"),
            "outcome_fingerprint": continuity.get("outcome_fingerprint"),
        },
        "confess": [
            "A successful paper execution is not proof of live profitability.",
            "A simulator or provider receipt does not create execution authority.",
            "One successful cycle cannot justify scaling by itself.",
        ],
        "risk": (
            "Paper fills, latency, liquidity, fees, and market impact can differ "
            "from real-world outcomes."
        ),
        "rollback": "Discard this advisory receipt; it mutates no broker, wallet, rule, or ceiling.",
        "next_gate": next_gate,
        "does_not_prove": [
            "live execution authority",
            "real-money movement",
            "future profitability",
            "automatic promotion or ceiling increase",
        ],
    }
    return _finalize(payload)


def capital_decision_fingerprint(
    cycles: Sequence[Mapping[str, Any]],
    rules: Mapping[str, Any],
) -> str:
    payload = {
        "cycles": list(cycles),
        "policy": {
            "ceiling": rules.get("ceiling", {}),
            "capital_ladder": rules.get("capital_ladder", {}),
        },
    }
    return _marker("sw-capital-subject-v1", payload)


def build_capital_truth_receipt(
    history: Mapping[str, Any],
    cycles: Sequence[Mapping[str, Any]],
    rules: Mapping[str, Any],
    *,
    current_fingerprint: str | None = None,
) -> dict[str, Any]:
    """Bind capital-ladder advice to source/execution/outcome truth planes."""

    evidence_fingerprint = capital_decision_fingerprint(cycles, rules)
    current = current_fingerprint or evidence_fingerprint
    fresh = current == evidence_fingerprint
    cycle_count = int(history.get("cycles", 0) or 0)
    latest_status = str(history.get("latest_status", "no_data"))

    if not fresh:
        source = _plane(
            ClaimState.BLOCKED,
            "The current cycle/policy fingerprint does not match the evidence being judged.",
        )
        execution = _plane(
            ClaimState.UNKNOWN,
            "Stale decision evidence cannot prove the current simulated execution state.",
        )
        outcome = _plane(
            ClaimState.UNKNOWN,
            "Historical outcomes remain historical and cannot stand in for current proof.",
        )
        decision = "REOBSERVE"
        next_gate = "Recompute the ladder from the current cycles and policy before deciding."
        confess = [
            "The previous receipt is historical evidence, not fresh proof.",
            "A changed fingerprint invalidates the predecessor decision for current use.",
        ]
    elif cycle_count == 0:
        source = _plane(ClaimState.UNKNOWN, "No paper cycle history was supplied.")
        execution = _plane(ClaimState.UNKNOWN, "No simulated cycle history was observed.")
        outcome = _plane(ClaimState.UNKNOWN, "No outcome exists to judge yet.")
        decision = "MEASURE"
        next_gate = "Record the first bounded paper cycle and recompute the ladder."
        confess = ["No data means no promotion, kill, or profitability claim is justified."]
    else:
        source = _plane(
            ClaimState.VERIFIED,
            "The decision is bound to the supplied ordered paper-cycle history and policy.",
        )
        execution = _plane(
            ClaimState.OBSERVED,
            "Capital usage and timing were measured from simulated cycles.",
        )
        outcome = _plane(
            ClaimState.VERIFIED,
            "The reported paper metrics were recomputed from the supplied cycle history.",
        )
        if bool(history.get("promotion_ready")):
            decision = "PROPOSE_PROMOTION_REVIEW"
            next_gate = (
                "Human review may consider the suggested paper ceiling; "
                "the system cannot raise it automatically."
            )
        elif latest_status == "pause":
            decision = "PROPOSE_TUNE_OR_STOP"
            next_gate = "Review the loss receipt and policy before any further scaling simulation."
        elif latest_status == "blocked":
            decision = "HOLD_OR_REVIEW"
            next_gate = "Resolve the blocked cycle independently before reconsidering scale."
        else:
            decision = "HOLD"
            next_gate = "Keep the current paper ceiling and gather another comparable outcome."
        confess = [
            "Paper ROI and velocity are simulated outcomes, not guaranteed future returns.",
            "Promotion readiness is advisory and cannot mutate the human-owned ceiling.",
        ]

    payload = {
        "schema": TRUTH_DECISION_CONTRACT,
        "subject": "sleepwealth-capital-ladder",
        "scope": "paper-compounding-decision",
        "authority": "decision_support_only",
        "authorizes": False,
        "subject_fingerprint": evidence_fingerprint,
        "current_fingerprint": current,
        "fresh": fresh,
        "truth_planes": {
            "source": source,
            "execution": execution,
            "outcome": outcome,
        },
        "decision": decision,
        "proof": {
            "cycles": cycle_count,
            "qualified_cycles": int(history.get("qualified_cycles", 0) or 0),
            "failed_cycles": int(history.get("failed_cycles", 0) or 0),
            "current_qualified_streak": int(
                history.get("current_qualified_streak", 0) or 0
            ),
            "failure_rate_pct": float(history.get("failure_rate_pct", 0.0) or 0.0),
            "win_rate_pct": float(history.get("win_rate_pct", 0.0) or 0.0),
            "net_roi_pct": float(history.get("net_roi_pct", 0.0) or 0.0),
            "profit_per_capital_day_pct": float(
                history.get("profit_per_capital_day_pct", 0.0) or 0.0
            ),
            "promotion_ready": bool(history.get("promotion_ready")),
            "effective_limit": float(history.get("effective_limit", 0.0) or 0.0),
            "suggested_next_limit": float(
                history.get("suggested_next_limit", 0.0) or 0.0
            ),
        },
        "confess": confess,
        "risk": (
            "Historical paper performance can fail to repeat; scaling decisions must preserve "
            "the configured loss, time, and ceiling boundaries."
        ),
        "rollback": (
            "Discard the advisory receipt or recompute it from prior evidence; "
            "no ceiling or execution state is mutated."
        ),
        "next_gate": next_gate,
        "does_not_prove": [
            "live profitability",
            "future returns",
            "automatic promotion",
            "permission to increase a human-owned ceiling",
            "real-money execution authority",
        ],
    }
    return _finalize(payload)
