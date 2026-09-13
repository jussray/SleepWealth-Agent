"""Simulation governance gate must fail closed."""

import json

from gate.live_gate import LiveGate


def test_gate_closed_on_empty_audit(tmp_path):
    gate = LiveGate(audit_path=str(tmp_path / "nope.log"))
    result = gate.evaluate(rules={}, config={})
    assert result.passed is False
    assert any(check.name == "audit_evidence_present" and not check.passed for check in result.checks)


def test_gate_blocks_auto_increasing_ceiling(tmp_path):
    log = tmp_path / "a.log"
    log.write_text(json.dumps({"event": "cycle_completed"}) + "\n")
    gate = LiveGate(audit_path=str(log))
    result = gate.evaluate(
        rules={"ceiling": {"can_auto_increase": True}, "floor_cash": 5.0},
        config={},
    )
    check = next(c for c in result.checks if c.name == "ceiling_remains_human_locked")
    assert check.passed is False


def test_gate_blocks_live_enabled_flag(tmp_path):
    log = tmp_path / "a.log"
    log.write_text(json.dumps({"event": "cycle_completed"}) + "\n")
    gate = LiveGate(audit_path=str(log))
    result = gate.evaluate(
        rules={"ceiling": {"can_auto_increase": False}},
        config={"live_enabled": True},
    )
    check = next(c for c in result.checks if c.name == "live_execution_disabled")
    assert check.passed is False


def test_gate_blocks_credential_like_config(tmp_path):
    log = tmp_path / "a.log"
    log.write_text(json.dumps({"event": "cycle_completed"}) + "\n")
    gate = LiveGate(audit_path=str(log))
    result = gate.evaluate(
        rules={"ceiling": {"can_auto_increase": False}},
        config={"api_key": "placeholder"},
    )
    check = next(c for c in result.checks if c.name == "no_broker_credentials")
    assert check.passed is False


def test_gate_render_never_authorizes_live_execution(tmp_path):
    log = tmp_path / "a.log"
    log.write_text(json.dumps({"event": "cycle_completed"}) + "\n")
    gate = LiveGate(audit_path=str(log))
    result = gate.evaluate(
        rules={"ceiling": {"can_auto_increase": False}},
        config={},
    )
    rendered = result.render()
    assert "live trading permitted" not in rendered.lower()
    assert "LIVE EXECUTION REMAINS DISABLED BY REPOSITORY POLICY" in rendered
