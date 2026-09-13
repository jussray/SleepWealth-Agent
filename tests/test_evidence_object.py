import pytest

from evidence import EvidenceArtifact, EvidenceObjectV1


ARTIFACT_SHA = "a" * 64


def make_evidence(**overrides):
    values = {
        "subject": "sleepwealth-playwright-proof",
        "evidence_type": "playwright-ui-runtime",
        "source_sha": "abc123",
        "tested_sha": "abc123",
        "authority_ceiling": "paper-only; read-only market observation",
        "claims": ("stock lane rendered", "crypto lane rendered"),
        "does_not_prove": ("live execution authority", "real-money movement"),
        "artifacts": (EvidenceArtifact("proof.png", ARTIFACT_SHA),),
    }
    values.update(overrides)
    return EvidenceObjectV1(**values)


def test_evidence_object_is_deterministic_and_non_authorizing():
    first = make_evidence()
    second = make_evidence()

    assert first.authorizes is False
    assert first.fingerprint == second.fingerprint
    assert first.fingerprint.startswith("evidence-v1:")
    assert first.to_dict()["artifacts"] == [{"name": "proof.png", "sha256": ARTIFACT_SHA}]


def test_exact_head_mismatch_is_rejected():
    with pytest.raises(ValueError, match="source_sha and tested_sha must match"):
        make_evidence(tested_sha="different")


def test_evidence_cannot_grant_authority():
    with pytest.raises(ValueError, match="non-authorizing"):
        make_evidence(authorizes=True)


def test_duplicate_artifact_names_are_rejected():
    artifact = EvidenceArtifact("same.png", ARTIFACT_SHA)
    with pytest.raises(ValueError, match="artifact names must be unique"):
        make_evidence(artifacts=(artifact, artifact))


def test_artifact_digest_must_be_sha256():
    with pytest.raises(ValueError, match="64-character hexadecimal"):
        EvidenceArtifact("proof.png", "not-a-digest")
