import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path


GENESIS_HASH = "0" * 64


def _canonical_event(event: dict) -> bytes:
    """Stable bytes for an audit event, excluding its self-hash."""
    payload = {k: v for k, v in event.items() if k != "entry_hash"}
    return json.dumps(
        payload,
        default=str,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


class AuditLogger:
    """Append-only, hash-chained JSONL evidence trail.

    Existing unchained logs are not rewritten. The first chained entry seals the
    exact legacy prefix with SHA-256; every later entry points at the previous
    entry hash. Editing, deleting, reordering, or inserting records breaks replay.
    """

    def __init__(self, log_path: str = "audit.log"):
        self.log_path = Path(log_path)
        if self.log_path.parent != Path("."):
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _previous_hash(self) -> str:
        if not self.log_path.exists() or self.log_path.stat().st_size == 0:
            return GENESIS_HASH

        raw = self.log_path.read_bytes()
        lines = [line for line in raw.splitlines() if line.strip()]
        if lines:
            try:
                last = json.loads(lines[-1])
            except json.JSONDecodeError:
                last = {}
            entry_hash = last.get("entry_hash")
            if isinstance(entry_hash, str) and len(entry_hash) == 64:
                return entry_hash

        # Seal the exact legacy bytes without mutating the historical log.
        return hashlib.sha256(raw).hexdigest()

    async def log(self, event: dict) -> None:
        record = {
            **event,
            "logged_at": datetime.now(timezone.utc).isoformat(),
            "prev_hash": self._previous_hash(),
        }
        record["entry_hash"] = hashlib.sha256(_canonical_event(record)).hexdigest()
        with open(self.log_path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, default=str, sort_keys=True) + "\n")

    async def read(self, limit: int = 100) -> list[dict]:
        if not self.log_path.exists():
            return []
        events = []
        with open(self.log_path, encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events[-limit:]

    @classmethod
    def verify_chain_file(cls, log_path: str | Path) -> tuple[bool, str]:
        """Replay and verify the chain without trusting a mutable counter."""
        path = Path(log_path)
        if not path.exists() or path.stat().st_size == 0:
            return False, "audit log is empty; no integrity chain exists"

        raw_lines = path.read_bytes().splitlines(keepends=True)
        legacy_prefix = b""
        previous_entry_hash: str | None = None
        chain_started = False
        chained_entries = 0

        for index, raw_line in enumerate(raw_lines, start=1):
            if not raw_line.strip():
                if not chain_started:
                    legacy_prefix += raw_line
                continue

            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                return False, f"audit line {index} is not valid JSON"

            prev_hash = event.get("prev_hash")
            entry_hash = event.get("entry_hash")
            has_chain_fields = isinstance(prev_hash, str) and isinstance(entry_hash, str)

            if not has_chain_fields:
                if chain_started:
                    return False, f"audit line {index} is unchained after chain start"
                legacy_prefix += raw_line
                continue

            expected_prev = (
                previous_entry_hash
                if chain_started
                else (hashlib.sha256(legacy_prefix).hexdigest() if legacy_prefix else GENESIS_HASH)
            )
            if prev_hash != expected_prev:
                return False, f"audit line {index} prev_hash mismatch"

            expected_entry = hashlib.sha256(_canonical_event(event)).hexdigest()
            if entry_hash != expected_entry:
                return False, f"audit line {index} entry_hash mismatch"

            chain_started = True
            chained_entries += 1
            previous_entry_hash = entry_hash

        if not chain_started:
            return False, "audit log has no hash-chained entries"
        return True, f"hash chain valid across {chained_entries} chained entrie(s)"
