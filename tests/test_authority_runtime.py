import pytest

from authority import (
    AuthorityGrant,
    AuthorityRequest,
    AuthorityRuntime,
    ConsequenceTier,
    EffectClass,
)
from evidence import EvidenceObjectV1


SHA = "a" * 40


def evidence() -> EvidenceObjectV1:
    return EvidenceObjectV1(
        subject="sleepwealth-paper-ui-runtime",
        evidence_type="playwright-ui-runtime",
        source_sha=SHA,
        tested_sha=SHA,
        authority_ceiling="paper-only; read-only market observation; no real-money execution",
        claims=("paper runtime proved",),
        does_not_prove=("live execution authority",),
    )


def grant(
    *,
    action: str = "assert_runtime_truth",
    effect: EffectClass = EffectClass.READ_ONLY,
    consequence: ConsequenceTier = ConsequenceTier.INFORMATIONAL,
) -> AuthorityGrant:
    return AuthorityGrant(
        grant_id="grant-test",
        subject="sleepwealth-paper-ui-runtime",
        allowed_actions=(action,),
        allowed_effects=(effect,),
        max_consequence=consequence,
    )


def request(**overrides) -> AuthorityRequest:
    values = {
        "action": "assert_runtime_truth",
        "subject": "sleepwealth-paper-ui-runtime",
        "consequence": ConsequenceTier.INFORMATIONAL,
        "effect": EffectClass.READ_ONLY,
        "evidence": evidence(),
        "current_source_sha": SHA,
        "grant": grant(),
    }
    values.update(overrides)
    return AuthorityRequest(**values)


def test_current_evidence_plus_independent_grant_allows_read_only_claim():
    decision = AuthorityRuntime().evaluate(request())
    assert decision.allowed is True
    assert decision.grant_id == "grant-test"
    assert decision.authority_source == "independent-grant"
    assert decision.evidence_fingerprint.startswith("evidence-v1:")


def test_evidence_alone_never_grants_authority():
    decision = AuthorityRuntime().evaluate(request(grant=None))
    assert decision.allowed is False
    assert decision.reason == "independent authority grant is required"


def test_stale_evidence_is_denied_even_with_grant():
    decision = AuthorityRuntime().evaluate(request(current_source_sha="b" * 40))
    assert decision.allowed is False
    assert "stale" in decision.reason


def test_action_scope_cannot_be_inferred_from_evidence():
    decision = AuthorityRuntime().evaluate(request(action="paper_execute"))
    assert decision.allowed is False
    assert "outside the authority grant" in decision.reason


def test_consequence_cannot_exceed_independent_grant():
    decision = AuthorityRuntime().evaluate(
        request(consequence=ConsequenceTier.CONSEQUENTIAL)
    )
    assert decision.allowed is False
    assert "consequence exceeds" in decision.reason


def test_effect_cannot_exceed_independent_grant():
    decision = AuthorityRuntime().evaluate(
        request(effect=EffectClass.PAPER_SIMULATION)
    )
    assert decision.allowed is False
    assert "effect is outside" in decision.reason


def test_paper_simulation_requires_explicit_paper_grant():
    decision = AuthorityRuntime().evaluate(
        request(
            action="paper_execute",
            effect=EffectClass.PAPER_SIMULATION,
            consequence=ConsequenceTier.REVERSIBLE,
            grant=grant(
                action="paper_execute",
                effect=EffectClass.PAPER_SIMULATION,
                consequence=ConsequenceTier.REVERSIBLE,
            ),
        )
    )
    assert decision.allowed is True


def test_runtime_has_no_live_money_effect_class():
    assert {effect.value for effect in EffectClass} == {"read-only", "paper-simulation"}
    with pytest.raises(ValueError):
        EffectClass("live-money")
