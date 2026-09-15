from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path

import pytest

from evidence.proof_verifier import ProofVerificationError, verify_proof_manifest


SHA = "a" * 40
SCREENSHOTS = (
    "sleepwealth-stock-desktop.png",
    "sleepwealth-crypto-desktop.png",
    "sleepwealth-stock-mobile.png",
    "sleepwealth-crypto-mobile.png",
)


def _digest(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _write_manifest(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    artifacts = []
    for index, name in enumerate(SCREENSHOTS):
        data = f"canonical-screenshot-{index}".encode()
        (tmp_path / name).write_bytes(data)
        artifacts.append({"name": name, "sha256": hashlib.sha256(data).hexdigest()})
    evidence = {
        "schema": "ultrathink-evidence-object-v1",
        "subject": "sleepwealth-paper-ui-runtime",
        "evidence_type": "playwright-ui-runtime",
        "source_sha": SHA,
        "tested_sha": SHA,
        "authority_ceiling": "paper-only; read-only market observation; no real-money execution",
        "authorizes": False,
        "claims": [
            "stock-lane UI runtime rendered",
            "crypto-lane UI runtime rendered",
            "external crypto observer ceiling rendered",
            "Pump.fun manual public evidence normalized without network authority",
            "paper execution paths exercised",
            "read-only market observation semantics displayed",
        ],
        "does_not_prove": [
            "live execution authority",
            "external broker connectivity",
            "real-money movement",
            "Pump.fun automated network access",
            "SideShift quote or shift authority",
            "SideShift upstream availability",
        ],
        "expires_when": [
            "subject changes",
            "source identity changes",
            "runtime identity changes",
            "evidence bytes change",
            "authority boundary changes",
        ],
        "artifacts": artifacts,
    }
    evidence["fingerprint"] = f"evidence-v1:{_digest(evidence)}"
    checks = [
        {"code": "LIVE_EXECUTION_MODE", "classification": "BLOCKED", "reason": "live mode is observation only", "source": "execution.modes", "blocking": True},
        {"code": "REAL_MONEY_EFFECT_CLASS", "classification": "BLOCKED", "reason": "real-money effect is not representable", "source": "authority.runtime", "blocking": True},
        {"code": "EXTERNAL_BROKER_ADAPTER", "classification": "VERIFIED", "reason": "read-only external observer adapter exists", "source": "broker.factory", "blocking": True},
        {"code": "LIVE_BROKER_SESSION_RECEIPT", "classification": "UNKNOWN", "reason": "no authorized live session receipt", "source": "external-runtime-evidence", "blocking": True},
    ]
    blockers = [check["code"] for check in checks if check["classification"] != "VERIFIED"]
    readiness = {
        "event": "live_money_readiness_evaluated",
        "ready": False,
        "execution_authorized": False,
        "authority_ceiling": "observation-only; no real-money execution",
        "checks": checks,
        "blockers": blockers,
        "external_readonly_observer": {"classification": "UNKNOWN", "accepted": False, "reason": "no read-only external account observer receipt supplied"},
        "fingerprint": _digest(checks),
        "truth": "state only; never authority",
    }
    review = {
        "schema": "sleepwealth-human-live-review-v1",
        "event": "human_live_review_prepared",
        "source_sha": SHA,
        "evidence_fingerprint": evidence["fingerprint"],
        "readiness_fingerprint": readiness["fingerprint"],
        "readiness_ready": False,
        "blockers": blockers,
        "manual_review_required": True,
        "execution_authorized": False,
        "submit_capability": False,
        "money_movement_capability": False,
        "contains_order_instructions": False,
        "allowed_content": ["current readiness classification", "evidence identity", "blocking conditions"],
        "forbidden_content": ["broker credentials", "wallet secrets", "funding instructions", "order submission instructions"],
        "truth": "human review only",
    }
    manifest = {
        "schema": "sleepwealth-playwright-proof-v1",
        "tested_sha": SHA,
        "source_sha": SHA,
        "github_event_sha": SHA,
        "github_event_name": "pull_request",
        "github_run_id": "1",
        "repository": "jussray/SleepWealth-Agent",
        "proof_type": "playwright-ui-runtime",
        "execution_mode": "practice",
        "live_execution": False,
        "market_observation": "read-only",
        "external_crypto_sources": "observation-only",
        "authority": "non-authorizing evidence",
        "claim_scope": list(evidence["claims"]),
        "does_not_prove": list(evidence["does_not_prove"]),
        "screenshots": copy.deepcopy(artifacts),
        "evidence": evidence,
        "authority_decision": {
            "action": "assert_runtime_truth", "allowed": True,
            "authority_source": "trusted-runtime-registry", "consequence": "informational",
            "effect": "read-only", "evidence_fingerprint": evidence["fingerprint"],
            "execution_mode": "practice", "grant_id": "ci-proof-claim-v1",
            "reason": "proof-only grant", "subject": "sleepwealth-paper-ui-runtime",
        },
        "live_money_readiness": readiness,
        "human_live_review": review,
    }
    path = tmp_path / "proof-manifest.json"
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path, manifest


def _rewrite(path: Path, manifest: dict[str, object]) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_independent_verifier_accepts_valid_non_authorizing_package(tmp_path: Path) -> None:
    path, _ = _write_manifest(tmp_path)
    receipt = verify_proof_manifest(path, expected_sha=SHA)
    assert receipt["accepted"] is True
    assert receipt["external_crypto_sources"] == "observation-only"
    assert receipt["execution_authorized"] is False
    assert receipt["submit_capability"] is False
    assert receipt["money_movement_capability"] is False


def test_independent_verifier_rejects_screenshot_byte_tamper(tmp_path: Path) -> None:
    path, _ = _write_manifest(tmp_path)
    (tmp_path / SCREENSHOTS[0]).write_bytes(b"tampered")
    with pytest.raises(ProofVerificationError, match="artifact hash mismatch"):
        verify_proof_manifest(path, expected_sha=SHA)


def test_independent_verifier_rejects_evidence_fingerprint_tamper(tmp_path: Path) -> None:
    path, manifest = _write_manifest(tmp_path)
    manifest["evidence"]["fingerprint"] = "evidence-v1:" + "0" * 64
    _rewrite(path, manifest)
    with pytest.raises(ProofVerificationError, match="evidence fingerprint mismatch"):
        verify_proof_manifest(path, expected_sha=SHA)


def test_independent_verifier_rejects_readiness_fingerprint_tamper(tmp_path: Path) -> None:
    path, manifest = _write_manifest(tmp_path)
    manifest["live_money_readiness"]["fingerprint"] = "0" * 64
    _rewrite(path, manifest)
    with pytest.raises(ProofVerificationError, match="readiness fingerprint mismatch"):
        verify_proof_manifest(path, expected_sha=SHA)


def test_independent_verifier_rejects_cross_wired_human_review(tmp_path: Path) -> None:
    path, manifest = _write_manifest(tmp_path)
    manifest["human_live_review"]["evidence_fingerprint"] = "evidence-v1:" + "f" * 64
    _rewrite(path, manifest)
    with pytest.raises(ProofVerificationError, match="evidence fingerprint is cross-wired"):
        verify_proof_manifest(path, expected_sha=SHA)


def test_independent_verifier_rejects_execution_capability_flip(tmp_path: Path) -> None:
    path, manifest = _write_manifest(tmp_path)
    manifest["human_live_review"]["submit_capability"] = True
    _rewrite(path, manifest)
    with pytest.raises(ProofVerificationError, match="submit_capability must be false"):
        verify_proof_manifest(path, expected_sha=SHA)


def test_independent_verifier_rejects_exact_head_drift(tmp_path: Path) -> None:
    path, _ = _write_manifest(tmp_path)
    with pytest.raises(ProofVerificationError, match="expected exact head"):
        verify_proof_manifest(path, expected_sha="b" * 40)


def test_independent_verifier_rejects_unknown_evidence_artifact(tmp_path: Path) -> None:
    path, manifest = _write_manifest(tmp_path)
    manifest["evidence"]["artifacts"].append({"name": "rogue.png", "sha256": "0" * 64})
    _rewrite(path, manifest)
    with pytest.raises(ProofVerificationError, match="exactly the four canonical"):
        verify_proof_manifest(path, expected_sha=SHA)


def test_independent_verifier_rejects_authority_effect_expansion(tmp_path: Path) -> None:
    path, manifest = _write_manifest(tmp_path)
    manifest["authority_decision"]["effect"] = "paper-simulation"
    _rewrite(path, manifest)
    with pytest.raises(ProofVerificationError, match="outside the proof-only authority boundary"):
        verify_proof_manifest(path, expected_sha=SHA)


def test_independent_verifier_rejects_external_crypto_authority_drift(tmp_path: Path) -> None:
    path, manifest = _write_manifest(tmp_path)
    manifest["external_crypto_sources"] = "trade-capable"
    _rewrite(path, manifest)
    with pytest.raises(ProofVerificationError, match="must remain observation-only"):
        verify_proof_manifest(path, expected_sha=SHA)


def test_independent_verifier_rejects_dropped_sideshift_nonclaim(tmp_path: Path) -> None:
    path, manifest = _write_manifest(tmp_path)
    manifest["evidence"]["does_not_prove"].remove("SideShift quote or shift authority")
    manifest["does_not_prove"].remove("SideShift quote or shift authority")
    canonical = dict(manifest["evidence"])
    canonical.pop("fingerprint")
    manifest["evidence"]["fingerprint"] = f"evidence-v1:{_digest(canonical)}"
    manifest["authority_decision"]["evidence_fingerprint"] = manifest["evidence"]["fingerprint"]
    manifest["human_live_review"]["evidence_fingerprint"] = manifest["evidence"]["fingerprint"]
    _rewrite(path, manifest)
    with pytest.raises(ProofVerificationError, match="missing required external/live-money non-claims"):
        verify_proof_manifest(path, expected_sha=SHA)
