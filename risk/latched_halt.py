from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class HaltState(StrEnum):
    ACTIVE = "active"
    HALTED = "halted"


class EvidenceState(StrEnum):
    VERIFIED = "verified"
    INFERRED = "inferred"
    UNKNOWN = "unknown"
    BLOCKED = "blocked"


@dataclass(frozen=True, slots=True)
class RiskSignal:
    name: str
    evidence: EvidenceState
    risk_score: float | None
    gain_score: float | None
    detail: str = ""

    def is_halt_trigger(self) -> bool:
        # Missing or blocked evidence can never become permission to keep spending.
        if self.evidence in {EvidenceState.UNKNOWN, EvidenceState.BLOCKED}:
            return True
        if self.risk_score is None or self.gain_score is None:
            return True
        return self.risk_score > self.gain_score

    def is_recovery_evidence(self) -> bool:
        return (
            self.evidence is EvidenceState.VERIFIED
            and self.risk_score is not None
            and self.gain_score is not None
            and self.risk_score <= self.gain_score
        )


@dataclass(frozen=True, slots=True)
class HaltReceipt:
    project: str
    state: HaltState
    trigger: str
    human_reauthorization_required: bool
    observation_authority: bool
    execution_authority: bool


@dataclass(frozen=True, slots=True)
class RecoveryNotice:
    project: str
    classification: str
    consecutive_verified_observations: int
    human_reauthorization_required: bool
    execution_authority: bool


class LatchedRiskHalt:
    """Fail-closed project circuit breaker.

    The machine may latch a project into HALTED when risk outruns gain or when
    required evidence becomes UNKNOWN/BLOCKED. While halted it retains read-only
    observation authority so it can notice material recovery. It cannot clear
    the latch itself; only explicit human reauthorization can resume execution.
    """

    def __init__(self, project: str, *, recovery_observations: int = 3) -> None:
        if not project.strip():
            raise ValueError("project is required")
        if recovery_observations < 1:
            raise ValueError("recovery_observations must be positive")
        self.project = project.strip()
        self.recovery_observations = recovery_observations
        self.state = HaltState.ACTIVE
        self._recovery_streak = 0
        self._trigger = ""

    @property
    def execution_authority(self) -> bool:
        return self.state is HaltState.ACTIVE

    @property
    def observation_authority(self) -> bool:
        return True

    def observe(self, signals: tuple[RiskSignal, ...]) -> HaltReceipt | RecoveryNotice | None:
        if not signals:
            return self._latch("required risk evidence is missing")

        triggers = [signal for signal in signals if signal.is_halt_trigger()]
        if triggers:
            self._recovery_streak = 0
            trigger = "; ".join(f"{signal.name}:{signal.evidence.value}" for signal in triggers)
            return self._latch(trigger)

        if self.state is HaltState.HALTED:
            if all(signal.is_recovery_evidence() for signal in signals):
                self._recovery_streak += 1
            else:
                self._recovery_streak = 0
            if self._recovery_streak >= self.recovery_observations:
                return RecoveryNotice(
                    project=self.project,
                    classification="RECOVERY_CANDIDATE",
                    consecutive_verified_observations=self._recovery_streak,
                    human_reauthorization_required=True,
                    execution_authority=False,
                )
        return None

    def human_reauthorize(self, *, approved: bool) -> HaltReceipt:
        if not approved:
            return HaltReceipt(
                project=self.project,
                state=self.state,
                trigger=self._trigger or "human reauthorization declined",
                human_reauthorization_required=self.state is HaltState.HALTED,
                observation_authority=True,
                execution_authority=self.execution_authority,
            )
        if self.state is HaltState.HALTED and self._recovery_streak < self.recovery_observations:
            raise PermissionError("recovery persistence gate has not been satisfied")
        self.state = HaltState.ACTIVE
        self._recovery_streak = 0
        self._trigger = ""
        return HaltReceipt(
            project=self.project,
            state=self.state,
            trigger="human reauthorization",
            human_reauthorization_required=False,
            observation_authority=True,
            execution_authority=True,
        )

    def _latch(self, trigger: str) -> HaltReceipt:
        self.state = HaltState.HALTED
        self._trigger = trigger
        return HaltReceipt(
            project=self.project,
            state=HaltState.HALTED,
            trigger=trigger,
            human_reauthorization_required=True,
            observation_authority=True,
            execution_authority=False,
        )
