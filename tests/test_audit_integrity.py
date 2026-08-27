"""Audit receipts must form a replay-verifiable hash chain."""
import json

from audit.logger import AuditLogger


async def test_hash_chain_verifies_and_detects_entry_tamper(tmp_path):
    path = tmp_path / "audit.log"
    audit = AuditLogger(str(path))

    await audit.log({"event": "cycle_completed", "cycle": 1})
    await audit.log({"event": "cycle_completed", "cycle": 2})

    ok, reason = AuditLogger.verify_chain_file(path)
    assert ok is True, reason

    lines = path.read_text().splitlines()
    first = json.loads(lines[0])
    first["cycle"] = 999
    lines[0] = json.dumps(first, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")

    ok, reason = AuditLogger.verify_chain_file(path)
    assert ok is False
    assert "entry_hash mismatch" in reason


async def test_first_chained_entry_seals_legacy_prefix(tmp_path):
    path = tmp_path / "audit.log"
    path.write_text(json.dumps({"event": "legacy", "value": 1}) + "\n")
    audit = AuditLogger(str(path))

    await audit.log({"event": "cycle_completed", "cycle": 1})
    ok, reason = AuditLogger.verify_chain_file(path)
    assert ok is True, reason

    lines = path.read_text().splitlines()
    legacy = json.loads(lines[0])
    legacy["value"] = 2
    lines[0] = json.dumps(legacy)
    path.write_text("\n".join(lines) + "\n")

    ok, reason = AuditLogger.verify_chain_file(path)
    assert ok is False
    assert "prev_hash mismatch" in reason


def test_unchained_log_is_not_integrity_proof(tmp_path):
    path = tmp_path / "audit.log"
    path.write_text(json.dumps({"event": "cycle_completed"}) + "\n")

    ok, reason = AuditLogger.verify_chain_file(path)
    assert ok is False
    assert "no hash-chained entries" in reason
