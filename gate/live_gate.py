"""Pre-live gate.

Turns the go-live checklist into code. Fail-closed: any exception is a failure,
an unknown state is a failure, an empty audit log is a failure.

IMPORTANT: a passing result means only that these advisory/pre-live control
checks are satisfied. Repository policy still disables live broker execution.
This gate never grants execution authority.

Audit-derived evidence is accepted only from one immutable, hash-chained
snapshot whose terminal entry hash matches an externally supplied anchor.
Unchained legacy-prefix events are never eligible gate evidence.
"""

import asyncio
import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from audit.logger import AuditLogger

DEFAULT_MIN_SOAK_DAYS = 30
DEFAULT_MIN_CLEAN_CYCLES = 20
DEFAULT_KILL_SWITCH_MAX_AGE_DAYS = 7
DEFAULT_MAX_DRAWDOWN_PCT = 10.0

CANCELLED_STATES = {"Cancelled", "ApiCancelled"}
WORKING_STATES = {"PendingSubmit", "PreSubmitted", "Submitted", "ApiPending"}


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
    """Evaluates an anchored audit snapshot plus the twelve readiness conditions."""

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
        """Whole-file checksum for diagnostics; not an audit trust anchor."""
        if not self.audit_path.exists():
            return ""
        h = hashlib.sha256()
        with open(self.audit_path, "rb") as fh:
            for chunk in iter(lambda: fh.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()

    def evaluate(
        self,
        broker=None,
        rules: Optional[dict] = None,
        config: Optional[dict] = None,
    ) -> GateResult:
        rules = rules or {}
        config = config or {}
        checks: List[GateCheck] = []
        events: List[dict] = []

        def add(name, passed, reason, priority, blocking=True):
            checks.append(GateCheck(name, bool(passed), reason, priority, blocking))

        # Read exactly one snapshot. All audit-derived checks below consume only
        # events returned from this verified snapshot, never a second file read.
        try:
            integrity_ok, integrity_reason, verified_events, _observed_head = (
                AuditLogger.verify_snapshot_file(
                    self.audit_path,
                    config.get("audit_head_hash"),
                )
            )
            if integrity_ok:
                events = verified_events
            add("audit_integrity", integrity_ok, integrity_reason, 0)
        except Exception as exc:
            add("audit_integrity", False, f"integrity check raised: {exc}", 0)

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

        # 2. Kill switch tested recently by cancelling a real working paper order.
        drills = [
            e for e in events
            if e.get("event") == "kill_switch_drill"
            and e.get("receipt_version") == 2
            and e.get("result") == "passed"
            and e.get("paper_proven") is True
            and bool(e.get("working_order_id"))
            and e.get("broker_cancel_path") == "cancel_all"
            and e.get("broker_status_path") == "get_order_status"
            and e.get("pre_cancel_status") in WORKING_STATES
            and e.get("terminal_status") in CANCELLED_STATES
        ]
        if not drills:
            add("kill_switch_tested", False,
                "no anchored broker-bound paper kill-switch drill with recorded working-state and terminal cancellation proof", 2)
        else:
            last = max((self._ts(e) for e in drills if self._ts(e)), default=None)
            if last is None:
                add("kill_switch_tested", False, "drill has no readable timestamp", 2)
            else:
                age = (datetime.now(timezone.utc) - last).days
                add("kill_switch_tested", age <= self.kill_switch_max_age_days,
                    f"last verified drill {age}d ago (max {self.kill_switch_max_age_days}d)", 2)

        # 3. Position and notional caps configured AND proven to bite
        ceiling = rules.get("ceiling") or {}
        caps_configured = bool(rules.get("max_position_size")) and bool(ceiling.get("current"))
        cap_fired = any(
            e.get("event") in ("execution_blocked", "race_decision")
            and "ceiling" in json.dumps(e.get("reason", "") or e.get("veto_reason", "") or "")
            for e in events
        )
        if caps_configured and cap_fired:
            add("position_caps_enforced", True,
                "caps configured and observed rejecting an order", 3)
        else:
            add("position_caps_enforced", False,
                "caps configured but no rejection proof" if caps_configured
                else "max_position_size/ceiling missing", 3)

        # 4. Broker-side fail-safe present
        add("broker_side_failsafe", bool(config.get("broker_side_stop")),
            "no broker-side stop/auto-flatten configured; an in-process check dies with the process", 4)

        # 5. Soak duration + clean cycles
        cycles = [e for e in events if e.get("event") in ("race_finished", "cycle_completed")]
        stamps = [self._ts(e) for e in events if self._ts(e)]
        if not stamps:
            add("soak_completed", False, "no anchored soak evidence", 5)
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
            f"{len(unresolved)} unresolved anchored error event(s)", 6)

        # 7. Drawdown within bounds
        dds = [float(e["max_drawdown_pct"]) for e in events
               if isinstance(e.get("max_drawdown_pct"), (int, float))]
        worst = max(dds) if dds else None
        if worst is None:
            add("drawdown_within_bounds", False, "no anchored drawdown observations recorded", 7)
        else:
            add("drawdown_within_bounds", worst <= self.max_drawdown_pct,
                f"worst observed {worst:.1f}% vs max {self.max_drawdown_pct:.1f}%", 7)

        # 8. Credentials verified read-only against the real account
        add("live_credentials_verified", bool(config.get("live_credentials_verified")),
            "live credentials never verified read-only", 8)

        # 9. Alerting proven to actually arrive
        alerts = [e for e in events if e.get("event") == "alert_received"]
        add("alerting_confirmed", bool(alerts),
            "no anchored alert_received event; synthetic alert receipt required", 9)

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

        # 12. Fractional path verified if used
        if not config.get("uses_fractional", True):
            add("fractional_verified", True, "fractional not used", 12, blocking=False)
        else:
            frac = [
                e for e in events
                if e.get("event") == "order_submitted"
                and isinstance(e.get("filled"), (int, float))
                and 0 < float(e["filled"]) < 1
            ]
            add("fractional_verified", bool(frac),
                "no anchored successful fractional paper fill recorded", 12)

        passed = all(c.passed for c in checks if c.blocking)
        return GateResult(passed=passed, checks=checks)


