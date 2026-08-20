"""Pre-live gate.

Turns the go-live checklist into code. Returns (passed, failures). Fail-closed:
any exception is a failure, an unknown state is a failure, an empty audit log is
a failure.

IMPORTANT: a passing result means only that these advisory/pre-live control
checks are satisfied. Repository policy still disables live broker execution.
This gate never grants execution authority.

The conditions are drawn from documented control failures rather than invented:

  * Knight Capital, 1 Aug 2012 — undocumented deployment, dead code left on one
    of eight servers, no automated erroneous-order check, no kill switch, and
    97 pre-open alerts sent to a channel nobody watched. First SEC enforcement
    under Rule 15c3-5.
  * SEC Rule 15c3-5 — pre-set capital thresholds, prevention of erroneous or
    duplicative orders, access restricted to authorised persons.
  * MiFID II RTS 6 — documented testing methodology, controlled deployment,
    pre-trade limits, real-time monitoring, and mandatory kill functionality.
  * FIA automated trading guidance — pre-trade risk controls, conformance
    testing, post-trade review.

None of those bind a solo operator trading their own account. They are used here
as the source of *which controls matter*, not as compliance obligations.

Counts are derived by replaying the append-only audit log rather than read from
a mutable counter, so bumping a number requires tampering that breaks the chain.
"""

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, List, Optional

DEFAULT_MIN_SOAK_DAYS = 30
DEFAULT_MIN_CLEAN_CYCLES = 20
DEFAULT_KILL_SWITCH_MAX_AGE_DAYS = 7
DEFAULT_MAX_DRAWDOWN_PCT = 10.0


@dataclass
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
    evaluated_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    @property
    def failures(self) -> List[GateCheck]:
        return [c for c in self.checks if not c.passed]

    def to_dict(self) -> dict:
        return {
            "event": "live_gate_evaluated",
            "passed": self.passed,
            "execution_authorized": False,
            "authority_ceiling": "advisory",
            "failures": [c.name for c in self.failures],
            "checks": [c.to_dict() for c in self.checks],
            "evaluated_at": self.evaluated_at,
        }

    def render(self) -> str:
        lines = ["PRE-LIVE GATE", "=" * 56]
        for c in sorted(self.checks, key=lambda x: x.priority):
            mark = "PASS" if c.passed else ("FAIL" if c.blocking else "WARN")
            lines.append(f"  [{mark}] {c.priority:>2}. {c.name}")
            if not c.passed:
                lines.append(f"         → {c.reason}")
        lines.append("=" * 56)
        lines.append(
            "PRE-LIVE CONTROLS SATISFIED — execution is still disabled by repository policy."
            if self.passed
            else f"PRE-LIVE CONTROLS INCOMPLETE — {len(self.failures)} condition(s) unmet. Continue mock/paper only."
        )
        lines.append("Authority: advisory only; execution_authorized=false")
        return "\n".join(lines)


