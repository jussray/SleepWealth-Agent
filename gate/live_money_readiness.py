"""Machine-readable live-money readiness truth for Sleep Wealth.

This module reports the repository's current execution ceiling. It does not
accept caller-supplied flags that could be mistaken for authority, and it never
grants execution authority. External brokerage/account state remains UNKNOWN
until a separately verified runtime receipt exists.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Iterable

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


def live_money_readiness() -> dict[str, object]:
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
            code="LIVE_BROKER_SESSION_RECEIPT",
            classification="UNKNOWN",
            reason=(
                "no independently verified live brokerage/account session receipt is bound "
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
        "fingerprint": _fingerprint(checks),
        "truth": (
            "This receipt describes current state only. It never grants, renews, or "
            "expands real-money authority."
        ),
    }
