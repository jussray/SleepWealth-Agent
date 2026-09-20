"""Machine-readable live-money readiness truth for Sleep Wealth.

This module reports the repository's current execution ceiling. It does not
accept caller-supplied booleans that could be mistaken for authority, and it
never grants execution authority. External brokerage/account observations may
be attached as evidence, but they cannot satisfy execution gates by themselves.
Broker eligibility is provider-scoped: unrelated product, repository, social,
or platform-account signals are never treated as brokerage eligibility proof.

Adult eligibility is a distinct provider-evidence plane. Sleep Wealth never
accepts self-attested age as live-money authority. A broker/provider receipt may
prove that the account holder satisfies an 18+ eligibility rule, but that receipt
still cannot authorize execution or bypass any other live-money gate.

Eligibility fingerprints are continuity markers only. Provider authenticity is
proved separately with a trusted-runtime HMAC key and short-lived receipt.
"""

from __future__ import annotations

import hashlib
import hmac
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping

from authority.runtime import EffectClass
from broker.factory import KNOWN_BROKERS
from execution.modes import LIVE_MODE, get_execution_mode

MIN_RECEIPT_KEY_BYTES = 32
MAX_ELIGIBILITY_TTL_SECONDS = 24 * 60 * 60
MAX_CLOCK_SKEW_SECONDS = 5 * 60


@dataclass(frozen=True, slots=True)
class ReadinessCheck:
    code: str
    classification: str
    reason: str
    source: str
    blocking: bool = True

    def to_dict(self) -> dict[str, object]:
        return {
            "code": self.code,
            "classification": self.classification,
            "reason": self.reason,
            "source": self.source,
            "blocking": self.blocking,
        }


