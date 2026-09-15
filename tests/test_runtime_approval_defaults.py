import os
import subprocess
import sys

import pytest

from approvals.queue import ApprovalQueue, ApprovalStatus, runtime_approval_state_path
from broker.base import Order


def _evaluation():
    return {
        "allowed": True,
        "reason": "paper test",
        "evaluated_price": 100.0,
        "ceiling": 200.0,
        "rules_version": "test",
    }


def test_omitted_state_path_uses_runtime_file_and_one_process_session(monkeypatch, tmp_path):
    state_path = tmp_path / "runtime" / "paper-approvals.json"
    monkeypatch.setenv("SLEEPWEALTH_APPROVAL_STATE", str(state_path))

    first = ApprovalQueue()
    proposal_id = first.add(Order("AAPL", 0.01, "buy"), _evaluation())
    assert first.approve(proposal_id, "paper approval")

    second = ApprovalQueue()

    assert runtime_approval_state_path() == str(state_path)
    assert first.state_path == state_path
    assert second.state_path == state_path
    assert first.session_id == second.session_id
    assert second.get(proposal_id).status is ApprovalStatus.APPROVED
    assert second.begin_execution(proposal_id)
    assert second.mark_executed(proposal_id, "MOCK-1")

    third = ApprovalQueue()
    assert third.get(proposal_id).status is ApprovalStatus.EXECUTED
    assert third.get(proposal_id).order_id == "MOCK-1"


def test_new_process_session_invalidates_unfinished_approval(tmp_path):
    state_path = tmp_path / "paper-approvals.json"
    first = ApprovalQueue(state_path=str(state_path), session_id="process-a")
    proposal_id = first.add(Order("MSFT", 0.01, "buy"), _evaluation())
    assert first.approve(proposal_id, "paper approval")

    restarted = ApprovalQueue(state_path=str(state_path), session_id="process-b")
    request = restarted.get(proposal_id)

    assert request.status is ApprovalStatus.STALE
    assert request.approved_fingerprint is None
    assert "restart" in request.reason


def test_new_process_session_requires_reconciliation_for_inflight_execution(tmp_path):
    state_path = tmp_path / "paper-approvals.json"
    first = ApprovalQueue(state_path=str(state_path), session_id="process-a")
    proposal_id = first.add(Order("AAPL", 0.01, "buy"), _evaluation())
    assert first.approve(proposal_id, "paper approval")
    assert first.begin_execution(proposal_id)

    restarted = ApprovalQueue(state_path=str(state_path), session_id="process-b")
    request = restarted.get(proposal_id)

    assert request.status is ApprovalStatus.RECONCILE_REQUIRED
    assert "reconciliation required" in request.reason


def _run_python(script: str, state_path) -> str:
    env = os.environ.copy()
    env["SLEEPWEALTH_APPROVAL_STATE"] = str(state_path)
    completed = subprocess.run(
        [sys.executable, "-c", script],
        check=True,
        capture_output=True,
        text=True,
        env=env,
    )
    return completed.stdout.strip()


def test_runtime_default_recovers_across_real_process_boundaries(tmp_path):
    state_path = tmp_path / "paper-approvals.json"
    evaluation = repr(_evaluation())

    approved_id = _run_python(
        f"""
from approvals.queue import ApprovalQueue
from broker.base import Order
q = ApprovalQueue()
pid = q.add(Order('AAPL', 0.01, 'buy'), {evaluation})
assert q.approve(pid, 'paper approval')
print(pid)
""",
        state_path,
    )
    assert approved_id == "PROP-1"

    stale_status = _run_python(
        f"""
from approvals.queue import ApprovalQueue
q = ApprovalQueue()
print(q.get({approved_id!r}).status.value)
""",
        state_path,
    )
    assert stale_status == ApprovalStatus.STALE.value

    executing_id = _run_python(
        f"""
from approvals.queue import ApprovalQueue
from broker.base import Order
q = ApprovalQueue()
pid = q.add(Order('MSFT', 0.01, 'buy'), {evaluation})
assert q.approve(pid, 'paper approval')
assert q.begin_execution(pid)
print(pid)
""",
        state_path,
    )
    assert executing_id == "PROP-2"

    reconcile_status = _run_python(
        f"""
from approvals.queue import ApprovalQueue
q = ApprovalQueue()
print(q.get({executing_id!r}).status.value)
""",
        state_path,
    )
    assert reconcile_status == ApprovalStatus.RECONCILE_REQUIRED.value


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires POSIX fork semantics")
def test_prefork_child_gets_distinct_runtime_session(monkeypatch, tmp_path):
    state_path = tmp_path / "paper-approvals.json"
    monkeypatch.setenv("SLEEPWEALTH_APPROVAL_STATE", str(state_path))

    parent = ApprovalQueue()
    proposal_id = parent.add(Order("AAPL", 0.01, "buy"), _evaluation())
    assert parent.approve(proposal_id, "paper approval")

    read_fd, write_fd = os.pipe()
    child_pid = os.fork()
    if child_pid == 0:  # pragma: no cover - assertions happen in the parent
        try:
            os.close(read_fd)
            child = ApprovalQueue()
            request = child.get(proposal_id)
            payload = f"{child.session_id}\n{request.status.value}".encode("utf-8")
            os.write(write_fd, payload)
            os.close(write_fd)
            os._exit(0)
        except BaseException:
            os._exit(1)

    os.close(write_fd)
    payload = os.read(read_fd, 4096).decode("utf-8")
    os.close(read_fd)
    _, status = os.waitpid(child_pid, 0)

    assert os.waitstatus_to_exitcode(status) == 0
    child_session, child_status = payload.splitlines()
    assert child_session != parent.session_id
    assert child_status == ApprovalStatus.STALE.value


def test_explicit_none_preserves_intentional_memory_only_mode(monkeypatch, tmp_path):
    default_path = tmp_path / "must-not-exist.json"
    monkeypatch.setenv("SLEEPWEALTH_APPROVAL_STATE", str(default_path))

    queue = ApprovalQueue(state_path=None)
    proposal_id = queue.add(Order("AAPL", 0.01, "buy"), _evaluation())

    assert queue.state_path is None
    assert queue.get(proposal_id).status is ApprovalStatus.PENDING
    assert not default_path.exists()


def test_corrupt_runtime_default_fails_closed(monkeypatch, tmp_path):
    state_path = tmp_path / "paper-approvals.json"
    state_path.write_text("not-json", encoding="utf-8")
    monkeypatch.setenv("SLEEPWEALTH_APPROVAL_STATE", str(state_path))

    try:
        ApprovalQueue()
    except RuntimeError as exc:
        assert "approval state is unreadable" in str(exc)
    else:
        raise AssertionError("corrupt runtime approval state must fail closed")
