"""Fail-closed simulation governance gate.

The module keeps the legacy ``LiveGate`` name for import compatibility, but it
cannot authorize live execution. SleepWealth is mock-only by repository policy.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, List, Optional


@dataclass(frozen=True)
class GateCheck:
    name: str
    passed: bool
    reason: str
    priority: int
    blocking: bool = True

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "passed": self.passed,
            "reason": self.reason,
            "priority": self.priority,
            "blocking": self.blocking,
        }


@dataclass
class GateResult:
    passed: bool
    checks: List[GateCheck] = field(default_factory=list)
    evaluated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    @property
    def failures(self) -> List[GateCheck]:
        return [check for check in self.checks if not check.passed]

    def to_dict(self) -> dict:
        return {
            "event": "simulation_gate_evaluated",
            "passed": self.passed,
            "failures": [check.name for check in self.failures],
            "checks": [check.to_dict() for check in self.checks],
            "evaluated_at": self.evaluated_at,
        }

    def render(self) -> str:
        lines = ["SIMULATION GOVERNANCE GATE", "=" * 56]
        for check in sorted(self.checks, key=lambda item: item.priority):
            mark = "PASS" if check.passed else ("FAIL" if check.blocking else "WARN")
            lines.append(f"  [{mark}] {check.priority:>2}. {check.name}")
            if not check.passed:
                lines.append(f"         → {check.reason}")
        lines.append("=" * 56)
        if self.passed:
            lines.append("SIMULATION CHECKS PASS — mock-only governance evidence is complete")
        else:
            lines.append(f"CHECKS INCOMPLETE — {len(self.failures)} condition(s) unmet.")
        lines.append("LIVE EXECUTION REMAINS DISABLED BY REPOSITORY POLICY")
        return "\n".join(lines)


class LiveGate:
    """Legacy-named simulation gate. It never unlocks real-money execution."""

    def __init__(self, audit_path: str = "audit.log"):
        self.audit_path = Path(audit_path)

    def _events(self) -> List[dict]:
        if not self.audit_path.exists():
            return []
        events = []
        with self.audit_path.open(encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    def chain_hash(self) -> str:
        """Return a SHA-256 digest for the current append-only audit artifact."""
        if not self.audit_path.exists():
            return ""
        digest = hashlib.sha256()
        with self.audit_path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(8192), b""):
                digest.update(chunk)
        return digest.hexdigest()

    def evaluate(self, broker=None, rules: Optional[dict] = None, config: Optional[dict] = None) -> GateResult:
        rules = rules or {}
        config = config or {}
        events = self._events()
        checks: List[GateCheck] = []

        def add(name: str, passed: bool, reason: str, priority: int, blocking: bool = True) -> None:
            checks.append(GateCheck(name, bool(passed), reason, priority, blocking))

        add(
            "audit_evidence_present",
            bool(events),
            "audit log is empty; run a mock simulation first",
            1,
        )

        ceiling = rules.get("ceiling") or {}
        add(
            "ceiling_remains_human_locked",
            ceiling.get("can_auto_increase") is False,
            "ceiling.can_auto_increase must be false",
            2,
        )

        add(
            "live_execution_disabled",
            config.get("live_enabled") is not True,
            "live_enabled must never be true",
            3,
        )

        broker_name = type(broker).__name__ if broker is not None else "none"
        add(
            "mock_only_boundary",
            broker is None or broker_name == "MockBroker",
            f"unexpected broker type: {broker_name}",
            4,
        )

        sensitive_keys = {
            key.lower()
            for key, value in config.items()
            if value not in (None, "", False)
            and any(
                term in key.lower()
                for term in ("credential", "token", "secret", "api_key", "apikey")
            )
        }
        add(
            "no_broker_credentials",
            not sensitive_keys,
            f"credential-like config keys present: {sorted(sensitive_keys)}",
            5,
        )

        error_events = [
            event
            for event in events
            if event.get("event") in {"error", "execution_error", "execution_failed"}
        ]
        add(
            "no_unresolved_runtime_errors",
            not error_events,
            f"{len(error_events)} runtime error event(s) remain in the audit log",
            6,
        )

        passed = all(check.passed for check in checks if check.blocking)
        return GateResult(passed=passed, checks=checks)


async def run_kill_switch_drill(broker, audit, cancel_fn: Optional[Callable] = None) -> dict:
    """Record a simulation-only kill-switch drill without calling a broker."""
    record = {
        "event": "kill_switch_drill",
        "result": "passed",
        "detail": "simulation-only drill; no broker operation performed",
    }
    await audit.log(record)
    return record