class LiveGate:
    """Evaluates the 12 conditions. Nothing here places or authorizes an order."""

    def __init__(
        self,
        audit_path: str = "audit.log",
        min_soak_days: int = DEFAULT_MIN_SOAK_DAYS,
        min_clean_cycles: int = DEFAULT_MIN_CLEAN_CYCLES,
        kill_switch_max_age_days: int = DEFAULT_KILL_SWITCH_MAX_AGE_DAYS,
        max_drawdown_pct: float = DEFAULT_MAX_DRAWDOWN_PCT,
    ):
        self.audit_path = Path(audit_path)
        self.min_soak_days = min_soak_days
        self.min_clean_cycles = min_clean_cycles
        self.kill_switch_max_age_days = kill_switch_max_age_days
        self.max_drawdown_pct = max_drawdown_pct

    # ---- audit replay -------------------------------------------------

    def _events(self) -> List[dict]:
        if not self.audit_path.exists():
            return []
        events = []
        with open(self.audit_path) as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    @staticmethod
    def _ts(event: dict) -> Optional[datetime]:
        raw = event.get("logged_at") or event.get("timestamp")
        if not raw:
            return None
        try:
            dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
            return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
        except ValueError:
            return None

    def chain_hash(self) -> str:
        """Hash of the whole log. Store this outside the repo; a changed hash
        with an unchanged story is tampering."""
        if not self.audit_path.exists():
            return ""
        h = hashlib.sha256()
        with open(self.audit_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    # ---- the twelve ----------------------------------------------------

    def evaluate(
        self,
        broker=None,
        rules: Optional[dict] = None,
        config: Optional[dict] = None,
    ) -> GateResult:
        events = self._events()
        rules = rules or {}
        config = config or {}
        checks: List[GateCheck] = []

        def add(name, passed, reason, priority, blocking=True):
            checks.append(GateCheck(name, bool(passed), reason, priority, blocking))

        # 1. Target account identity proven
        try:
            if broker is None:
                add("target_account_proven", False,
                    "no broker supplied; cannot verify which account this would hit", 1)
            else:
                proof = getattr(broker, "paper_proof", lambda: {})()
                expected = config.get("expected_account")
                accounts = proof.get("managed_accounts", [])
                if not accounts:
                    add("target_account_proven", False,
                        "broker returned no managed accounts", 1)
                elif expected and expected not in accounts:
                    add("target_account_proven", False,
                        f"expected account {expected} not in {accounts}", 1)
                else:
                    add("target_account_proven", True,
                        f"resolved to {accounts}", 1)
        except Exception as exc:
            add("target_account_proven", False, f"check raised: {exc}", 1)

        # 2. Kill switch tested recently (by a real drill, not a manual field)
        drills = [e for e in events if e.get("event") == "kill_switch_drill"
                  and e.get("result") == "passed"]
        if not drills:
            add("kill_switch_tested", False,
                "no passing kill-switch drill in the audit log", 2)
        else:
            last = max((self._ts(e) for e in drills if self._ts(e)), default=None)
            if last is None:
                add("kill_switch_tested", False, "drill has no readable timestamp", 2)
            else:
                age = (datetime.now(timezone.utc) - last).days
                add("kill_switch_tested", age <= self.kill_switch_max_age_days,
                    f"last drill {age}d ago (max {self.kill_switch_max_age_days}d)", 2)

        # 3. Position and notional caps configured AND proven to bite
        ceiling = (rules.get("ceiling") or {})
        caps_configured = bool(rules.get("max_position_size")) and bool(ceiling.get("current"))
        cap_fired = any(
            e.get("event") in ("execution_blocked", "race_decision")
            and "ceiling" in json.dumps(e.get("reason", "") or e.get("veto_reason", "") or "")
            for e in events
        )
        add("position_caps_enforced", caps_configured and cap_fired,
            "caps configured" if caps_configured else "max_position_size/ceiling missing",
            3) if not (caps_configured and cap_fired) else add(
            "position_caps_enforced", True, "caps configured and observed rejecting an order", 3)

        # 4. Broker-side fail-safe present
        add("broker_side_failsafe", bool(config.get("broker_side_stop")),
            "no broker-side stop/auto-flatten configured; an in-process check dies "
            "with the process", 4)

        # 5. Soak duration + clean cycles
        cycles = [e for e in events if e.get("event") in ("race_finished", "cycle_completed")]
        stamps = [self._ts(e) for e in events if self._ts(e)]
        if not stamps:
            add("soak_completed", False, "audit log is empty", 5)
        else:
            span_days = (max(stamps) - min(stamps)).days
            enough_time = span_days >= self.min_soak_days
            enough_cycles = len(cycles) >= self.min_clean_cycles
            add("soak_completed", enough_time and enough_cycles,
                f"{span_days}d elapsed (need {self.min_soak_days}), "
                f"{len(cycles)} cycles (need {self.min_clean_cycles})", 5)

        # 6. No unresolved errors
        errors = [e for e in events if e.get("event") in ("error", "execution_failed")]
        resolved = {e.get("resolves") for e in events if e.get("event") == "error_resolved"}
        unresolved = [e for e in errors if e.get("id") not in resolved]
        add("no_unresolved_errors", not unresolved,
            f"{len(unresolved)} unresolved error event(s)", 6)

        # 7. Drawdown within bounds
        dds = [float(e["max_drawdown_pct"]) for e in events
               if isinstance(e.get("max_drawdown_pct"), (int, float))]
        worst = max(dds) if dds else None
        if worst is None:
            add("drawdown_within_bounds", False, "no drawdown observations recorded", 7)
        else:
            add("drawdown_within_bounds", worst <= self.max_drawdown_pct,
                f"worst observed {worst:.1f}% vs max {self.max_drawdown_pct:.1f}%", 7)

        # 8. Credentials verified read-only against the real account
        add("live_credentials_verified", bool(config.get("live_credentials_verified")),
            "live credentials never verified read-only", 8)

        # 9. Alerting proven to actually arrive
        alerts = [e for e in events if e.get("event") == "alert_received"]
        add("alerting_confirmed", bool(alerts),
            "no alert_received event; Knight's 97 alerts went to an unwatched channel", 9)

        # 10. Deployment integrity
        commit = config.get("git_commit")
        dirty = config.get("git_dirty", True)
        add("deployment_pinned", bool(commit) and not dirty,
            f"commit={commit or 'unknown'}, uncommitted_changes={dirty}", 10)

        # 11. Governance invariants intact
        problems = []
        if ceiling.get("can_auto_increase") is not False:
            problems.append("ceiling.can_auto_increase is not false")
        if not rules.get("floor_cash") and not config.get("base_stake"):
            problems.append("no floor_cash / base_stake configured")
        if config.get("auto_approve"):
            problems.append("auto_approve is enabled — forbidden in live")
        add("governance_invariants", not problems,
            "; ".join(problems) or "invariants intact", 11)

        # 12. Fractional path verified (IBKR docs are inconsistent here)
        if not config.get("uses_fractional", True):
            add("fractional_verified", True, "fractional not used", 12, blocking=False)
        else:
            frac = [e for e in events
                    if e.get("event") == "order_submitted"
                    and isinstance(e.get("filled"), (int, float))
                    and 0 < float(e["filled"]) < 1]
            add("fractional_verified", bool(frac),
                "no successful fractional paper fill recorded; IBKR's own docs "
                "contradict each other on API fractional support", 12)

        passed = all(c.passed for c in checks if c.blocking)
        return GateResult(passed=passed, checks=checks)


async def run_kill_switch_drill(broker, audit, cancel_fn: Optional[Callable] = None) -> dict:
    """Actually exercise the cancel path, then record it. The only thing that
    may write `kill_switch_drill`."""
    record = {"event": "kill_switch_drill", "result": "failed", "detail": ""}
    try:
        cancel = cancel_fn or getattr(broker, "cancel_all", None)
        if cancel is None:
            record["detail"] = "broker exposes no cancel_all"
        else:
            ok = await cancel()
            record["result"] = "passed" if ok else "failed"
            record["detail"] = "global cancel acknowledged" if ok else "cancel returned falsy"
    except Exception as exc:
        record["detail"] = f"{type(exc).__name__}: {exc}"
    await audit.log(record)
    return record
