from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Mapping, Sequence

MIN_COOKIE_KEY_BYTES = 32
MAX_COOKIE_TTL_SECONDS = 10 * 60
MAX_CLOCK_SKEW_SECONDS = 5 * 60
SCHEMA = "sleepwealth-mcp-continuity-v1"


def _canonical(payload: Mapping[str, object]) -> bytes:
    body = dict(payload)
    body.pop("fingerprint", None)
    body.pop("cookie_auth", None)
    return json.dumps(body, sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")


def _key(value: object) -> bytes:
    if isinstance(value, bytes):
        result = value
    elif isinstance(value, str):
        result = value.encode("utf-8")
    else:
        return b""
    return result if len(result) >= MIN_COOKIE_KEY_BYTES else b""


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.isascii()
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


@dataclass(frozen=True, slots=True)
class ContinuityDecision:
    accepted: bool
    classification: str
    reason: str
    fingerprint: str | None = None
    provider: str | None = None
    environment: str | None = None
    provider_subject_fingerprint: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "classification": self.classification,
            "reason": self.reason,
            "fingerprint": self.fingerprint,
            "provider": self.provider,
            "environment": self.environment,
            "provider_subject_fingerprint": self.provider_subject_fingerprint,
            "execution_authorized": False,
            "contains_secret": False,
        }


def issue_continuity_cookie(
    *,
    issuer_id: str,
    issuer_key: str | bytes,
    caller_fingerprint: str,
    provider: str,
    provider_subject_fingerprint: str,
    source_sha: str,
    environment: str,
    capabilities: Sequence[str],
    authority_fingerprint: str | None = None,
    issued_at: datetime | None = None,
    ttl_seconds: int = 5 * 60,
) -> dict[str, object]:
    """Issue a short-lived non-authorizing continuity cookie.

    The cookie answers only "is this the same caller/provider/account/source
    context we observed recently?" It is never a credential or money-moving
    grant, even though it is authenticated against tampering.
    """

    key = _key(issuer_key)
    if not issuer_id.strip() or not key:
        raise ValueError("continuity issuer id and a 32+ byte key are required")
    if not (_valid_sha256(caller_fingerprint) and _valid_sha256(provider_subject_fingerprint)):
        raise ValueError("caller and provider-subject fingerprints must be SHA-256 values")
    if not isinstance(source_sha, str) or len(source_sha) < 7:
        raise ValueError("source_sha is required")
    if not provider.strip() or not environment.strip():
        raise ValueError("provider and environment are required")
    normalized_caps = tuple(sorted({str(value).strip() for value in capabilities if str(value).strip()}))
    if not normalized_caps:
        raise ValueError("at least one capability is required")
    if authority_fingerprint is not None and not _valid_sha256(authority_fingerprint):
        raise ValueError("authority_fingerprint must be a SHA-256 value when supplied")
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool):
        raise ValueError("ttl_seconds must be an integer")
    if not 1 <= ttl_seconds <= MAX_COOKIE_TTL_SECONDS:
        raise ValueError(f"continuity TTL must be 1..{MAX_COOKIE_TTL_SECONDS} seconds")

    now = _utc(issued_at)
    expires = now + timedelta(seconds=ttl_seconds)
    receipt: dict[str, object] = {
        "schema": SCHEMA,
        "event": "mcp_continuity_observed",
        "classification": "CONTINUITY_ONLY",
        "issuer_id": issuer_id.strip(),
        "caller_fingerprint": caller_fingerprint.lower(),
        "provider": provider.strip().lower(),
        "provider_subject_fingerprint": provider_subject_fingerprint.lower(),
        "source_sha": source_sha.strip(),
        "environment": environment.strip().lower(),
        "capabilities": list(normalized_caps),
        "authority_fingerprint": authority_fingerprint.lower() if authority_fingerprint else None,
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "authorizes": False,
        "execution_authorized": False,
        "contains_secret": False,
    }
    receipt["fingerprint"] = hashlib.sha256(_canonical(receipt)).hexdigest()
    receipt["cookie_auth"] = hmac.new(key, _canonical(receipt), hashlib.sha256).hexdigest()
    return receipt


