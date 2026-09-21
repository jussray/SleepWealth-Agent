"""Evidence-led founder capital router for SleepWealth decision support.

MONEYROUTER implements the founder's "Don't Fall in Love" loop:
DISCOVER -> VERIFY -> MONEY PATH -> COMPARE -> TEST -> MEASURE -> COMPOUND/KILL.

This module is deliberately non-authorizing. A receipt can recommend a bounded test,
but it never grants spending, brokerage, wallet, signing, transfer, or live-execution
authority. Existing SleepWealth approval/risk/authority gates remain stronger.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from math import isfinite
from typing import Iterable, Literal

Stage = Literal[
    "DISCOVER",
    "VERIFY",
    "MONEY_PATH",
    "COMPARE",
    "TEST",
    "MEASURE",
    "COMPOUND",
    "KILL",
]
Decision = Literal["BLOCK", "DISCOVER", "VERIFY", "TEST", "COMPOUND", "KILL"]


@dataclass(frozen=True, slots=True)
class Evidence:
    id: str
    kind: str
    verified: bool
    source: str
    timestamp: str
    value: float | None = None


@dataclass(frozen=True, slots=True)
class MoneyPath:
    payer: str
    offer: str
    price: float
    unit_cost: float
    conversion_probability: float
    repeatable: bool
    proven: bool = False
    cycle_days: float = 30.0

    @property
    def gross_profit(self) -> float:
        return self.price - self.unit_cost


@dataclass(frozen=True, slots=True)
class Opportunity:
    id: str
    name: str
    project: str
    stage: Stage
    evidence: tuple[Evidence, ...]
    capital_required: float
    founder_hours_required: float
    max_loss: float
    reversibility_risk: float
    compounding_value: float
    successful_cycles: int
    repeated_cycles: int
    kill_after_failures: int
    failures: int
    money_path: MoneyPath | None = None
    uses_borrowing: bool = False
    uses_leverage: bool = False
    chasing_loss: bool = False


@dataclass(frozen=True, slots=True)
class FinancialState:
    liquid_cash: float
    survival_floor: float
    safety_buffer: float
    experiment_budget: float


@dataclass(frozen=True, slots=True)
class RouterReceipt:
    receipt_version: int
    opportunity_id: str
    project: str
    decision: Decision
    comparison_score: float
    expected_net_value: float
    capital_velocity: float
    reasons: tuple[str, ...]
    next_test: str | None
    stop_condition: str | None
    evidence_ids: tuple[str, ...]
    previous_cookie_hash: str | None
    continuity_cookie_hash: str
    fingerprint: str
    authority: str
    authorizes_spending: bool
    authorizes_execution: bool
    real_money: bool
    generated_at: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


def _finite_nonnegative(name: str, value: float) -> float:
    value = float(value)
    if not isfinite(value) or value < 0:
        raise ValueError(f"{name} must be finite and non-negative")
    return value


def _canonical_digest(payload: object) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def deployable_cash(finances: FinancialState) -> float:
    liquid = _finite_nonnegative("liquid_cash", finances.liquid_cash)
    floor = _finite_nonnegative("survival_floor", finances.survival_floor)
    buffer = _finite_nonnegative("safety_buffer", finances.safety_buffer)
    return max(0.0, liquid - floor - buffer)


def _verified_evidence(opportunity: Opportunity) -> tuple[Evidence, ...]:
    return tuple(item for item in opportunity.evidence if item.verified)


def expected_net_value(opportunity: Opportunity) -> float:
    path = opportunity.money_path
    if path is None:
        return 0.0
    probability = float(path.conversion_probability)
    if not isfinite(probability) or probability < 0 or probability > 1:
        raise ValueError("conversion_probability must be between 0 and 1")
    price = _finite_nonnegative("price", path.price)
    unit_cost = _finite_nonnegative("unit_cost", path.unit_cost)
    required = _finite_nonnegative("capital_required", opportunity.capital_required)
    return (price - unit_cost) * probability - required


def capital_velocity(opportunity: Opportunity) -> float:
    """Expected gross-profit dollars per cycle day, before fixed experiment cost."""

    path = opportunity.money_path
    if path is None:
        return 0.0
    cycle_days = float(path.cycle_days)
    if not isfinite(cycle_days) or cycle_days <= 0:
        raise ValueError("cycle_days must be finite and greater than zero")
    probability = float(path.conversion_probability)
    if not isfinite(probability) or probability < 0 or probability > 1:
        raise ValueError("conversion_probability must be between 0 and 1")
    return (path.gross_profit * probability) / cycle_days


def score_opportunity(opportunity: Opportunity) -> float:
    """Coarse comparison score; never an execution or spending authority signal."""

    verified_count = len(_verified_evidence(opportunity))
    expected = expected_net_value(opportunity)
    velocity = capital_velocity(opportunity)

    evidence_score = min(verified_count * 8.0, 32.0)
    repeatability_score = (
        18.0 if opportunity.money_path and opportunity.money_path.repeatable else 0.0
    )
    proof_score = (
        30.0
        if opportunity.repeated_cycles >= 2
        else 15.0
        if opportunity.successful_cycles
        else 0.0
    )
    compounding_score = max(0.0, min(float(opportunity.compounding_value), 1.0)) * 20.0
    risk_penalty = max(0.0, min(float(opportunity.reversibility_risk), 1.0)) * 20.0
    capital_penalty = min(
        _finite_nonnegative("capital_required", opportunity.capital_required) / 100.0, 25.0
    )
    time_penalty = min(
        _finite_nonnegative("founder_hours_required", opportunity.founder_hours_required)
        * 1.5,
        20.0,
    )
    failure_penalty = max(0, int(opportunity.failures)) * 10.0

    economics_signal = max(-25.0, min(expected, 25.0))
    velocity_signal = max(-10.0, min(velocity, 10.0))

    return round(
        economics_signal
        + velocity_signal
        + evidence_score
        + repeatability_score
        + proof_score
        + compounding_score
        - risk_penalty
        - capital_penalty
        - time_penalty
        - failure_penalty,
        2,
    )


def _make_receipt(
    opportunity: Opportunity,
    decision: Decision,
    reasons: Iterable[str],
    *,
    previous_cookie_hash: str | None,
    next_test: str | None = None,
    stop_condition: str | None = None,
) -> RouterReceipt:
    generated_at = datetime.now(timezone.utc).isoformat()
    evidence_ids = tuple(sorted(item.id for item in opportunity.evidence if item.verified))
    expected = round(expected_net_value(opportunity), 2)
    velocity = round(capital_velocity(opportunity), 6)
    score = score_opportunity(opportunity)

    cookie_payload = {
        "version": 1,
        "opportunity_id": opportunity.id,
        "project": opportunity.project,
        "stage": opportunity.stage,
        "decision": decision,
        "previous_cookie_hash": previous_cookie_hash,
        "evidence_ids": evidence_ids,
        "capital_required": round(float(opportunity.capital_required), 2),
        "max_loss": round(float(opportunity.max_loss), 2),
        "generated_at": generated_at,
    }
    cookie_hash = _canonical_digest(cookie_payload)

    fingerprint_payload = {
        "opportunity": asdict(opportunity),
        "decision": decision,
        "evidence_ids": evidence_ids,
        "expected_net_value": expected,
        "capital_velocity": velocity,
        "previous_cookie_hash": previous_cookie_hash,
    }
    fingerprint = _canonical_digest(fingerprint_payload)

    return RouterReceipt(
        receipt_version=1,
        opportunity_id=opportunity.id,
        project=opportunity.project,
        decision=decision,
        comparison_score=score,
        expected_net_value=expected,
        capital_velocity=velocity,
        reasons=tuple(reasons),
        next_test=next_test,
        stop_condition=stop_condition,
        evidence_ids=evidence_ids,
        previous_cookie_hash=previous_cookie_hash,
        continuity_cookie_hash=cookie_hash,
        fingerprint=fingerprint,
        authority="decision-support-only",
        authorizes_spending=False,
        authorizes_execution=False,
        real_money=False,
        generated_at=generated_at,
    )


def decide(
    opportunity: Opportunity,
    finances: FinancialState,
    *,
    previous_cookie_hash: str | None = None,
) -> RouterReceipt:
    """Return a fail-closed, non-authorizing COMPOUND/KILL decision receipt."""

    available = deployable_cash(finances)
    required = _finite_nonnegative("capital_required", opportunity.capital_required)
    experiment_budget = _finite_nonnegative("experiment_budget", finances.experiment_budget)

    if opportunity.uses_borrowing or opportunity.uses_leverage or opportunity.chasing_loss:
        return _make_receipt(
            opportunity,
            "BLOCK",
            (
                "The proposed test depends on borrowing, leverage, or chasing a prior loss.",
                "Redesign the test so downside is bounded by already-available experiment capital.",
            ),
            previous_cookie_hash=previous_cookie_hash,
        )

    if required > experiment_budget:
        return _make_receipt(
            opportunity,
            "BLOCK",
            (
                f"Next test requires ${required:.2f}; experiment ceiling is ${experiment_budget:.2f}.",
                "Shrink the test before allocating capital.",
            ),
            previous_cookie_hash=previous_cookie_hash,
        )

    if required > available:
        return _make_receipt(
            opportunity,
            "BLOCK",
            (
                f"Only ${available:.2f} is deployable above the survival floor and safety buffer.",
                "The proposed test would consume protected cash.",
            ),
            previous_cookie_hash=previous_cookie_hash,
        )

    if opportunity.failures >= opportunity.kill_after_failures:
        return _make_receipt(
            opportunity,
            "KILL",
            (
                f"Failure limit reached: {opportunity.failures}/{opportunity.kill_after_failures}.",
                "Stop allocating resources unless materially new evidence changes the thesis.",
            ),
            previous_cookie_hash=previous_cookie_hash,
        )

    if opportunity.money_path is None:
        return _make_receipt(
            opportunity,
            "DISCOVER",
            (
                "No explicit payer, offer, and price are defined.",
                "Define the money path before additional build work.",
            ),
            previous_cookie_hash=previous_cookie_hash,
        )

    path = opportunity.money_path
    if not path.payer.strip() or not path.offer.strip():
        return _make_receipt(
            opportunity,
            "DISCOVER",
            ("The money path is incomplete: payer and offer must be explicit.",),
            previous_cookie_hash=previous_cookie_hash,
        )

    if not _verified_evidence(opportunity):
        return _make_receipt(
            opportunity,
            "VERIFY",
            (
                "A money path exists but no verified external evidence is attached.",
                "Obtain one real proof before expanding implementation.",
            ),
            previous_cookie_hash=previous_cookie_hash,
        )

    if path.gross_profit <= 0:
        return _make_receipt(
            opportunity,
            "KILL",
            (
                "The proposed sale has non-positive gross margin.",
                "Do not scale a money path that loses money before fixed costs.",
            ),
            previous_cookie_hash=previous_cookie_hash,
        )

    if opportunity.repeated_cycles < 2:
        return _make_receipt(
            opportunity,
            "TEST",
            ("The complete money cycle has not repeated independently at least twice.",),
            previous_cookie_hash=previous_cookie_hash,
            next_test=(
                "Run the smallest paid experiment that exercises offer -> payment -> "
                "fulfillment -> retained margin."
            ),
            stop_condition=(
                "Stop at the configured failure threshold or if unit economics turn non-positive."
            ),
        )

    if expected_net_value(opportunity) <= 0:
        return _make_receipt(
            opportunity,
            "KILL",
            (
                "Repeated activity exists, but expected net economics are non-positive after experiment cost.",
                "Do not scale negative expected economics.",
            ),
            previous_cookie_hash=previous_cookie_hash,
        )

    if not path.repeatable:
        return _make_receipt(
            opportunity,
            "TEST",
            ("Revenue evidence exists, but repeatability is not established.",),
            previous_cookie_hash=previous_cookie_hash,
            next_test="Seek one additional independent buyer through the same money path.",
            stop_condition="Return to VERIFY or KILL if the mechanism does not repeat.",
        )

    return _make_receipt(
        opportunity,
        "COMPOUND",
        (
            "Protected cash remains intact.",
            "Verified evidence exists.",
            "The money cycle repeated at least twice.",
            "Expected economics are positive.",
            "The mechanism is marked repeatable.",
        ),
        previous_cookie_hash=previous_cookie_hash,
        next_test="Increase allocation by one bounded step and re-measure the same money cycle.",
        stop_condition=(
            "Revert to TEST or KILL if margin, conversion, continuity, or evidence quality deteriorates."
        ),
    )


def rank_opportunities(
    opportunities: Iterable[Opportunity],
    finances: FinancialState,
) -> list[tuple[Opportunity, RouterReceipt]]:
    priority: dict[Decision, int] = {
        "COMPOUND": 6,
        "TEST": 5,
        "VERIFY": 4,
        "DISCOVER": 3,
        "BLOCK": 2,
        "KILL": 1,
    }
    ranked = [(opportunity, decide(opportunity, finances)) for opportunity in opportunities]
    return sorted(
        ranked,
        key=lambda item: (priority[item[1].decision], item[1].comparison_score),
        reverse=True,
    )
