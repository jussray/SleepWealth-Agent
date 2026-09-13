from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


class ProofVerificationError(ValueError):
    """Raised when a proof package violates an independent verification invariant."""


EXPECTED_SCREENSHOTS = {
    "sleepwealth-stock-desktop.png",
    "sleepwealth-crypto-desktop.png",
    "sleepwealth-stock-mobile.png",
    "sleepwealth-crypto-mobile.png",
}
EXPECTED_EVIDENCE_SCHEMA = "ultrathink-evidence-object-v1"
EXPECTED_MANIFEST_SCHEMA = "sleepwealth-playwright-proof-v1"
EXPECTED_REVIEW_SCHEMA = "sleepwealth-human-live-review-v1"
EXPECTED_EVIDENCE_AUTHORITY_CEILING = (
    "paper-only; read-only market observation; no real-money execution"
)
REQUIRED_NONCLAIMS = {
    "live execution authority",
    "external broker connectivity",
    "real-money movement",
    "Pump.fun automated network access",
    "SideShift quote or shift authority",
    "SideShift upstream availability",
}


def _reject(message: str) -> None:
    raise ProofVerificationError(message)


def _mapping(value: Any, field: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        _reject(f"{field} must be an object")
    return value


def _list(value: Any, field: str) -> list[Any]:
    if not isinstance(value, list):
        _reject(f"{field} must be a list")
    return value


def _string(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        _reject(f"{field} must be a non-empty string")
    return value.strip()


def _sha40(value: Any, field: str) -> str:
    cleaned = _string(value, field).lower()
    if len(cleaned) != 40 or any(char not in "0123456789abcdef" for char in cleaned):
        _reject(f"{field} must be a 40-character hexadecimal git SHA")
    return cleaned


def _sha256(value: Any, field: str) -> str:
    cleaned = _string(value, field).lower()
    if len(cleaned) != 64 or any(char not in "0123456789abcdef" for char in cleaned):
        _reject(f"{field} must be a 64-character hexadecimal sha256 digest")
    return cleaned


def _expect_bool(mapping: dict[str, Any], key: str, expected: bool, field: str) -> None:
    if mapping.get(key) is not expected:
        _reject(f"{field}.{key} must be {str(expected).lower()}")


def _hash_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_digest(payload: Any) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _verify_artifacts(artifacts_raw: Any, artifact_dir: Path) -> list[dict[str, str]]:
    artifacts = _list(artifacts_raw, "evidence.artifacts")
    names: list[str] = []
    normalized: list[dict[str, str]] = []
    for index, raw in enumerate(artifacts):
        artifact = _mapping(raw, f"evidence.artifacts[{index}]")
        name = _string(artifact.get("name"), f"evidence.artifacts[{index}].name")
        digest = _sha256(artifact.get("sha256"), f"evidence.artifacts[{index}].sha256")
        if name != Path(name).name or "/" in name or "\\" in name:
            _reject(f"artifact path must be a basename: {name}")
        names.append(name)
        normalized.append({"name": name, "sha256": digest})
    if len(names) != len(set(names)):
        _reject("evidence artifact names must be unique")
    if set(names) != EXPECTED_SCREENSHOTS:
        _reject("evidence artifacts must be exactly the four canonical SleepWealth screenshots")
    for artifact in normalized:
        path = artifact_dir / artifact["name"]
        if not path.is_file():
            _reject(f"artifact file is missing: {artifact['name']}")
        if _hash_file(path) != artifact["sha256"]:
            _reject(f"artifact hash mismatch: {artifact['name']}")
    return normalized


def _verify_evidence(
    manifest: dict[str, Any], artifact_dir: Path, source_sha: str
) -> tuple[dict[str, Any], list[dict[str, str]], str]:
    evidence = _mapping(manifest.get("evidence"), "evidence")
    if evidence.get("schema") != EXPECTED_EVIDENCE_SCHEMA:
        _reject("evidence.schema is unsupported")
    _expect_bool(evidence, "authorizes", False, "evidence")
    if _sha40(evidence.get("source_sha"), "evidence.source_sha") != source_sha:
        _reject("evidence.source_sha does not match manifest source_sha")
    if _sha40(evidence.get("tested_sha"), "evidence.tested_sha") != source_sha:
        _reject("evidence.tested_sha does not match exact source SHA")
    if evidence.get("authority_ceiling") != EXPECTED_EVIDENCE_AUTHORITY_CEILING:
        _reject("evidence authority ceiling changed")
    claims = _list(evidence.get("claims"), "evidence.claims")
    nonclaims = _list(evidence.get("does_not_prove"), "evidence.does_not_prove")
    expires_when = _list(evidence.get("expires_when"), "evidence.expires_when")
    if not claims or any(not isinstance(item, str) or not item.strip() for item in claims):
        _reject("evidence.claims must contain non-empty strings")
    if not REQUIRED_NONCLAIMS.issubset(set(nonclaims)):
        _reject("evidence.does_not_prove is missing required external/live-money non-claims")
    if not expires_when or any(not isinstance(item, str) or not item.strip() for item in expires_when):
        _reject("evidence.expires_when must contain non-empty invalidation rules")
    artifacts = _verify_artifacts(evidence.get("artifacts"), artifact_dir)
    canonical = {
        "schema": evidence["schema"],
        "subject": _string(evidence.get("subject"), "evidence.subject"),
        "evidence_type": _string(evidence.get("evidence_type"), "evidence.evidence_type"),
        "source_sha": source_sha,
        "tested_sha": source_sha,
        "authority_ceiling": evidence["authority_ceiling"],
        "authorizes": False,
        "claims": claims,
        "does_not_prove": nonclaims,
        "expires_when": expires_when,
        "artifacts": artifacts,
    }
    fingerprint = f"evidence-v1:{_canonical_digest(canonical)}"
    if evidence.get("fingerprint") != fingerprint:
        _reject("evidence fingerprint mismatch")
    if manifest.get("screenshots") != artifacts:
        _reject("top-level screenshots are cross-wired from evidence artifacts")
    if manifest.get("claim_scope") != claims:
        _reject("top-level claim_scope does not match evidence claims")
    if manifest.get("does_not_prove") != nonclaims:
        _reject("top-level does_not_prove does not match evidence")
    return evidence, artifacts, fingerprint


def _verify_readiness(manifest: dict[str, Any]) -> tuple[dict[str, Any], str]:
    readiness = _mapping(manifest.get("live_money_readiness"), "live_money_readiness")
    if readiness.get("event") != "live_money_readiness_evaluated":
        _reject("live_money_readiness event is invalid")
    _expect_bool(readiness, "execution_authorized", False, "live_money_readiness")
    _string(readiness.get("authority_ceiling"), "live_money_readiness.authority_ceiling")
    checks = _list(readiness.get("checks"), "live_money_readiness.checks")
    if not checks:
        _reject("live_money_readiness.checks must not be empty")
    codes: list[str] = []
    normalized_checks: list[dict[str, Any]] = []
    for index, raw in enumerate(checks):
        check = _mapping(raw, f"live_money_readiness.checks[{index}]")
        code = _string(check.get("code"), f"live_money_readiness.checks[{index}].code")
        classification = _string(
            check.get("classification"), f"live_money_readiness.checks[{index}].classification"
        )
        reason = _string(check.get("reason"), f"live_money_readiness.checks[{index}].reason")
        source = _string(check.get("source"), f"live_money_readiness.checks[{index}].source")
        blocking = check.get("blocking")
        if not isinstance(blocking, bool):
            _reject(f"live_money_readiness.checks[{index}].blocking must be boolean")
        codes.append(code)
        normalized_checks.append(
            {"code": code, "classification": classification, "reason": reason, "source": source, "blocking": blocking}
        )
    if len(codes) != len(set(codes)):
        _reject("live_money_readiness check codes must be unique")
    fingerprint = _canonical_digest(normalized_checks)
    if readiness.get("fingerprint") != fingerprint:
        _reject("live_money_readiness fingerprint mismatch")
    calculated_ready = all(check["classification"] == "VERIFIED" for check in normalized_checks)
    if readiness.get("ready") is not calculated_ready:
        _reject("live_money_readiness.ready does not match its checks")
    blockers = [check["code"] for check in normalized_checks if check["classification"] != "VERIFIED"]
    if readiness.get("blockers") != blockers:
        _reject("live_money_readiness.blockers do not match its checks")
    return readiness, fingerprint


def _verify_human_review(
    manifest: dict[str, Any], source_sha: str, evidence_fingerprint: str,
    readiness: dict[str, Any], readiness_fingerprint: str,
) -> None:
    review = _mapping(manifest.get("human_live_review"), "human_live_review")
    if review.get("schema") != EXPECTED_REVIEW_SCHEMA:
        _reject("human_live_review.schema is unsupported")
    if review.get("event") != "human_live_review_prepared":
        _reject("human_live_review event is invalid")
    if _sha40(review.get("source_sha"), "human_live_review.source_sha") != source_sha:
        _reject("human_live_review source SHA is cross-wired")
    if review.get("evidence_fingerprint") != evidence_fingerprint:
        _reject("human_live_review evidence fingerprint is cross-wired")
    if review.get("readiness_fingerprint") != readiness_fingerprint:
        _reject("human_live_review readiness fingerprint is cross-wired")
    if review.get("readiness_ready") is not readiness.get("ready"):
        _reject("human_live_review readiness classification is cross-wired")
    if review.get("blockers") != readiness.get("blockers"):
        _reject("human_live_review blockers are cross-wired")
    _expect_bool(review, "manual_review_required", True, "human_live_review")
    for key in ("execution_authorized", "submit_capability", "money_movement_capability", "contains_order_instructions"):
        _expect_bool(review, key, False, "human_live_review")
    forbidden = set(_list(review.get("forbidden_content"), "human_live_review.forbidden_content"))
    if not {"broker credentials", "wallet secrets", "funding instructions", "order submission instructions"}.issubset(forbidden):
        _reject("human_live_review forbidden_content lost a required boundary")


def _verify_authority_decision(manifest: dict[str, Any], evidence: dict[str, Any], evidence_fingerprint: str) -> None:
    decision = _mapping(manifest.get("authority_decision"), "authority_decision")
    expected = {
        "allowed": True,
        "action": "assert_runtime_truth",
        "effect": "read-only",
        "consequence": "informational",
        "execution_mode": "practice",
        "grant_id": "ci-proof-claim-v1",
        "authority_source": "trusted-runtime-registry",
        "subject": evidence.get("subject"),
        "evidence_fingerprint": evidence_fingerprint,
    }
    for key, value in expected.items():
        if decision.get(key) != value:
            _reject(f"authority_decision.{key} is outside the proof-only authority boundary")


def verify_proof_manifest(manifest_path: str | Path, *, expected_sha: str | None = None) -> dict[str, Any]:
    path = Path(manifest_path)
    if not path.is_file():
        _reject(f"manifest file is missing: {path}")
    raw_bytes = path.read_bytes()
    try:
        manifest = json.loads(raw_bytes)
    except json.JSONDecodeError as exc:
        raise ProofVerificationError("proof manifest is not valid JSON") from exc
    manifest = _mapping(manifest, "manifest")
    if manifest.get("schema") != EXPECTED_MANIFEST_SCHEMA:
        _reject("manifest schema is unsupported")
    source_sha = _sha40(manifest.get("source_sha"), "manifest.source_sha")
    tested_sha = _sha40(manifest.get("tested_sha"), "manifest.tested_sha")
    if source_sha != tested_sha:
        _reject("manifest source_sha and tested_sha must match")
    if expected_sha is not None and source_sha != _sha40(expected_sha, "expected_sha"):
        _reject("manifest source SHA does not match expected exact head")
    if manifest.get("execution_mode") != "practice":
        _reject("manifest execution_mode must remain practice")
    _expect_bool(manifest, "live_execution", False, "manifest")
    if manifest.get("market_observation") != "read-only":
        _reject("manifest market observation must remain read-only")
    if manifest.get("external_crypto_sources") != "observation-only":
        _reject("external crypto sources must remain observation-only")
    if manifest.get("authority") != "non-authorizing evidence":
        _reject("manifest authority classification changed")
    evidence, artifacts, evidence_fingerprint = _verify_evidence(manifest, path.parent, source_sha)
    readiness, readiness_fingerprint = _verify_readiness(manifest)
    _verify_human_review(manifest, source_sha, evidence_fingerprint, readiness, readiness_fingerprint)
    _verify_authority_decision(manifest, evidence, evidence_fingerprint)
    return {
        "schema": "sleepwealth-independent-proof-verification-v1",
        "event": "proof_manifest_independently_verified",
        "accepted": True,
        "source_sha": source_sha,
        "tested_sha": tested_sha,
        "manifest_sha256": _hash_bytes(raw_bytes),
        "evidence_fingerprint": evidence_fingerprint,
        "readiness_fingerprint": readiness_fingerprint,
        "verified_artifacts": artifacts,
        "external_crypto_sources": "observation-only",
        "authority": "non-authorizing verification",
        "execution_authorized": False,
        "submit_capability": False,
        "money_movement_capability": False,
        "truth": "Independent verification accepted the proof package without granting execution authority.",
    }


def _write_receipt(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Independently verify a SleepWealth proof manifest")
    parser.add_argument("manifest", help="Path to proof-manifest.json")
    parser.add_argument("--expected-sha", help="Exact source SHA required for acceptance")
    parser.add_argument("--receipt", help="Optional path for the verification receipt")
    args = parser.parse_args(argv)
    receipt_path = Path(args.receipt) if args.receipt else None
    try:
        receipt = verify_proof_manifest(args.manifest, expected_sha=args.expected_sha)
    except ProofVerificationError as exc:
        failure = {
            "schema": "sleepwealth-independent-proof-verification-v1",
            "event": "proof_manifest_independently_verified",
            "accepted": False,
            "reason": str(exc),
            "authority": "non-authorizing verification",
            "execution_authorized": False,
            "submit_capability": False,
            "money_movement_capability": False,
        }
        if receipt_path is not None:
            _write_receipt(receipt_path, failure)
        print(json.dumps(failure, sort_keys=True), file=sys.stderr)
        return 1
    if receipt_path is not None:
        _write_receipt(receipt_path, receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
