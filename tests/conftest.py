import pytest


@pytest.fixture(autouse=True)
def isolate_runtime_approval_state(monkeypatch, tmp_path):
    """Keep the runtime-default approval ledger durable but isolated per test."""
    monkeypatch.setenv(
        "SLEEPWEALTH_APPROVAL_STATE",
        str(tmp_path / "paper-approvals.json"),
    )
    monkeypatch.setenv("SLEEPWEALTH_APPROVAL_STATE_SCOPE", "pytest-isolated")
