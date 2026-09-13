from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum

from evidence import EvidenceObjectV1
from execution.modes import get_execution_mode


class ConsequenceTier(IntEnum):
    INFORMATIONAL = 0
    REVERSIBLE = 1
    CONSEQUENTIAL = 2
    IRREVERSIBLE = 3


class EffectClass(StrEnum):
    READ_ONLY = "read-only"
    PAPER_SIMULATION = "paper-simulation"


@dataclass(frozen=True, slots=True)
class AuthorityGrant:
    grant_id: str
    subject: str
    allowed_actions: tuple[str, ...]
    allowed_effects: tuple[EffectClass, ...]
    max_consequence: ConsequenceTier

    def __post_init__(self) -> None:
        if not self.grant_id.strip():
            raise ValueError("grant_id must not be empty")
        if not self.subject.strip():
            raise ValueError("subject must not be empty")
        if not self.allowed_actions:
            raise ValueError("allowed_actions must not be empty")
        if not self.allowed_effects:
            raise ValueError("allowed_effects must not be empty")
        if any(not action.strip() for action in self.allowed_actions):
            raise ValueError("allowed_actions must not contain empty values")


@dataclass(frozen=True, slots=True)
class AuthorityRequest:
    action: str
    subject: str
    consequence: ConsequenceTier
    effect: EffectClass
    evidence: EvidenceObjectV1
    current_source_sha: str
    execution_mode: str
    grant: AuthorityGrant | None = None


@dataclass(frozen=True, slots=True)
class AuthorityDecision:
    allowed: bool
    reason: str
    action: str
    subject: str
    consequence: ConsequenceTier
    effect: EffectClass
    execution_mode: str
    evidence_fingerprint: str
    grant_id: str | None
    authority_source: str = "independent-grant"

    def to_dict(self) -> dict[str, object]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "action": self.action,
            "subject": self.subject,
            "consequence": self.consequence.name.lower(),
            "effect": self.effect.value,
            "execution_mode": self.execution_mode,
            "evidence_fingerprint": self.evidence_fingerprint,
            "grant_id": self.grant_id,
            "authority_source": self.authority_source,
        }


class AuthorityRuntime:
    """Consumes evidence without allowing evidence to create authority.

    The runtime exposes only read-only and paper-simulation effects. Repository
    execution mode is checked independently from the grant. Real-money, wallet,
    funding, transfer, mint, and live trading effects are not representable.
    """

    def evaluate(self, request: AuthorityRequest) -> AuthorityDecision:
        evidence = request.evidence
        grant = request.grant

        try:
            mode = get_execution_mode(request.execution_mode)
        except ValueError as exc:
            return self._deny(request, f"execution mode is invalid: {exc}")

        def deny(reason: str) -> AuthorityDecision:
            return self._deny(request, reason, mode.name)

        if not request.action.strip():
            return deny("requested action is empty")
        if not request.subject.strip():
            return deny("requested subject is empty")
        if request.current_source_sha != evidence.source_sha:
            return deny("evidence is stale for the current source identity")
        if evidence.tested_sha != evidence.source_sha:
            return deny("evidence is not exact-head bound")
        if request.subject != evidence.subject:
            return deny("evidence subject does not match requested subject")
        if evidence.authorizes:
            return deny("evidence must never grant authority")
        if request.effect is EffectClass.PAPER_SIMULATION and not mode.simulated_execution_enabled:
            return deny(f"{mode.name} mode is observation-only")
        if request.effect is EffectClass.READ_ONLY and mode.market_observation != "read-only":
            return deny(f"{mode.name} mode does not permit read-only observation")
        if grant is None:
            return deny("independent authority grant is required")
        if grant.subject != request.subject:
            return deny("authority grant subject does not match requested subject")
        if request.action not in grant.allowed_actions:
            return deny("requested action is outside the authority grant")
        if request.effect not in grant.allowed_effects:
            return deny("requested effect is outside the authority grant")
        if request.consequence > grant.max_consequence:
            return deny("requested consequence exceeds the authority grant")

        return AuthorityDecision(
            allowed=True,
            reason="current evidence, execution mode, and independent authority permit the requested action",
            action=request.action,
            subject=request.subject,
            consequence=request.consequence,
            effect=request.effect,
            execution_mode=mode.name,
            evidence_fingerprint=evidence.fingerprint,
            grant_id=grant.grant_id,
        )

    @staticmethod
    def _deny(
        request: AuthorityRequest,
        reason: str,
        execution_mode: str | None = None,
    ) -> AuthorityDecision:
        return AuthorityDecision(
            allowed=False,
            reason=reason,
            action=request.action,
            subject=request.subject,
            consequence=request.consequence,
            effect=request.effect,
            execution_mode=execution_mode or str(request.execution_mode),
            evidence_fingerprint=request.evidence.fingerprint,
            grant_id=request.grant.grant_id if request.grant else None,
        )
