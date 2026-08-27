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
    assert "terminal cancellation proof" in ks.reason


async def test_kill_switch_drill_requires_working_paper_order_and_terminal_cancel(tmp_path):
    path = tmp_path / "audit.log"
    audit = AuditLogger(str(path))

    class PaperBroker:
        def is_paper_only(self):
            return True

    states = iter(["Submitted", "Submitted", "Cancelled"])

    async def status(_order_id):
        return {"status": next(states)}

    async def cancel_all():
        return True

    record = await run_kill_switch_drill(
        PaperBroker(),
        audit,
        working_order_id="paper-42",
        cancel_fn=cancel_all,
        status_fn=status,
        status_attempts=3,
        status_interval=0,
    )

    assert record["result"] == "passed"
    assert record["paper_proven"] is True
    assert record["pre_cancel_status"] == "Submitted"
    assert record["terminal_status"] == "Cancelled"

    gate = LiveGate(audit_path=str(path))
    result = gate.evaluate(rules={}, config={})
    integrity = next(c for c in result.checks if c.name == "audit_integrity")
    ks = next(c for c in result.checks if c.name == "kill_switch_tested")
    assert integrity.passed is True
    assert ks.passed is True


async def test_kill_switch_drill_cannot_pass_without_order_id(tmp_path):
    path = tmp_path / "audit.log"
    audit = AuditLogger(str(path))

    class PaperBroker:
        def is_paper_only(self):
            return True

    record = await run_kill_switch_drill(PaperBroker(), audit)
    assert record["result"] == "failed"
    assert "order id is required" in record["detail"]


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
