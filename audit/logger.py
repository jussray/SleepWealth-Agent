import asyncio
import hashlib
import json
import os
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX environments fail closed below
    fcntl = None


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


def _is_hash(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


class AuditLogger:
    """Append-only, hash-chained JSONL evidence trail.

    Existing unchained logs are not rewritten. They may be sealed as historical
    bytes by the first chained entry, but they never become trusted gate evidence.
    Gate evidence requires one immutable snapshot whose terminal entry hash
    matches a separately supplied external anchor.
    """

    def __init__(self, log_path: str = "audit.log"):
        self.log_path = Path(log_path)
        self.lock_path = self.log_path.with_name(f"{self.log_path.name}.lock")
        if self.log_path.parent != Path("."):
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _exclusive_append_lock(self):
        """Serialize predecessor selection plus append across processes.

        The supported production/runtime path is POSIX. On environments without
        an OS-level flock primitive, fail closed instead of pretending a
        process-local lock protects a cross-process evidence chain.
        """
        if fcntl is None:
            raise RuntimeError("cross-process audit locking is unavailable on this platform")
        with open(self.lock_path, "a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _previous_hash_from_raw(raw: bytes) -> str:
        if not raw:
            return GENESIS_HASH

        lines = [line for line in raw.splitlines() if line.strip()]
        if lines:
            try:
                last = json.loads(lines[-1])
            except json.JSONDecodeError:
                last = {}
            entry_hash = last.get("entry_hash")
            if _is_hash(entry_hash):
                return str(entry_hash).lower()

        # Seal the exact legacy bytes without promoting them into trusted events.
        return hashlib.sha256(raw).hexdigest()

    def _append_sync(self, event: dict) -> None:
        with self._exclusive_append_lock():
            raw = self.log_path.read_bytes() if self.log_path.exists() else b""
            record = {
                **event,
                "logged_at": datetime.now(timezone.utc).isoformat(),
                "prev_hash": self._previous_hash_from_raw(raw),
            }
            record["entry_hash"] = hashlib.sha256(_canonical_event(record)).hexdigest()
            encoded = (json.dumps(record, default=str, sort_keys=True) + "\n").encode("utf-8")
            with open(self.log_path, "ab") as fh:
                fh.write(encoded)
                fh.flush()
                os.fsync(fh.fileno())

    async def log(self, event: dict) -> None:
        # Thread off the blocking OS file lock so concurrent async callers can
        # contend safely without blocking the event loop.
        await asyncio.to_thread(self._append_sync, event)

    async def read(self, limit: int = 100) -> list[dict]:
        """Unverified diagnostic read. Never use this method for gate evidence."""
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

    def observed_terminal_hash(self) -> str:
        """Return the current terminal hash for external anchoring.

        This observation is not itself a trust anchor. A caller must persist the
        value in a separately trusted control plane before using it later to
        verify a gate snapshot.
        """
        if not self.log_path.exists() or self.log_path.stat().st_size == 0:
            return ""
        raw = self.log_path.read_bytes()
        lines = [line for line in raw.splitlines() if line.strip()]
        if not lines:
            return ""
        try:
            last = json.loads(lines[-1])
        except json.JSONDecodeError:
            return ""
        entry_hash = last.get("entry_hash")
        return str(entry_hash).lower() if _is_hash(entry_hash) else ""

    @classmethod
    def verify_snapshot_file(
        cls,
        log_path: str | Path,
        expected_head_hash: str | None,
    ) -> tuple[bool, str, list[dict], str]:
        """Verify one immutable file snapshot against an external terminal hash.

        Returns only hash-chained events. Any unchained legacy prefix may be
        cryptographically sealed as predecessor bytes, but it is intentionally
        excluded from the trusted event list.
        """
        path = Path(log_path)
        if not path.exists() or path.stat().st_size == 0:
            return False, "audit log is empty; no integrity chain exists", [], ""
        if not _is_hash(expected_head_hash):
            return False, "trusted terminal audit hash is required", [], ""

        # One read only. Integrity and all returned evidence are derived from
        # these exact bytes, preventing verification/evaluation TOCTOU drift.
        raw = path.read_bytes()
        raw_lines = raw.splitlines(keepends=True)
        legacy_prefix = b""
        previous_entry_hash: str | None = None
        chain_started = False
        chained_events: list[dict] = []

        for index, raw_line in enumerate(raw_lines, start=1):
            if not raw_line.strip():
                if not chain_started:
                    legacy_prefix += raw_line
                continue

            try:
                event = json.loads(raw_line)
            except json.JSONDecodeError:
                return False, f"audit line {index} is not valid JSON", [], ""

            prev_hash = event.get("prev_hash")
            entry_hash = event.get("entry_hash")
            has_chain_fields = _is_hash(prev_hash) and _is_hash(entry_hash)

            if not has_chain_fields:
                if chain_started:
                    return False, f"audit line {index} is unchained after chain start", [], ""
                legacy_prefix += raw_line
                continue

            expected_prev = (
                previous_entry_hash
                if chain_started
                else (hashlib.sha256(legacy_prefix).hexdigest() if legacy_prefix else GENESIS_HASH)
            )
            if str(prev_hash).lower() != expected_prev:
                return False, f"audit line {index} prev_hash mismatch", [], ""

            expected_entry = hashlib.sha256(_canonical_event(event)).hexdigest()
            if str(entry_hash).lower() != expected_entry:
                return False, f"audit line {index} entry_hash mismatch", [], ""

            chain_started = True
            previous_entry_hash = expected_entry
            chained_events.append(event)

        if not chain_started or previous_entry_hash is None:
            return False, "audit log has no hash-chained entries", [], ""
        if previous_entry_hash != str(expected_head_hash).lower():
            return (
                False,
                "audit terminal hash does not match trusted external anchor",
                [],
                previous_entry_hash,
            )
        return (
            True,
            f"anchored hash chain valid across {len(chained_events)} chained entrie(s)",
            chained_events,
            previous_entry_hash,
        )

    @classmethod
    def verify_chain_file(
        cls,
        log_path: str | Path,
        expected_head_hash: str | None = None,
    ) -> tuple[bool, str]:
        ok, reason, _events, _head = cls.verify_snapshot_file(log_path, expected_head_hash)
        return ok, reason
