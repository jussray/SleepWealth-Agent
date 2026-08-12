"""The gate must fail closed."""
import json
from pathlib import Path

from gate.live_gate import LiveGate


def test_gate_closed_on_empty_audit(tmp_path):
    gate = LiveGate(audit_path=str(tmp_path / "nope.log"))
    result = gate.evaluate(rules={}, config={})
    assert result.passed is False
    assert len(result.failures) >= 8


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


def test_kill_switch_check_requires_a_real_drill(tmp_path):
    log = tmp_path / "a.log"
    log.write_text(json.dumps({"event": "kill_switch_drill", "result": "failed"}) + "\n")
    gate = LiveGate(audit_path=str(log))
    result = gate.evaluate(rules={}, config={})
    ks = next(c for c in result.checks if c.name == "kill_switch_tested")
    assert ks.passed is False
