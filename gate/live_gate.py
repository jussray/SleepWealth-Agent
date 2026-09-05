"""Pre-live gate.

Turns the go-live checklist into code. Fail-closed: any exception is a failure,
an unknown state is a failure, an empty audit log is a failure.

IMPORTANT: a passing result means only that these advisory/pre-live control
checks are satisfied. Repository policy still disables live broker execution.
This gate never grants execution authority.

Audit-derived evidence is accepted only from one immutable, hash-chained
snapshot whose trusted start and terminal hashes are supplied externally.
Kill-switch receipts additionally require a separately trusted HMAC key.
"""

import asyncio
import hashlib
import hmac
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
KILL_SWITCH_RECEIPT_VERSION = 4
MIN_RECEIPT_KEY_BYTES = 32


def _receipt_key(value) -> bytes:
    if isinstance(value, bytes):
        key = value
    elif isinstance(value, str):
        key = value.encode("utf-8")
    else:
        return b""
    return key if len(key) >= MIN_RECEIPT_KEY_BYTES else b""


def _broker_receipt_binding(broker, expected_account: Optional[str] = None):
    """Fingerprint the broker proof and select exactly one target account."""
    if broker is None:
        return "", None, [], {}
    proof = getattr(broker, "paper_proof", lambda: {})()
    if not isinstance(proof, dict):
        return "", None, [], {}

    raw_accounts = proof.get("managed_accounts", [])
    if not isinstance(raw_accounts, (list, tuple)):
        return "", None, [], proof
    accounts = sorted({str(account) for account in raw_accounts if str(account)})
    target = str(expected_account) if expected_account else (accounts[0] if len(accounts) == 1 else None)
    if target not in accounts:
        target = None

    binding_payload = {
        "broker_class": f"{broker.__class__.__module__}.{broker.__class__.__qualname__}",
        "port": proof.get("port"),
        "managed_accounts": accounts,
        "configured_paper": proof.get("configured_paper"),
        "provably_paper": proof.get("provably_paper"),
    }
    binding = hashlib.sha256(
        json.dumps(binding_payload, default=str, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return binding, target, accounts, proof


def _kill_switch_payload(record: dict) -> bytes:
    payload = {
        "event": record.get("event"),
        "receipt_version": record.get("receipt_version"),
        "result": record.get("result"),
        "detail": record.get("detail"),
        "paper_proven": record.get("paper_proven"),
        "working_order_id": record.get("working_order_id"),
        "pre_cancel_status": record.get("pre_cancel_status"),
        "terminal_status": record.get("terminal_status"),
        "broker_cancel_path": record.get("broker_cancel_path"),
        "broker_status_path": record.get("broker_status_path"),
        "occurred_at": record.get("occurred_at"),
        "target_account": record.get("target_account"),
        "broker_proof_hash": record.get("broker_proof_hash"),
    }
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _sign_kill_switch_receipt(record: dict, receipt_key) -> str:
    key = _receipt_key(receipt_key)
    if not key:
        return ""
    return hmac.new(key, _kill_switch_payload(record), hashlib.sha256).hexdigest()


def _valid_kill_switch_receipt(record: dict, receipt_key) -> bool:
    provided = record.get("receipt_auth")
    expected = _sign_kill_switch_receipt(record, receipt_key)
    if not (
        isinstance(provided, str)
        and len(provided) == 64
        and provided.isascii()
        and all(char in "0123456789abcdefABCDEF" for char in provided)
        and bool(expected)
    ):
        return False
    return hmac.compare_digest(provided.lower(), expected.lower())


def _receipt_occurrence(record: dict) -> Optional[datetime]:
    raw = record.get("occurred_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


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
    """Evaluates an externally anchored audit snapshot plus readiness conditions."""

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

        try:
            integrity_ok, integrity_reason, verified_events, _observed_head = (
                AuditLogger.verify_snapshot_file(
                    self.audit_path,
                    config.get("audit_start_hash"),
                    config.get("audit_head_hash"),
                )
            )
            if integrity_ok:
                events = verified_events
            add("audit_integrity", integrity_ok, integrity_reason, 0)
        except Exception as exc:
            add("audit_integrity", False, f"integrity check raised: {exc}", 0)

        broker_binding = ""
        target_account = None
        managed_accounts: list[str] = []
        try:
            if broker is None:
                add("target_account_proven", False,
                    "no broker supplied; cannot verify which account this would hit", 1)
            else:
                broker_binding, target_account, managed_accounts, _proof = _broker_receipt_binding(
                    broker, config.get("expected_account")
                )
                expected = config.get("expected_account")
                if not managed_accounts:
                    add("target_account_proven", False,
                        "broker returned no managed accounts", 1)
                elif expected and expected not in managed_accounts:
                    add("target_account_proven", False,
                        f"expected account {expected} not in {managed_accounts}", 1)
                elif target_account is None:
                    add("target_account_proven", False,
                        "multiple managed accounts require an explicit expected_account", 1)
                else:
                    add("target_account_proven", True,
                        f"resolved to {target_account} within {managed_accounts}", 1)
        except Exception as exc:
            add("target_account_proven", False, f"check raised: {exc}", 1)

        receipt_key = config.get("kill_switch_receipt_key")
        drills = [
            e for e in events
            if e.get("event") == "kill_switch_drill"
            and e.get("receipt_version") == KILL_SWITCH_RECEIPT_VERSION
            and e.get("result") == "passed"
            and e.get("paper_proven") is True
            and bool(e.get("working_order_id"))
            and e.get("broker_cancel_path") == "cancel_all"
            and e.get("broker_status_path") == "get_order_status"
            and e.get("pre_cancel_status") in WORKING_STATES
            and e.get("terminal_status") in CANCELLED_STATES
            and bool(broker_binding)
            and e.get("broker_proof_hash") == broker_binding
            and bool(target_account)
            and e.get("target_account") == target_account
            and _receipt_occurrence(e) is not None
            and _valid_kill_switch_receipt(e, receipt_key)
        ]
        if not drills:
            add("kill_switch_tested", False,
                "no authenticated anchored broker/account-bound paper kill-switch drill with signed occurrence time, working-state, and terminal cancellation proof", 2)
        else:
            last = max((_receipt_occurrence(e) for e in drills if _receipt_occurrence(e)), default=None)
            if last is None:
                add("kill_switch_tested", False, "drill has no authenticated occurrence timestamp", 2)
            else:
                now = datetime.now(timezone.utc)
                age_seconds = (now - last).total_seconds()
                max_age_seconds = self.kill_switch_max_age_days * 86400
                if age_seconds < 0:
                    add("kill_switch_tested", False, "drill occurrence timestamp is in the future", 2)
                else:
                    age_days = int(age_seconds // 86400)
                    add("kill_switch_tested", age_seconds <= max_age_seconds,
                        f"last verified drill {age_days}d ago (max {self.kill_switch_max_age_days}d)", 2)

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

        add("broker_side_failsafe", bool(config.get("broker_side_stop")),
            "no broker-side stop/auto-flatten configured; an in-process check dies with the process", 4)

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

        errors = [e for e in events if e.get("event") in ("error", "execution_failed")]
        resolved = {e.get("resolves") for e in events if e.get("event") == "error_resolved"}
        unresolved = [e for e in errors if e.get("id") not in resolved]
        add("no_unresolved_errors", not unresolved,
            f"{len(unresolved)} unresolved anchored error event(s)", 6)

        dds = [float(e["max_drawdown_pct"]) for e in events
               if isinstance(e.get("max_drawdown_pct"), (int, float))]
        worst = max(dds) if dds else None
        if worst is None:
            add("drawdown_within_bounds", False, "no anchored drawdown observations recorded", 7)
        else:
            add("drawdown_within_bounds", worst <= self.max_drawdown_pct,
                f"worst observed {worst:.1f}% vs max {self.max_drawdown_pct:.1f}%", 7)

        add("live_credentials_verified", bool(config.get("live_credentials_verified")),
            "live credentials never verified read-only", 8)

        alerts = [e for e in events if e.get("event") == "alert_received"]
        add("alerting_confirmed", bool(alerts),
            "no anchored alert_received event; synthetic alert receipt required", 9)

        commit = config.get("git_commit")
        dirty = config.get("git_dirty", True)
        add("deployment_pinned", bool(commit) and not dirty,
            f"commit={commit or 'unknown'}, uncommitted_changes={dirty}", 10)

        problems = []
        if ceiling.get("can_auto_increase") is not False:
            problems.append("ceiling.can_auto_increase is not false")
        if not rules.get("floor_cash") and not config.get("base_stake"):
            problems.append("no floor_cash / base_stake configured")
        if config.get("auto_approve"):
            problems.append("auto_approve is enabled — forbidden in live")
        add("governance_invariants", not problems,
            "; ".join(problems) or "invariants intact", 11)

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
    receipt_key=None,
    expected_account: Optional[str] = None,
    status_attempts: int = 10,
    status_interval: float = 0.2,
) -> dict:
    """Exercise broker-bound cancel/status methods and mint an authenticated receipt.

    The receipt HMAC key must come from a separately trusted control plane. Test
    callbacks are intentionally not accepted by this API.
    """
    broker_binding, target_account, managed_accounts, broker_proof = _broker_receipt_binding(
        broker, expected_account
    )
    record = {
        "event": "kill_switch_drill",
        "receipt_version": KILL_SWITCH_RECEIPT_VERSION,
        "result": "failed",
        "detail": "",
        "paper_proven": False,
        "working_order_id": working_order_id,
        "pre_cancel_status": None,
        "terminal_status": None,
        "broker_cancel_path": "cancel_all",
        "broker_status_path": "get_order_status",
        "occurred_at": datetime.now(timezone.utc).isoformat(),
        "target_account": target_account,
        "broker_proof_hash": broker_binding,
    }
    try:
        key = _receipt_key(receipt_key)
        if not key:
            record["detail"] = f"trusted kill-switch receipt key must be at least {MIN_RECEIPT_KEY_BYTES} bytes"
        elif not broker_binding or not managed_accounts or target_account is None:
            record["detail"] = "broker/account identity could not be proven for this drill"
        else:
            paper_proven = bool(getattr(broker, "is_paper_only", lambda: False)())
            if broker_proof.get("provably_paper") is False:
                paper_proven = False
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

    record["receipt_auth"] = _sign_kill_switch_receipt(record, receipt_key)
    await audit.log(record)
    return record