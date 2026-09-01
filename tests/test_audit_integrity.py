"""Audit receipts must form an externally anchored replay-verifiable chain."""
import asyncio
import json

from audit.logger import AuditLogger


async def test_hash_chain_verifies_and_detects_entry_tamper(tmp_path):
    path = tmp_path / "audit.log"
    audit = AuditLogger(str(path))

    await audit.log({"event": "cycle_completed", "cycle": 1})
    await audit.log({"event": "cycle_completed", "cycle": 2})
    anchor = audit.observed_terminal_hash()

    ok, reason = AuditLogger.verify_chain_file(path, anchor)
    assert ok is True, reason

    lines = path.read_text().splitlines()
    first = json.loads(lines[0])
    first["cycle"] = 999
    lines[0] = json.dumps(first, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")

    ok, reason = AuditLogger.verify_chain_file(path, anchor)
    assert ok is False
    assert "entry_hash mismatch" in reason


async def test_truncated_valid_prefix_cannot_match_trusted_terminal_anchor(tmp_path):
    path = tmp_path / "audit.log"
    audit = AuditLogger(str(path))
    await audit.log({"event": "cycle_completed", "cycle": 1})
    await audit.log({"event": "error", "id": "must-not-disappear"})
    trusted_head = audit.observed_terminal_hash()

    lines = path.read_text().splitlines()
    path.write_text(lines[0] + "\n")

    ok, reason = AuditLogger.verify_chain_file(path, trusted_head)
    assert ok is False
    assert "terminal hash does not match trusted external anchor" in reason


async def test_first_chained_entry_seals_but_does_not_trust_legacy_prefix(tmp_path):
    path = tmp_path / "audit.log"
    path.write_text(json.dumps({"event": "alert_received", "legacy": True}) + "\n")
    audit = AuditLogger(str(path))

    await audit.log({"event": "cycle_completed", "cycle": 1})
    anchor = audit.observed_terminal_hash()
    ok, reason, events, observed_head = AuditLogger.verify_snapshot_file(path, anchor)
    assert ok is True, reason
    assert observed_head == anchor
    assert [event["event"] for event in events] == ["cycle_completed"]
    assert all(event.get("legacy") is not True for event in events)

    lines = path.read_text().splitlines()
    legacy = json.loads(lines[0])
    legacy["legacy"] = "edited"
    lines[0] = json.dumps(legacy)
    path.write_text("\n".join(lines) + "\n")

    ok, reason = AuditLogger.verify_chain_file(path, anchor)
    assert ok is False
    assert "prev_hash mismatch" in reason


async def test_concurrent_writers_serialize_predecessor_selection_and_append(tmp_path):
    path = tmp_path / "audit.log"
    first = AuditLogger(str(path))
    second = AuditLogger(str(path))

    writes = []
    for index in range(20):
        logger = first if index % 2 == 0 else second
        writes.append(logger.log({"event": "cycle_completed", "cycle": index + 1}))
    await asyncio.gather(*writes)

    anchor = first.observed_terminal_hash()
    ok, reason, events, observed_head = AuditLogger.verify_snapshot_file(path, anchor)
    assert ok is True, reason
    assert observed_head == anchor
    assert len(events) == 20
    assert len({event["entry_hash"] for event in events}) == 20


def test_missing_external_anchor_is_not_integrity_proof(tmp_path):
    path = tmp_path / "audit.log"
    path.write_text(json.dumps({"event": "cycle_completed"}) + "\n")

    ok, reason = AuditLogger.verify_chain_file(path)
    assert ok is False
    assert "trusted terminal audit hash is required" in reason


def test_unchained_log_is_not_integrity_proof_even_with_candidate_anchor(tmp_path):
    path = tmp_path / "audit.log"
    path.write_text(json.dumps({"event": "cycle_completed"}) + "\n")

    ok, reason = AuditLogger.verify_chain_file(path, "f" * 64)
    assert ok is False
    assert "no hash-chained entries" in reason