def validate_continuity_cookie(
    cookie: Mapping[str, object] | None,
    *,
    trusted_keys: Mapping[str, object] | None,
    evaluated_at: datetime | None = None,
) -> ContinuityDecision:
    if cookie is None:
        return ContinuityDecision(False, "MISSING", "continuity cookie is required")

    provider = str(cookie.get("provider", "")) or None
    environment = str(cookie.get("environment", "")) or None
    subject_fp = str(cookie.get("provider_subject_fingerprint", "")) or None
    supplied_fp = cookie.get("fingerprint")
    capabilities = cookie.get("capabilities")

    structural_ok = (
        cookie.get("schema") == SCHEMA
        and cookie.get("event") == "mcp_continuity_observed"
        and cookie.get("classification") == "CONTINUITY_ONLY"
        and cookie.get("authorizes") is False
        and cookie.get("execution_authorized") is False
        and cookie.get("contains_secret") is False
        and isinstance(cookie.get("issuer_id"), str)
        and bool(str(cookie.get("issuer_id", "")).strip())
        and _valid_sha256(cookie.get("caller_fingerprint"))
        and _valid_sha256(subject_fp)
        and isinstance(provider, str)
        and bool(provider.strip())
        and isinstance(environment, str)
        and bool(environment.strip())
        and isinstance(cookie.get("source_sha"), str)
        and len(str(cookie.get("source_sha"))) >= 7
        and isinstance(capabilities, list)
        and bool(capabilities)
        and len(capabilities) == len(set(str(value) for value in capabilities))
        and all(isinstance(value, str) and value.strip() for value in capabilities)
        and (cookie.get("authority_fingerprint") is None or _valid_sha256(cookie.get("authority_fingerprint")))
        and _valid_sha256(supplied_fp)
        and hmac.compare_digest(
            str(supplied_fp).lower(),
            hashlib.sha256(_canonical(cookie)).hexdigest().lower(),
        )
    )
    if not structural_ok:
        return ContinuityDecision(False, "INVALID", "continuity cookie invariants failed")

    issuer_id = str(cookie["issuer_id"])
    key = _key((trusted_keys or {}).get(issuer_id))
    supplied_auth = cookie.get("cookie_auth")
    expected_auth = hmac.new(key, _canonical(cookie), hashlib.sha256).hexdigest() if key else ""
    if not (
        key
        and _valid_sha256(supplied_auth)
        and hmac.compare_digest(str(supplied_auth).lower(), expected_auth.lower())
    ):
        return ContinuityDecision(False, "UNTRUSTED", "continuity cookie authentication failed")

    issued = _parse_time(cookie.get("issued_at"))
    expires = _parse_time(cookie.get("expires_at"))
    now = _utc(evaluated_at)
    freshness_ok = False
    if issued and expires:
        issued_utc = issued.astimezone(timezone.utc)
        expires_utc = expires.astimezone(timezone.utc)
        ttl = (expires_utc - issued_utc).total_seconds()
        freshness_ok = (
            0 < ttl <= MAX_COOKIE_TTL_SECONDS
            and issued_utc <= now + timedelta(seconds=MAX_CLOCK_SKEW_SECONDS)
            and now <= expires_utc
        )
    if not freshness_ok:
        return ContinuityDecision(False, "STALE", "continuity cookie is outside its freshness window")

    return ContinuityDecision(
        True,
        "VERIFIED_CONTINUITY",
        "authenticated continuity marker is current; it grants no execution authority",
        fingerprint=str(supplied_fp).lower(),
        provider=provider,
        environment=environment,
        provider_subject_fingerprint=subject_fp,
    )
