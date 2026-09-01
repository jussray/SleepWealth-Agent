"""Audit receipts must form an externally bounded replay-verifiable chain."""
import asyncio
import hashlib
import json

from audit.logger import AuditLogger, GENESIS_HASH


def _canonical(event: dict) -> bytes:
    payload = {k: v for k, v in event.items() if k != "entry_hash"}
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


async def test_hash_chain_verifies_and_detects_entry_tamper(tmp_path):
    path = tmp_path / "audit.log"
    audit = AuditLogger(str(path))

    start = await audit.start_trusted_chain({"event": "cycle_completed", "cycle": 1})
    await audit.log({"event": "cycle_completed", "cycle": 2})
    head = audit.observed_terminal_hash()

    ok, reason = AuditLogger.verify_chain_file(path, start, head)
    assert ok is True, reason

    lines = path.read_text().splitlines()
    first = json.loads(lines[0])
    first["cycle"] = 999
    lines[0] = json.dumps(first, sort_keys=True)
    path.write_text("\n".join(lines) + "\n")

    ok, reason = AuditLogger.verify_chain_file(path, start, head)
    assert ok is False
    assert "entry_hash mismatch" in reason


async def test_truncated_valid_prefix_cannot_match_trusted_terminal_anchor(tmp_path):
    path = tmp_path / "audit.log"
    audit = AuditLogger(str(path))
    start = await audit.start_trusted_chain({"event": "cycle_completed", "cycle": 1})
    await audit.log({"event": "error", "id": "must-not-disappear"})
    trusted_head = audit.observed_terminal_hash()

    lines = path.read_text().splitlines()
    path.write_text(lines[0] + "\n")

    ok, reason = AuditLogger.verify_chain_file(path, start, trusted_head)
    assert ok is False
    assert "terminal hash does not match trusted external anchor" in reason


async def test_explicit_start_seals_but_does_not_trust_legacy_prefix(tmp_path):
    path = tmp_path / "audit.log"
    path.write_text(json.dumps({"event": "alert_received", "legacy": True}) + "\n")
    audit = AuditLogger(str(path))

    start = await audit.start_trusted_chain({"event": "cycle_completed", "cycle": 1})
    head = audit.observed_terminal_hash()
    ok, reason, events, observed_head = AuditLogger.verify_snapshot_file(path, start, head)
    assert ok is True, reason
    assert observed_head == head
    assert [event["event"] for event in events] == ["cycle_completed"]
    assert all(event.get("legacy") is not True for event in events)

    lines = path.read_text().splitlines()
    legacy = json.loads(lines[0])
    legacy["legacy"] = "edited"
    lines[0] = json.dumps(legacy)
    path.write_text("\n".join(lines) + "\n")

    ok, reason = AuditLogger.verify_chain_file(path, start, head)
    assert ok is False
    assert "trusted audit start does not seal exact legacy prefix" in reason


async def test_chain_looking_legacy_record_stays_outside_trusted_start(tmp_path):
    path = tmp_path / "audit.log"
    forged_legacy = {
        "event": "alert_received",
        "legacy": True,
        "logged_at": "2026-01-01T00:00:00+00:00",
        "prev_hash": GENESIS_HASH,
    }
    forged_legacy["entry_hash"] = hashlib.sha256(_canonical(forged_legacy)).hexdigest()
    path.write_text(json.dumps(forged_legacy, sort_keys=True) + "\n")

    audit = AuditLogger(str(path))
    start = await audit.start_trusted_chain({"event": "cycle_completed", "cycle": 1})
    head = audit.observed_terminal_hash()

    ok, reason, events, _ = AuditLogger.verify_snapshot_file(path, start, head)
    assert ok is True, reason
    assert [event["event"] for event in events] == ["cycle_completed"]
    assert all(event.get("legacy") is not True for event in events)

    ok, reason = AuditLogger.verify_chain_file(path, forged_legacy["entry_hash"], head)
    assert ok is False
    assert "boundary marker" in reason


async def test_concurrent_writers_serialize_predecessor_selection_and_append(tmp_path):
    path = tmp_path / "audit.log"
    first = AuditLogger(str(path))
    second = AuditLogger(str(path))
    start = await first.start_trusted_chain({"event": "audit_ready"})

    writes = []
    for index in range(20):
        logger = first if index % 2 == 0 else second
        writes.append(logger.log({"event": "cycle_completed", "cycle": index + 1}))
    await asyncio.gather(*writes)

    head = first.observed_terminal_hash()
    ok, reason, events, observed_head = AuditLogger.verify_snapshot_file(path, start, head)
    assert ok is True, reason
    assert observed_head == head
    assert len(events) == 21
    assert len({event["entry_hash"] for event in events}) == 21


async def test_real_path_and_symlink_alias_share_one_inode_lock(tmp_path):
    path = tmp_path / "audit.log"
    alias = tmp_path / "alias.log"
    primary = AuditLogger(str(path))
    start = await primary.start_trusted_chain({"event": "audit_ready"})
    alias.symlink_to(path)
    via_alias = AuditLogger(str(alias))

    writes = []
    for index in range(20):
        logger = primary if index % 2 == 0 else via_alias
        writes.append(logger.log({"event": "cycle_completed", "cycle": index + 1}))
    await asyncio.gather(*writes)

    head = primary.observed_terminal_hash()
    ok, reason, events, _ = AuditLogger.verify_snapshot_file(path, start, head)
    assert ok is True, reason
    assert len(events) == 21


async def test_missing_external_start_anchor_is_not_integrity_proof(tmp_path):
    path = tmp_path / "audit.log"
    audit = AuditLogger(str(path))
    await audit.start_trusted_chain({"event": "cycle_completed"})
    head = audit.observed_terminal_hash()

    ok, reason = AuditLogger.verify_chain_file(path, None, head)
    assert ok is False
    assert "trusted audit start hash is required" in reason


def test_unchained_log_is_not_integrity_proof_even_with_candidate_anchors(tmp_path):
    path = tmp_path / "audit.log"
    path.write_text(json.dumps({"event": "cycle_completed"}) + "\n")

    ok, reason = AuditLogger.verify_chain_file(path, "e" * 64, "f" * 64)
    assert ok is False
    assert "trusted audit start hash is not present" in reason
