"""The gate must fail closed and never mint execution authority."""
import json

from audit.logger import AuditLogger
from gate.live_gate import GateCheck, GateResult, LiveGate, run_kill_switch_drill


def test_gate_closed_on_empty_audit(tmp_path):
    gate = LiveGate(audit_path=str(tmp_path / "nope.log"))
    result = gate.evaluate(rules={}, config={})
    assert result.passed is False
    assert len(result.failures) >= 8
    assert result.to_dict()["execution_authorized"] is False
    assert result.to_dict()["authority_ceiling"] == "advisory"
    assert "Continue mock/paper only" in result.render()


def test_gate_requires_external_audit_anchor(tmp_path):
    log = tmp_path / "a.log"
    audit = AuditLogger(str(log))

    async def write_one():
        await audit.log({"event": "cycle_completed", "cycle": 1})

    import asyncio
    asyncio.run(write_one())

    result = LiveGate(audit_path=str(log)).evaluate(rules={}, config={})
    integrity = next(c for c in result.checks if c.name == "audit_integrity")
    assert integrity.passed is False
    assert "trusted terminal audit hash is required" in integrity.reason


def test_gate_blocks_when_auto_approve_enabled(tmp_path):
    log = tmp_path / "a.log"
    log.write_text(json.dumps({"event": "race_finished", "logged_at": "2026-01-01T00:00:00+00:00"}) + "\n")
    gate = LiveGate(audit_path=str(log))
    result = gate.evaluate(
        rules={"ceiling": {"can_auto_increase": False}, "floor_cash": 5.0},
        config={"auto_approve": True},
    )
    inv = next(c for c in result.checks if c.name == "governance_invariants")
    assert inv.passed is False
    assert "auto_approve" in inv.reason


def test_gate_blocks_auto_increasing_ceiling(tmp_path):
    log = tmp_path / "a.log"
    log.write_text("")
    gate = LiveGate(audit_path=str(log))
    result = gate.evaluate(
        rules={"ceiling": {"can_auto_increase": True}, "floor_cash": 5.0}, config={}
    )
    inv = next(c for c in result.checks if c.name == "governance_invariants")
    assert inv.passed is False


def test_legacy_kill_switch_pass_event_is_not_enough(tmp_path):
    log = tmp_path / "a.log"
    log.write_text(json.dumps({"event": "kill_switch_drill", "result": "passed"}) + "\n")
    gate = LiveGate(audit_path=str(log))
    result = gate.evaluate(rules={}, config={})
    ks = next(c for c in result.checks if c.name == "kill_switch_tested")
    assert ks.passed is False
    assert "working-state" in ks.reason


async def test_legacy_prefix_cannot_satisfy_anchored_gate_evidence(tmp_path):
    path = tmp_path / "audit.log"
    path.write_text(json.dumps({
        "event": "kill_switch_drill",
        "receipt_version": 2,
        "result": "passed",
        "paper_proven": True,
        "working_order_id": "forged-legacy",
        "broker_cancel_path": "cancel_all",
        "broker_status_path": "get_order_status",
        "pre_cancel_status": "Submitted",
        "terminal_status": "Cancelled",
        "logged_at": "2026-09-01T00:00:00+00:00",
    }) + "\n")
    audit = AuditLogger(str(path))
    await audit.log({"event": "cycle_completed", "cycle": 1})
    anchor = audit.observed_terminal_hash()

    result = LiveGate(audit_path=str(path)).evaluate(
        rules={},
        config={"audit_head_hash": anchor},
    )
    integrity = next(c for c in result.checks if c.name == "audit_integrity")
    ks = next(c for c in result.checks if c.name == "kill_switch_tested")
    assert integrity.passed is True
    assert ks.passed is False


async def test_kill_switch_drill_requires_broker_bound_working_paper_order_and_terminal_cancel(tmp_path):
    path = tmp_path / "audit.log"
    audit = AuditLogger(str(path))

    class PaperBroker:
        def __init__(self):
            self.states = iter(["Submitted", "Submitted", "Cancelled"])
            self.cancel_called = False

        def is_paper_only(self):
            return True

        async def get_order_status(self, _order_id):
            return {"status": next(self.states)}

        async def cancel_all(self):
            self.cancel_called = True
            return True

    broker = PaperBroker()
    record = await run_kill_switch_drill(
        broker,
        audit,
        working_order_id="paper-42",
        status_attempts=3,
        status_interval=0,
    )

    assert broker.cancel_called is True
    assert record["receipt_version"] == 2
    assert record["result"] == "passed"
    assert record["paper_proven"] is True
    assert record["pre_cancel_status"] == "Submitted"
    assert record["terminal_status"] == "Cancelled"
    assert record["broker_cancel_path"] == "cancel_all"
    assert record["broker_status_path"] == "get_order_status"

    anchor = audit.observed_terminal_hash()
    gate = LiveGate(audit_path=str(path))
    result = gate.evaluate(rules={}, config={"audit_head_hash": anchor})
    integrity = next(c for c in result.checks if c.name == "audit_integrity")
    ks = next(c for c in result.checks if c.name == "kill_switch_tested")
    assert integrity.passed is True
    assert ks.passed is True