def _fingerprint(checks: Iterable[ReadinessCheck]) -> str:
    payload = [check.to_dict() for check in checks]
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _canonical_receipt_payload(receipt: Mapping[str, object]) -> bytes:
    payload = dict(receipt)
    payload.pop("fingerprint", None)
    payload.pop("receipt_auth", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return canonical.encode("utf-8")


def _receipt_fingerprint(receipt: Mapping[str, object]) -> tuple[str, str]:
    supplied_fingerprint = str(receipt.get("fingerprint", ""))
    calculated_fingerprint = hashlib.sha256(_canonical_receipt_payload(receipt)).hexdigest()
    return supplied_fingerprint, calculated_fingerprint


def _receipt_key(value: object) -> bytes:
    if isinstance(value, bytes):
        key = value
    elif isinstance(value, str):
        key = value.encode("utf-8")
    else:
        return b""
    return key if len(key) >= MIN_RECEIPT_KEY_BYTES else b""


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _valid_sha256(value: object) -> bool:
    if not isinstance(value, str) or len(value) != 64 or not value.isascii():
        return False
    return all(char in "0123456789abcdefABCDEF" for char in value)


def _eligibility_auth_is_valid(
    receipt: Mapping[str, object],
    trusted_eligibility_keys: Mapping[str, object] | None,
) -> bool:
    issuer_id = receipt.get("issuer_id")
    if not isinstance(issuer_id, str) or not issuer_id.strip():
        return False
    if not trusted_eligibility_keys:
        return False
    key = _receipt_key(trusted_eligibility_keys.get(issuer_id))
    if not key:
        return False
    provided = receipt.get("receipt_auth")
    if not _valid_sha256(provided):
        return False
    expected = hmac.new(key, _canonical_receipt_payload(receipt), hashlib.sha256).hexdigest()
    return hmac.compare_digest(str(provided).lower(), expected.lower())


def _observer_evidence(receipt: Mapping[str, object] | None) -> dict[str, object]:
    """Validate a non-authorizing external observer receipt."""

    if receipt is None:
        return {
            "classification": "UNKNOWN",
            "accepted": False,
            "reason": "no read-only external account observer receipt supplied",
        }

    supplied_fingerprint, calculated_fingerprint = _receipt_fingerprint(receipt)

    invariants_ok = (
        receipt.get("event") == "ibkr_readonly_session_observed"
        and receipt.get("classification") == "OBSERVED"
        and receipt.get("connected") is True
        and receipt.get("execution_authorized") is False
        and receipt.get("readonly_requested") is True
        and receipt.get("loopback_only") is True
        and supplied_fingerprint == calculated_fingerprint
    )
    if not invariants_ok:
        return {
            "classification": "INVALID",
            "accepted": False,
            "reason": "external observer receipt failed integrity or non-authority invariants",
        }

    return {
        "classification": "VERIFIED_OBSERVATION",
        "accepted": True,
        "reason": (
            "read-only local session evidence is internally consistent; provider-side read-only "
            "enforcement and real-money execution authority remain unproved"
        ),
        "fingerprint": supplied_fingerprint,
        "account_count": receipt.get("account_count", 0),
        "provider_readonly_enforcement": receipt.get(
            "provider_readonly_enforcement", "UNKNOWN"
        ),
    }


def _broker_eligibility_evidence(
    receipt: Mapping[str, object] | None,
    trusted_eligibility_keys: Mapping[str, object] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, object]:
    """Validate provider-bound adult/account eligibility evidence.

    The caller cannot create trust by naming itself "broker-provider". The
    receipt must be bound to a trusted issuer key supplied by the runtime, must
    identify the provider account only through a non-secret fingerprint, and
    must be fresh. A valid receipt is evidence only and cannot authorize an
    order, transfer, funding action, or wallet signature.
    """

    if receipt is None:
        return {
            "classification": "UNKNOWN",
            "accepted": False,
            "reason": "no broker/provider adult-account eligibility receipt supplied",
        }

    supplied_fingerprint, calculated_fingerprint = _receipt_fingerprint(receipt)
    minimum_age = receipt.get("minimum_age")
    minimum_age_ok = (
        isinstance(minimum_age, int)
        and not isinstance(minimum_age, bool)
        and minimum_age >= 18
    )
    issued_at = _parse_timestamp(receipt.get("issued_at"))
    expires_at = _parse_timestamp(receipt.get("expires_at"))
    now = evaluated_at or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    else:
        now = now.astimezone(timezone.utc)

    freshness_ok = False
    if issued_at and expires_at:
        issued_utc = issued_at.astimezone(timezone.utc)
        expires_utc = expires_at.astimezone(timezone.utc)
        ttl_seconds = (expires_utc - issued_utc).total_seconds()
        freshness_ok = (
            0 < ttl_seconds <= MAX_ELIGIBILITY_TTL_SECONDS
            and issued_utc.timestamp() - MAX_CLOCK_SKEW_SECONDS <= now.timestamp()
            and now <= expires_utc
        )

    structural_ok = (
        receipt.get("event") == "broker_account_eligibility_observed"
        and receipt.get("classification") == "VERIFIED"
        and receipt.get("source") == "broker-provider"
        and receipt.get("account_holder_age_verified") is True
        and minimum_age_ok
        and receipt.get("trading_enabled") is True
        and receipt.get("live_money_allowed") is True
        and receipt.get("execution_authorized") is False
        and isinstance(receipt.get("broker"), str)
        and bool(str(receipt.get("broker", "")).strip())
        and isinstance(receipt.get("issuer_id"), str)
        and bool(str(receipt.get("issuer_id", "")).strip())
        and _valid_sha256(receipt.get("account_fingerprint"))
        and supplied_fingerprint == calculated_fingerprint
    )

    if not structural_ok:
        return {
            "classification": "INVALID",
            "accepted": False,
            "reason": (
                "broker eligibility receipt failed integrity, provider-source, 18+, "
                "account-permission, account-fingerprint, or non-authority invariants"
            ),
        }

    if not _eligibility_auth_is_valid(receipt, trusted_eligibility_keys):
        return {
            "classification": "UNTRUSTED",
            "accepted": False,
            "reason": (
                "broker eligibility receipt is structurally valid but lacks a valid "
                "trusted-issuer authentication proof"
            ),
        }

    if not freshness_ok:
        return {
            "classification": "STALE",
            "accepted": False,
            "reason": (
                "broker eligibility receipt is outside the allowed freshness window "
                f"(max {MAX_ELIGIBILITY_TTL_SECONDS // 3600}h)"
            ),
        }

    return {
        "classification": "VERIFIED_ELIGIBLE_ADULT_ACCOUNT",
        "accepted": True,
        "reason": (
            "trusted provider evidence verifies an eligible 18+ account holder and "
            "live-money account permission; this remains non-authorizing evidence"
        ),
        "fingerprint": supplied_fingerprint,
        "broker": receipt.get("broker"),
        "issuer_id": receipt.get("issuer_id"),
        "account_fingerprint": receipt.get("account_fingerprint"),
        "minimum_age": minimum_age,
        "expires_at": receipt.get("expires_at"),
    }


def live_money_readiness(
    external_observer_receipt: Mapping[str, object] | None = None,
    broker_eligibility_receipt: Mapping[str, object] | None = None,
    *,
    trusted_eligibility_keys: Mapping[str, object] | None = None,
    evaluated_at: datetime | None = None,
) -> dict[str, object]:
    """Return a fail-closed readiness receipt derived from executable repo truth.

    Evidence/fingerprints are continuity markers only; they never create or
    renew trading authority.
    """

    live_mode = get_execution_mode(LIVE_MODE)
    real_money_effect_representable = any(
        effect.value in {"real-money", "live-trade", "funding", "transfer"}
        for effect in EffectClass
    )
    external_brokers = tuple(name for name in KNOWN_BROKERS if name != "mock")
    observer = _observer_evidence(external_observer_receipt)
    observer_seen = observer.get("classification") == "VERIFIED_OBSERVATION"
    eligibility = _broker_eligibility_evidence(
        broker_eligibility_receipt,
        trusted_eligibility_keys=trusted_eligibility_keys,
        evaluated_at=evaluated_at,
    )
    adult_account_verified = (
        eligibility.get("classification") == "VERIFIED_ELIGIBLE_ADULT_ACCOUNT"
    )

    checks = (
        ReadinessCheck(
            code="LIVE_EXECUTION_MODE",
            classification="VERIFIED" if live_mode.real_execution_enabled else "BLOCKED",
            reason=(
                "live execution mode permits real execution"
                if live_mode.real_execution_enabled
                else f"live mode ceiling is '{live_mode.authority_ceiling}'"
            ),
            source="execution.modes",
        ),
        ReadinessCheck(
            code="REAL_MONEY_EFFECT_CLASS",
            classification="VERIFIED" if real_money_effect_representable else "BLOCKED",
            reason=(
                "authority runtime represents a real-money effect"
                if real_money_effect_representable
                else "authority runtime exposes only read-only and paper-simulation effects"
            ),
            source="authority.runtime",
        ),
        ReadinessCheck(
            code="EXTERNAL_BROKER_ADAPTER",
            classification="VERIFIED" if external_brokers else "BLOCKED",
            reason=(
                f"external broker adapters available: {', '.join(external_brokers)}"
                if external_brokers
                else "broker factory exposes mock only; external broker execution is disabled"
            ),
            source="broker.factory",
        ),
        ReadinessCheck(
            code="ADULT_ACCOUNT_ELIGIBILITY",
            classification=(
                "VERIFIED" if adult_account_verified else str(eligibility["classification"])
            ),
            reason=str(eligibility["reason"]),
            source="broker-provider-age-and-account-authority",
        ),
        ReadinessCheck(
            code="BROKER_ACCOUNT_ELIGIBILITY",
            classification="VERIFIED" if adult_account_verified else "UNKNOWN",
            reason=(
                "trusted broker/provider receipt verifies account permission and 18+ holder "
                "eligibility"
                if adult_account_verified
                else "no trusted broker-provider eligibility/account-permission receipt is "
                "bound to this runtime; unrelated product, repository, social, or "
                "platform-account signals cannot satisfy this check"
            ),
            source="broker-provider-authority",
        ),
        ReadinessCheck(
            code="LIVE_BROKER_SESSION_RECEIPT",
            classification="UNKNOWN",
            reason=(
                "a read-only IBKR session was observed, but observation is not proof of an "
                "authorized live execution session"
                if observer_seen
                else "no independently verified live brokerage/account session receipt is bound "
                "to this runtime"
            ),
            source="external-runtime-evidence",
        ),
    )

    ready = all(check.classification == "VERIFIED" for check in checks)
    return {
        "event": "live_money_readiness_evaluated",
        "ready": ready,
        "execution_authorized": False,
        "authority_ceiling": live_mode.authority_ceiling,
        "checks": [check.to_dict() for check in checks],
        "blockers": [check.code for check in checks if check.classification != "VERIFIED"],
        "external_readonly_observer": observer,
        "broker_eligibility": eligibility,
        "fingerprint": _fingerprint(checks),
        "truth": (
            "This receipt describes current state only. It never grants, renews, or "
            "expands real-money authority."
        ),
    }
