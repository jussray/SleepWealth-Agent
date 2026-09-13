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
    grant_id: str = "grant-test",
    action: str = "assert_runtime_truth",
    effect: EffectClass = EffectClass.READ_ONLY,
    consequence: ConsequenceTier = ConsequenceTier.INFORMATIONAL,
) -> AuthorityGrant:
    return AuthorityGrant(
        grant_id=grant_id,
        subject="sleepwealth-paper-ui-runtime",
        allowed_actions=(action,),
        allowed_effects=(effect,),
        max_consequence=consequence,
    )


def runtime(*grants: AuthorityGrant) -> AuthorityRuntime:
    return AuthorityRuntime(grants or (grant(),))


def request(**overrides) -> AuthorityRequest:
    values = {
        "action": "assert_runtime_truth",
        "subject": "sleepwealth-paper-ui-runtime",
        "consequence": ConsequenceTier.INFORMATIONAL,
        "effect": EffectClass.READ_ONLY,
        "evidence": evidence(),
        "current_source_sha": SHA,
        "execution_mode": "practice",
        "grant_id": "grant-test",
    }
    values.update(overrides)
    return AuthorityRequest(**values)


def test_current_evidence_plus_trusted_grant_allows_read_only_claim():
    decision = runtime().evaluate(request())
    assert decision.allowed is True
    assert decision.grant_id == "grant-test"
    assert decision.execution_mode == "practice"
    assert decision.authority_source == "trusted-runtime-registry"
    assert decision.evidence_fingerprint.startswith("evidence-v1:")


def test_evidence_alone_never_grants_authority():
    decision = AuthorityRuntime().evaluate(request())
    assert decision.allowed is False
    assert decision.reason == "authority grant is not trusted by this runtime"


def test_missing_grant_id_fails_closed():
    decision = runtime().evaluate(request(grant_id=None))
    assert decision.allowed is False
    assert decision.reason == "trusted authority grant id is required"


def test_spoofed_grant_id_cannot_self_issue_authority():
    decision = runtime().evaluate(request(grant_id="caller-made-it-up"))
    assert decision.allowed is False
    assert decision.reason == "authority grant is not trusted by this runtime"


def test_stale_evidence_is_denied_even_with_trusted_grant():
    decision = runtime().evaluate(request(current_source_sha="b" * 40))
    assert decision.allowed is False
    assert "stale" in decision.reason


def test_action_scope_cannot_be_inferred_from_evidence():
    decision = runtime().evaluate(request(action="paper_execute"))
    assert decision.allowed is False
    assert "outside the authority grant" in decision.reason


def test_consequence_cannot_exceed_trusted_grant():
    decision = runtime().evaluate(request(consequence=ConsequenceTier.CONSEQUENTIAL))
    assert decision.allowed is False
    assert "consequence exceeds" in decision.reason


def test_effect_cannot_exceed_trusted_grant():
    decision = runtime().evaluate(request(effect=EffectClass.PAPER_SIMULATION))
    assert decision.allowed is False
    assert "effect is outside" in decision.reason


def test_paper_simulation_requires_explicit_paper_grant_and_practice_mode():
    paper_grant = grant(
        grant_id="paper-grant",
        action="paper_execute",
        effect=EffectClass.PAPER_SIMULATION,
        consequence=ConsequenceTier.REVERSIBLE,
    )
    decision = runtime(paper_grant).evaluate(
        request(
            action="paper_execute",
            effect=EffectClass.PAPER_SIMULATION,
            consequence=ConsequenceTier.REVERSIBLE,
            execution_mode="practice",
            grant_id="paper-grant",
        )
    )
    assert decision.allowed is True


def test_observation_only_live_mode_blocks_paper_simulation_even_with_trusted_grant():
    paper_grant = grant(
        grant_id="paper-grant",
        action="paper_execute",
        effect=EffectClass.PAPER_SIMULATION,
        consequence=ConsequenceTier.REVERSIBLE,
    )
    decision = runtime(paper_grant).evaluate(
        request(
            action="paper_execute",
            effect=EffectClass.PAPER_SIMULATION,
            consequence=ConsequenceTier.REVERSIBLE,
            execution_mode="live",
            grant_id="paper-grant",
        )
    )
    assert decision.allowed is False
    assert decision.reason == "live mode is observation-only"


def test_observation_only_live_mode_still_allows_scoped_read_only_claim():
    decision = runtime().evaluate(request(execution_mode="live"))
    assert decision.allowed is True
    assert decision.effect is EffectClass.READ_ONLY


def test_invalid_execution_mode_fails_closed():
    decision = runtime().evaluate(request(execution_mode="mystery"))
    assert decision.allowed is False
    assert "execution mode is invalid" in decision.reason


def test_duplicate_trusted_grant_ids_are_rejected():
    with pytest.raises(ValueError, match="unique"):
        AuthorityRuntime((grant(), grant()))


def test_runtime_has_no_live_money_effect_class():
    assert {effect.value for effect in EffectClass} == {"read-only", "paper-simulation"}
    with pytest.raises(ValueError):
        EffectClass("live-money")
