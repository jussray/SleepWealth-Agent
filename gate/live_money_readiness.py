"""Machine-readable live-money readiness truth for Sleep Wealth.

This module reports the repository's current execution ceiling. It does not
accept caller-supplied booleans that could be mistaken for authority, and it
never grants execution authority. External brokerage/account observations may
be attached as evidence, but they cannot satisfy execution gates by themselves.
Broker eligibility is provider-scoped: unrelated product, repository, social,
or platform-account signals are never treated as brokerage eligibility proof.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable, Mapping

from authority.runtime import EffectClass
from broker.factory import KNOWN_BROKERS
from execution.modes import LIVE_MODE, get_execution_mode


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


def _observer_evidence(receipt: Mapping[str, object] | None) -> dict[str, object]:
    """Validate a non-authorizing external observer receipt.

    Even a valid receipt proves observation only. It never changes a live-money
    blocker from BLOCKED/UNKNOWN to VERIFIED.
    """

    if receipt is None:
        return {
            "classification": "UNKNOWN",
            "accepted": False,
            "reason": "no read-only external account observer receipt supplied",
        }

    supplied_fingerprint = str(receipt.get("fingerprint", ""))
    payload = dict(receipt)
    payload.pop("fingerprint", None)
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    calculated_fingerprint = hashlib.sha256(canonical.encode("utf-8")).hexdigest()

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


def live_money_readiness(
    external_observer_receipt: Mapping[str, object] | None = None,
) -> dict[str, object]:
    """Return a fail-closed readiness receipt derived from executable repo truth.

    The receipt intentionally separates each blocker. Evidence/fingerprints are
    continuity markers only; they never create or renew trading authority.
    """

    live_mode = get_execution_mode(LIVE_MODE)
    real_money_effect_representable = any(
        effect.value in {"real-money", "live-trade", "funding", "transfer"}
        for effect in EffectClass
    )
    external_brokers = tuple(name for name in KNOWN_BROKERS if name != "mock")
    observer = _observer_evidence(external_observer_receipt)
    observer_seen = observer.get("classification") == "VERIFIED_OBSERVATION"

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
            code="BROKER_ACCOUNT_ELIGIBILITY",
            classification="UNKNOWN",
            reason=(
                "no broker-provider eligibility/account-permission receipt is bound to this "
                "runtime; unrelated product, repository, social, or platform-account signals "
                "cannot satisfy this check"
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
        "fingerprint": _fingerprint(checks),
        "truth": (
            "This receipt describes current state only. It never grants, renews, or "
            "expands real-money authority."
        ),
    }
