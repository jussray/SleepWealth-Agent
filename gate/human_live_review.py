"""Non-executable human review handoff for live-money readiness.

This module packages current evidence and readiness truth for human review only.
It deliberately cannot submit orders, carry broker credentials, or grant money-moving
authority. The output is descriptive and fail-closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from evidence import EvidenceObjectV1


@dataclass(frozen=True, slots=True)
class HumanLiveReviewV1:
    source_sha: str
    evidence_fingerprint: str
    readiness_fingerprint: str
    blockers: tuple[str, ...]
    readiness_ready: bool
    schema: str = "sleepwealth-human-live-review-v1"
    execution_authorized: bool = False
    submit_capability: bool = False
    money_movement_capability: bool = False
    contains_order_instructions: bool = False

    def __post_init__(self) -> None:
        if not self.source_sha.strip():
            raise ValueError("source_sha must not be empty")
        if not self.evidence_fingerprint.startswith("evidence-v1:"):
            raise ValueError("evidence fingerprint is missing or invalid")
        if len(self.readiness_fingerprint.strip()) != 64:
            raise ValueError("readiness fingerprint must be a sha256 hex digest")
        if any(char not in "0123456789abcdef" for char in self.readiness_fingerprint.lower()):
            raise ValueError("readiness fingerprint must be a sha256 hex digest")
        if self.execution_authorized or self.submit_capability or self.money_movement_capability:
            raise ValueError("human review receipts cannot grant execution or money movement")
        if self.contains_order_instructions:
            raise ValueError("human review receipts cannot contain order instructions")

    def to_dict(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "event": "human_live_review_prepared",
            "source_sha": self.source_sha,
            "evidence_fingerprint": self.evidence_fingerprint,
            "readiness_fingerprint": self.readiness_fingerprint,
            "readiness_ready": self.readiness_ready,
            "blockers": list(self.blockers),
            "manual_review_required": True,
            "execution_authorized": False,
            "submit_capability": False,
            "money_movement_capability": False,
            "contains_order_instructions": False,
            "allowed_content": [
                "current readiness classification",
                "evidence identity",
                "blocking conditions",
                "broker-provider account eligibility or permission status",
            ],
            "forbidden_content": [
                "broker credentials",
                "wallet secrets",
                "funding instructions",
                "order submission instructions",
                "unrelated product, repository, social, or platform-account signals presented as broker eligibility",
            ],
            "truth": (
                "This receipt is for human review only. It cannot submit, fund, transfer, "
                "mint, trade, or authorize real-money execution."
            ),
        }


def prepare_human_live_review(
    evidence: EvidenceObjectV1,
    readiness: dict[str, object],
    *,
    current_source_sha: str,
) -> HumanLiveReviewV1:
    """Bind current evidence + readiness into a non-executable review receipt."""

    if current_source_sha != evidence.source_sha or evidence.tested_sha != evidence.source_sha:
        raise ValueError("evidence is stale or is not exact-head bound")
    if evidence.authorizes:
        raise ValueError("evidence must remain non-authorizing")
    if readiness.get("event") != "live_money_readiness_evaluated":
        raise ValueError("readiness receipt event is missing or invalid")
    if readiness.get("execution_authorized") is not False:
        raise ValueError("readiness receipt must remain non-authorizing")

    readiness_fingerprint = str(readiness.get("fingerprint") or "").lower()
    blockers_raw = readiness.get("blockers")
    if not isinstance(blockers_raw, list) or any(not isinstance(item, str) for item in blockers_raw):
        raise ValueError("readiness blockers must be a list of strings")

    return HumanLiveReviewV1(
        source_sha=current_source_sha,
        evidence_fingerprint=evidence.fingerprint,
        readiness_fingerprint=readiness_fingerprint,
        blockers=tuple(blockers_raw),
        readiness_ready=bool(readiness.get("ready") is True),
    )
