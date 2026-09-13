from __future__ import annotations

from dataclasses import dataclass, field
from hashlib import sha256
import json
from typing import Iterable


def _clean_text(value: str, field_name: str) -> str:
    cleaned = value.strip()
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned


def _clean_tuple(values: Iterable[str], field_name: str) -> tuple[str, ...]:
    cleaned = tuple(_clean_text(value, field_name) for value in values)
    if not cleaned:
        raise ValueError(f"{field_name} must not be empty")
    return cleaned


def _validate_sha256(value: str) -> str:
    cleaned = value.strip().lower()
    if len(cleaned) != 64 or any(char not in "0123456789abcdef" for char in cleaned):
        raise ValueError("artifact sha256 must be a 64-character hexadecimal digest")
    return cleaned


@dataclass(frozen=True, slots=True)
class EvidenceArtifact:
    name: str
    sha256: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "name", _clean_text(self.name, "artifact name"))
        object.__setattr__(self, "sha256", _validate_sha256(self.sha256))

    def to_dict(self) -> dict[str, str]:
        return {"name": self.name, "sha256": self.sha256}


@dataclass(frozen=True, slots=True)
class EvidenceObjectV1:
    subject: str
    evidence_type: str
    source_sha: str
    tested_sha: str
    authority_ceiling: str
    claims: tuple[str, ...]
    does_not_prove: tuple[str, ...]
    artifacts: tuple[EvidenceArtifact, ...] = field(default_factory=tuple)
    expires_when: tuple[str, ...] = (
        "subject changes",
        "source identity changes",
        "runtime identity changes",
        "evidence bytes change",
        "authority boundary changes",
    )
    schema: str = "ultrathink-evidence-object-v1"
    authorizes: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "subject", _clean_text(self.subject, "subject"))
        object.__setattr__(self, "evidence_type", _clean_text(self.evidence_type, "evidence_type"))
        object.__setattr__(self, "source_sha", _clean_text(self.source_sha, "source_sha"))
        object.__setattr__(self, "tested_sha", _clean_text(self.tested_sha, "tested_sha"))
        object.__setattr__(
            self, "authority_ceiling", _clean_text(self.authority_ceiling, "authority_ceiling")
        )
        object.__setattr__(self, "claims", _clean_tuple(self.claims, "claims"))
        object.__setattr__(
            self, "does_not_prove", _clean_tuple(self.does_not_prove, "does_not_prove")
        )
        object.__setattr__(self, "expires_when", _clean_tuple(self.expires_when, "expires_when"))
        object.__setattr__(self, "artifacts", tuple(self.artifacts))
        if self.authorizes:
            raise ValueError("Evidence objects are non-authorizing and cannot grant authority")
        if self.source_sha != self.tested_sha:
            raise ValueError("source_sha and tested_sha must match for exact-head evidence")
        names = [artifact.name for artifact in self.artifacts]
        if len(names) != len(set(names)):
            raise ValueError("artifact names must be unique")

    def canonical_payload(self) -> dict[str, object]:
        return {
            "schema": self.schema,
            "subject": self.subject,
            "evidence_type": self.evidence_type,
            "source_sha": self.source_sha,
            "tested_sha": self.tested_sha,
            "authority_ceiling": self.authority_ceiling,
            "authorizes": self.authorizes,
            "claims": list(self.claims),
            "does_not_prove": list(self.does_not_prove),
            "expires_when": list(self.expires_when),
            "artifacts": [artifact.to_dict() for artifact in self.artifacts],
        }

    @property
    def fingerprint(self) -> str:
        encoded = json.dumps(
            self.canonical_payload(), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        return f"evidence-v1:{sha256(encoded).hexdigest()}"

    def to_dict(self) -> dict[str, object]:
        payload = self.canonical_payload()
        payload["fingerprint"] = self.fingerprint
        return payload