async def run_kill_switch_drill(
    broker,
    audit,
    working_order_id: Optional[str] = None,
    status_attempts: int = 10,
    status_interval: float = 0.2,
) -> dict:
    """Exercise broker-bound cancel/status methods on a working paper order.

    Test callbacks are intentionally not accepted by this trusted receipt API.
    The supplied broker itself must prove paper-only mode and expose the actual
    `cancel_all` and `get_order_status` methods used to mint the receipt.
    """
    record = {
        "event": "kill_switch_drill",
        "receipt_version": 2,
        "result": "failed",
        "detail": "",
        "paper_proven": False,
        "working_order_id": working_order_id,
        "pre_cancel_status": None,
        "terminal_status": None,
        "broker_cancel_path": "cancel_all",
        "broker_status_path": "get_order_status",
    }
    try:
        paper_proven = bool(getattr(broker, "is_paper_only", lambda: False)())
        record["paper_proven"] = paper_proven
        if not paper_proven:
            record["detail"] = "broker is not provably paper"
        elif not working_order_id:
            record["detail"] = "working paper order id is required"
        else:
            cancel = getattr(broker, "cancel_all", None)
            status_reader = getattr(broker, "get_order_status", None)
            if not callable(cancel) or not callable(status_reader):
                record["detail"] = "broker lacks bound cancel_all/get_order_status proof path"
            else:
                before = await status_reader(working_order_id)
                before_status = before.get("status") if isinstance(before, dict) else str(before)
                record["pre_cancel_status"] = before_status
                if before_status not in WORKING_STATES:
                    record["detail"] = f"probe order was not working before cancel: {before_status}"
                else:
                    cancel_ok = await cancel()
                    if not cancel_ok:
                        record["detail"] = "global cancel returned falsy"
                    else:
                        for _ in range(max(1, status_attempts)):
                            status = await status_reader(working_order_id)
                            state = status.get("status") if isinstance(status, dict) else str(status)
                            record["terminal_status"] = state
                            if state in CANCELLED_STATES:
                                record["result"] = "passed"
                                record["detail"] = "working paper order cancelled by broker-bound global kill path"
                                break
                            if state == "Filled":
                                record["detail"] = "probe filled before cancellation could be proven"
                                break
                            await asyncio.sleep(max(0.0, status_interval))
                        else:
                            record["detail"] = (
                                f"cancel not terminal after {max(1, status_attempts)} status checks"
                            )
    except Exception as exc:
        record["detail"] = f"{type(exc).__name__}: {exc}"

    await audit.log(record)
    return record
