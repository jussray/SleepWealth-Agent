from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum, StrEnum

from evidence import EvidenceObjectV1


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
    grant: AuthorityGrant | None = None


@dataclass(frozen=True, slots=True)
class AuthorityDecision:
    allowed: bool
    reason: str
    action: str
    subject: str
    consequence: ConsequenceTier
    effect: EffectClass
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
            "evidence_fingerprint": self.evidence_fingerprint,
            "grant_id": self.grant_id,
            "authority_source": self.authority_source,
        }


class AuthorityRuntime:
    """Consumes evidence without letting evidence become authority.

    This runtime intentionally exposes only read-only and paper-simulation
    effects. Real-money execution, wallet movement, funding, minting, and other
    live financial effects are outside this runtime's representable authority.
    """

    def evaluate(self, request: AuthorityRequest) -> AuthorityDecision:
        evidence = request.evidence
        grant = request.grant

        def deny(reason: str) -> AuthorityDecision:
            return AuthorityDecision(
                allowed=False,
                reason=reason,
                action=request.action,
                subject=request.subject,
                consequence=request.consequence,
                effect=request.effect,
                evidence_fingerprint=evidence.fingerprint,
                grant_id=grant.grant_id if grant else None,
            )

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
            reason="evidence is current and independent authority permits the requested action",
            action=request.action,
            subject=request.subject,
            consequence=request.consequence,
            effect=request.effect,
            evidence_fingerprint=evidence.fingerprint,
            grant_id=grant.grant_id,
        )
