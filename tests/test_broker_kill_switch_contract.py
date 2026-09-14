import pytest

from audit.logger import AuditLogger
from broker.crypto_sandbox import CryptoSandboxBroker
from broker.mock import MOCK_ACCOUNT_ID, MockBroker
from gate.live_gate import LiveGate, run_kill_switch_drill

RECEIPT_KEY = "broker-contract-proof-key-32-bytes-minimum"


async def _prove_drill(tmp_path, broker, account_id: str, order_id: str, status: str):
    path = tmp_path / f"{order_id}.audit.log"
    audit = AuditLogger(str(path))
    start = await audit.start_trusted_chain({"event": "audit_ready"})

    assert await broker.connect() is True
    broker.orders[order_id] = {"status": status, "real_money": False}

    record = await run_kill_switch_drill(
        broker,
        audit,
        working_order_id=order_id,
        receipt_key=RECEIPT_KEY,
        expected_account=account_id,
        status_attempts=1,
        status_interval=0,
    )

    assert record["result"] == "passed"
    assert record["paper_proven"] is True
    assert record["target_account"] == account_id
    assert record["pre_cancel_status"] == status
    assert record["terminal_status"] == "Cancelled"
    assert len(record["broker_proof_hash"]) == 64
    assert len(record["receipt_auth"]) == 64

    terminal = await broker.get_order_status(order_id)
    assert terminal["status"] == "Cancelled"
    assert terminal["cancelled_at"] is not None

    head = audit.observed_terminal_hash()
    result = LiveGate(audit_path=str(path)).evaluate(
        broker=broker,
        rules={},
        config={
            "audit_start_hash": start,
            "audit_head_hash": head,
            "kill_switch_receipt_key": RECEIPT_KEY,
            "expected_account": account_id,
        },
    )
    account_check = next(c for c in result.checks if c.name == "target_account_proven")
    kill_switch_check = next(c for c in result.checks if c.name == "kill_switch_tested")
    assert account_check.passed is True
    assert kill_switch_check.passed is True


@pytest.mark.asyncio
async def test_mock_broker_satisfies_bound_kill_switch_drill_end_to_end(tmp_path):
    await _prove_drill(
        tmp_path,
        MockBroker(),
        MOCK_ACCOUNT_ID,
        "MOCK-PROBE",
        "Submitted",
    )


@pytest.mark.asyncio
async def test_crypto_sandbox_satisfies_bound_kill_switch_drill_end_to_end(tmp_path):
    broker = CryptoSandboxBroker(wallet_id="SANDBOX-KILL-SWITCH")
    await _prove_drill(
        tmp_path,
        broker,
        broker.wallet_id,
        "CRYPTO-PROBE",
        "ApiPending",
    )