async def test_gate_rejects_passed_receipt_without_recorded_working_state(tmp_path):
    path = tmp_path / "audit.log"
    audit = AuditLogger(str(path))
    await audit.log({
        "event": "kill_switch_drill",
        "receipt_version": 2,
        "result": "passed",
        "paper_proven": True,
        "working_order_id": "paper-42",
        "broker_cancel_path": "cancel_all",
        "broker_status_path": "get_order_status",
        "pre_cancel_status": "Cancelled",
        "terminal_status": "Cancelled",
    })
    anchor = audit.observed_terminal_hash()

    result = LiveGate(audit_path=str(path)).evaluate(
        rules={},
        config={"audit_head_hash": anchor},
    )
    integrity = next(c for c in result.checks if c.name == "audit_integrity")
    ks = next(c for c in result.checks if c.name == "kill_switch_tested")
    assert integrity.passed is True
    assert ks.passed is False
    assert "working-state" in ks.reason


async def test_kill_switch_receipt_api_rejects_forged_callbacks(tmp_path):
    path = tmp_path / "audit.log"
    audit = AuditLogger(str(path))

    class PaperBroker:
        def is_paper_only(self):
            return True

        async def get_order_status(self, _order_id):
            return {"status": "Submitted"}

        async def cancel_all(self):
            return False

    async def forged_status(_order_id):
        return {"status": "Cancelled"}

    async def forged_cancel():
        return True

    try:
        await run_kill_switch_drill(
            PaperBroker(),
            audit,
            working_order_id="paper-42",
            cancel_fn=forged_cancel,
            status_fn=forged_status,
        )
    except TypeError:
        pass
    else:
        raise AssertionError("trusted kill-switch API accepted injectable proof callbacks")

    assert not path.exists()


async def test_kill_switch_drill_cannot_pass_without_order_id(tmp_path):
    path = tmp_path / "audit.log"
    audit = AuditLogger(str(path))

    class PaperBroker:
        def is_paper_only(self):
            return True

    record = await run_kill_switch_drill(PaperBroker(), audit)
    assert record["result"] == "failed"
    assert "order id is required" in record["detail"]


async def test_gate_rejects_entry_boundary_truncation_against_trusted_anchor(tmp_path):
    path = tmp_path / "audit.log"
    audit = AuditLogger(str(path))
    await audit.log({"event": "cycle_completed", "cycle": 1})
    await audit.log({"event": "error", "id": "do-not-hide"})
    trusted_anchor = audit.observed_terminal_hash()

    lines = path.read_text().splitlines()
    path.write_text(lines[0] + "\n")

    result = LiveGate(audit_path=str(path)).evaluate(
        rules={},
        config={"audit_head_hash": trusted_anchor},
    )
    integrity = next(c for c in result.checks if c.name == "audit_integrity")
    assert integrity.passed is False
    assert "terminal hash does not match trusted external anchor" in integrity.reason


async def test_gate_uses_one_verified_snapshot_for_integrity_and_events(tmp_path, monkeypatch):
    path = tmp_path / "audit.log"
    audit = AuditLogger(str(path))
    await audit.log({"event": "cycle_completed", "cycle": 1})
    anchor = audit.observed_terminal_hash()

    original = AuditLogger.verify_snapshot_file
    calls = {"count": 0}

    def verify_then_append(log_path, expected_head_hash):
        calls["count"] += 1
        result = original(log_path, expected_head_hash)
        with open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps({"event": "error", "id": "later-unanchored"}) + "\n")
        return result

    monkeypatch.setattr(AuditLogger, "verify_snapshot_file", staticmethod(verify_then_append))
    result = LiveGate(audit_path=str(path)).evaluate(
        rules={},
        config={"audit_head_hash": anchor},
    )

    assert calls["count"] == 1
    integrity = next(c for c in result.checks if c.name == "audit_integrity")
    errors = next(c for c in result.checks if c.name == "no_unresolved_errors")
    assert integrity.passed is True
    assert errors.passed is True


def test_passing_pre_live_controls_never_claim_live_execution_authority():
    result = GateResult(
        passed=True,
        checks=[GateCheck("example_control", True, "proven", 1)],
    )

    rendered = result.render()
    receipt = result.to_dict()

    assert "PRE-LIVE CONTROLS SATISFIED" in rendered
    assert "execution is still disabled by repository policy" in rendered
    assert "live trading permitted" not in rendered
    assert receipt["passed"] is True
    assert receipt["execution_authorized"] is False
    assert receipt["authority_ceiling"] == "advisory"
