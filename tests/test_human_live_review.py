import pytest

from evidence import EvidenceObjectV1
from gate.human_live_review import HumanLiveReviewV1, prepare_human_live_review


SHA = "a" * 40


def evidence() -> EvidenceObjectV1:
    return EvidenceObjectV1(
        subject="sleepwealth-paper-ui-runtime",
        evidence_type="playwright-ui-runtime",
        source_sha=SHA,
        tested_sha=SHA,
        authority_ceiling="paper-only; read-only market observation; no real-money execution",
        claims=("runtime proof exists",),
        does_not_prove=("live execution authority",),
    )


def readiness(*, ready=False, execution_authorized=False) -> dict[str, object]:
    return {
        "event": "live_money_readiness_evaluated",
        "ready": ready,
        "execution_authorized": execution_authorized,
        "fingerprint": "b" * 64,
        "blockers": ["LIVE_EXECUTION_MODE", "REAL_MONEY_EFFECT_CLASS"],
    }


def test_review_receipt_binds_current_evidence_without_execution_capability():
    receipt = prepare_human_live_review(evidence(), readiness(), current_source_sha=SHA)
    payload = receipt.to_dict()
    assert payload["manual_review_required"] is True
    assert payload["execution_authorized"] is False
    assert payload["submit_capability"] is False
    assert payload["money_movement_capability"] is False
    assert payload["contains_order_instructions"] is False
    assert payload["source_sha"] == SHA
    assert str(payload["evidence_fingerprint"]).startswith("evidence-v1:")


def test_stale_evidence_fails_closed():
    with pytest.raises(ValueError, match="stale"):
        prepare_human_live_review(evidence(), readiness(), current_source_sha="c" * 40)


def test_authorizing_readiness_receipt_is_rejected():
    with pytest.raises(ValueError, match="non-authorizing"):
        prepare_human_live_review(
            evidence(), readiness(execution_authorized=True), current_source_sha=SHA
        )


def test_even_ready_state_does_not_create_submission_or_money_movement():
    receipt = prepare_human_live_review(evidence(), readiness(ready=True), current_source_sha=SHA)
    payload = receipt.to_dict()
    assert payload["readiness_ready"] is True
    assert payload["execution_authorized"] is False
    assert payload["submit_capability"] is False
    assert payload["money_movement_capability"] is False


def test_receipt_constructor_cannot_be_flipped_to_executable():
    with pytest.raises(ValueError, match="cannot grant execution"):
        HumanLiveReviewV1(
            source_sha=SHA,
            evidence_fingerprint="evidence-v1:" + "c" * 64,
            readiness_fingerprint="b" * 64,
            blockers=(),
            readiness_ready=True,
            execution_authorized=True,
        )


def test_review_receipt_keeps_broker_eligibility_provider_scoped():
    payload = prepare_human_live_review(
        evidence(), readiness(), current_source_sha=SHA
    ).to_dict()

    assert "broker-provider account eligibility or permission status" in payload["allowed_content"]
    assert any(
        "unrelated product" in item and "broker eligibility" in item
        for item in payload["forbidden_content"]
    )
    assert payload["execution_authorized"] is False
