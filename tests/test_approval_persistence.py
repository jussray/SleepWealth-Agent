import json

import pytest

from approvals.queue import ApprovalQueue, ApprovalStatus
from broker.base import Order


def evaluation():
    return {
        "allowed": True,
        "reason": "OK",
        "ceiling": 1000.0,
        "max_position_size": 1000.0,
        "floor_cash": 5.0,
        "rules_version": "test-v1",
    }


def test_pending_state_and_counter_survive_restart(tmp_path):
    state = tmp_path / "approvals.json"
    first = ApprovalQueue(str(state), session_id="session-a")
    assert first.add(Order("AAPL", 1, "buy"), evaluation()) == "PROP-1"

    second = ApprovalQueue(str(state), session_id="session-b")
    restored = second.get("PROP-1")
    assert restored is not None
    assert restored.status is ApprovalStatus.PENDING
    assert second.add(Order("AAPL", 2, "buy"), evaluation()) == "PROP-2"


def test_approved_request_becomes_stale_after_restart(tmp_path):
    state = tmp_path / "approvals.json"
    first = ApprovalQueue(str(state), session_id="session-a")
    proposal_id = first.add(Order("AAPL", 1, "buy"), evaluation())
    assert first.approve(proposal_id, "paper approval")

    restarted = ApprovalQueue(str(state), session_id="session-b")
    restored = restarted.get(proposal_id)
    assert restored is not None
    assert restored.status is ApprovalStatus.STALE
    assert "restart" in (restored.reason or "")
    assert restored.approved_fingerprint is None
    assert restarted.begin_execution(proposal_id) is False


def test_inflight_execution_requires_reconciliation_after_restart(tmp_path):
    state = tmp_path / "approvals.json"
    first = ApprovalQueue(str(state), session_id="session-a")
    proposal_id = first.add(Order("AAPL", 1, "buy"), evaluation())
    assert first.approve(proposal_id)
    assert first.begin_execution(proposal_id)

    restarted = ApprovalQueue(str(state), session_id="session-b")
    restored = restarted.get(proposal_id)
    assert restored is not None
    assert restored.status is ApprovalStatus.RECONCILE_REQUIRED
    assert "reconciliation required" in (restored.reason or "")
    assert restarted.begin_execution(proposal_id) is False


def test_executed_request_survives_restart_without_replay(tmp_path):
    state = tmp_path / "approvals.json"
    first = ApprovalQueue(str(state), session_id="session-a")
    proposal_id = first.add(Order("AAPL", 1, "buy"), evaluation())
    assert first.approve(proposal_id)
    assert first.begin_execution(proposal_id)
    assert first.mark_executed(proposal_id, "MOCK-1")

    restarted = ApprovalQueue(str(state), session_id="session-b")
    restored = restarted.get(proposal_id)
    assert restored is not None
    assert restored.status is ApprovalStatus.EXECUTED
    assert restored.order_id == "MOCK-1"
    assert restarted.begin_execution(proposal_id) is False


def test_multiple_queue_instances_do_not_reuse_proposal_ids(tmp_path):
    state = tmp_path / "approvals.json"
    first = ApprovalQueue(str(state), session_id="session-a")
    second = ApprovalQueue(str(state), session_id="session-b")

    assert first.add(Order("AAPL", 1, "buy"), evaluation()) == "PROP-1"
    assert second.add(Order("AAPL", 1, "buy"), evaluation()) == "PROP-2"


def test_corrupt_persistent_state_fails_closed(tmp_path):
    state = tmp_path / "approvals.json"
    state.write_text("{not-json", encoding="utf-8")

    with pytest.raises(RuntimeError, match="approval state is unreadable"):
        ApprovalQueue(str(state), session_id="session-a")


def test_persistent_state_is_explicit_json_contract(tmp_path):
    state = tmp_path / "approvals.json"
    queue = ApprovalQueue(str(state), session_id="session-a")
    queue.add(Order("AAPL", 1, "buy"), evaluation())

    payload = json.loads(state.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["counter"] == 1
    assert payload["requests"][0]["proposal_id"] == "PROP-1"
