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
TRUSTED_START_MARKER = "trusted-start-v1"


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


def _json_object(raw_line: bytes) -> dict | None:
    """Decode one JSON object without requiring legacy bytes to be valid text."""
    try:
        value = json.loads(raw_line)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


class AuditLogger:
    """Append-only, hash-chained JSONL evidence trail.

    Existing bytes are never promoted into trusted evidence merely because they
    happen to contain chain-looking fields. A migration/new-chain operator must
    append one explicit trusted-start entry and persist that entry hash plus the
    current terminal hash in a separately trusted control plane.
    """

    def __init__(self, log_path: str = "audit.log"):
        self.log_path = Path(log_path)
        if self.log_path.parent != Path("."):
            self.log_path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked_audit_file(self):
        """Lock the audit inode itself, so path aliases share one lock identity."""
        if fcntl is None:
            raise RuntimeError("cross-process audit locking is unavailable on this platform")
        with open(self.log_path, "a+b") as audit_file:
            fcntl.flock(audit_file.fileno(), fcntl.LOCK_EX)
            try:
                yield audit_file
            finally:
                fcntl.flock(audit_file.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def _previous_hash_from_raw(raw: bytes) -> str:
        if not raw:
            return GENESIS_HASH

        lines = [line for line in raw.splitlines() if line.strip()]
        if lines:
            last = _json_object(lines[-1]) or {}
            entry_hash = last.get("entry_hash")
            if _is_hash(entry_hash):
                return str(entry_hash).lower()

        # A normal append over an unchained file remains untrusted until an
        # explicit trusted-start boundary is created and externally anchored.
        return hashlib.sha256(raw).hexdigest()

    @staticmethod
    def _tail_entry_hash(fh) -> str | None:
        """Read only the final nonblank JSONL record during steady-state appends."""
        fh.seek(0, os.SEEK_END)
        position = fh.tell()
        if position == 0:
            return GENESIS_HASH

        buffer = b""
        while position > 0:
            read_size = min(8192, position)
            position -= read_size
            fh.seek(position)
            buffer = fh.read(read_size) + buffer
            trimmed = buffer.rstrip()
            if not trimmed:
                continue

            newline = max(trimmed.rfind(b"\n"), trimmed.rfind(b"\r"))
            if newline >= 0 or position == 0:
                raw_line = trimmed[newline + 1 :]
                last = _json_object(raw_line) or {}
                entry_hash = last.get("entry_hash")
                return str(entry_hash).lower() if _is_hash(entry_hash) else None

        return None

    def _append_sync(self, event: dict, trusted_start: bool = False) -> str:
        with self._locked_audit_file() as fh:
            separator_added = False
            if trusted_start:
                fh.seek(0)
                raw = fh.read()
                prev_hash = hashlib.sha256(raw).hexdigest() if raw else GENESIS_HASH
                separator_added = bool(raw and not raw.endswith((b"\n", b"\r")))
            else:
                prev_hash = self._tail_entry_hash(fh)
                if prev_hash is None:
                    # Legacy/untrusted fallback only. Normal chained appends read
                    # the tail instead of rereading the complete audit history.
                    fh.seek(0)
                    raw = fh.read()
                    prev_hash = self._previous_hash_from_raw(raw)

            record = {
                **event,
                "logged_at": datetime.now(timezone.utc).isoformat(),
                "prev_hash": prev_hash,
            }
            if trusted_start:
                record["chain_boundary"] = TRUSTED_START_MARKER
                record["legacy_separator_added"] = separator_added
            record["entry_hash"] = hashlib.sha256(_canonical_event(record)).hexdigest()
            encoded = (json.dumps(record, default=str, sort_keys=True) + "\n").encode("utf-8")

            fh.seek(0, os.SEEK_END)
            if separator_added:
                fh.write(b"\n")
            fh.write(encoded)
            fh.flush()
            os.fsync(fh.fileno())
            return record["entry_hash"]

    async def log(self, event: dict) -> str:
        """Append a normal chained event and return its observed entry hash."""
        return await asyncio.to_thread(self._append_sync, event, False)

    async def start_trusted_chain(self, event: dict) -> str:
        """Append the explicit trust boundary and return its hash for external anchoring.

        The returned value is only an observation until a caller persists it in
        an independent trusted control plane. This method deliberately seals all
        prior bytes as legacy, even if those bytes contain valid-looking hashes.
        """
        return await asyncio.to_thread(self._append_sync, event, True)

    async def read(self, limit: int = 100) -> list[dict]:
        """Unverified diagnostic read. Never use this method for gate evidence."""
        if not self.log_path.exists():
            return []
        events = []
        with open(self.log_path, encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    value = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(value, dict):
                    events.append(value)
        return events[-limit:]

    def observed_terminal_hash(self) -> str:
        """Return the current terminal hash for external anchoring.

        This observation is not itself a trust anchor. A caller must persist the
        value in a separately trusted control plane before using it later to
        verify a gate snapshot.
        """
        if not self.log_path.exists() or self.log_path.stat().st_size == 0:
            return ""
        with open(self.log_path, "rb") as fh:
            entry_hash = self._tail_entry_hash(fh)
        return entry_hash or ""

    @classmethod
    def verify_snapshot_file(
        cls,
        log_path: str | Path,
        expected_start_hash: str | None,
        expected_head_hash: str | None,
    ) -> tuple[bool, str, list[dict], str]:
        """Verify one immutable snapshot between externally trusted start/head hashes.

        All bytes before the trusted-start entry are opaque legacy bytes. They do
        not become evidence even if they contain syntactically valid chain fields.
        The trusted-start entry must seal the SHA-256 of that exact legacy prefix.
        """
        path = Path(log_path)
        if not path.exists() or path.stat().st_size == 0:
            return False, "audit log is empty; no integrity chain exists", [], ""
        if not _is_hash(expected_start_hash):
            return False, "trusted audit start hash is required", [], ""
        if not _is_hash(expected_head_hash):
            return False, "trusted terminal audit hash is required", [], ""

        # One read only. Integrity and every returned event derive from these bytes.
        raw = path.read_bytes()
        raw_lines = raw.splitlines(keepends=True)
        start_index: int | None = None
        start_event: dict | None = None

        # Locate the independently anchored boundary first. Everything before it
        # is opaque legacy, including invalid UTF-8, JSON scalars, arrays, and
        # forged chain-looking objects.
        for zero_index, raw_line in enumerate(raw_lines):
            if not raw_line.strip():
                continue
            candidate = _json_object(raw_line)
            if not candidate:
                continue
            if str(candidate.get("entry_hash", "")).lower() == str(expected_start_hash).lower():
                start_index = zero_index
                start_event = candidate
                break

        if start_index is None or start_event is None:
            return False, "trusted audit start hash is not present in snapshot", [], ""
        if start_event.get("chain_boundary") != TRUSTED_START_MARKER:
            return False, "trusted audit start entry lacks required boundary marker", [], ""

        legacy_prefix = b"".join(raw_lines[:start_index])
        separator_added = start_event.get("legacy_separator_added") is True
        if separator_added:
            if not legacy_prefix.endswith(b"\n"):
                return False, "trusted audit separator marker does not match snapshot", [], ""
            sealed_legacy_prefix = legacy_prefix[:-1]
        else:
            sealed_legacy_prefix = legacy_prefix

        expected_prev = (
            hashlib.sha256(sealed_legacy_prefix).hexdigest()
            if sealed_legacy_prefix
            else GENESIS_HASH
        )
        if str(start_event.get("prev_hash", "")).lower() != expected_prev:
            return False, "trusted audit start does not seal exact legacy prefix", [], ""

        previous_entry_hash: str | None = None
        chained_events: list[dict] = []
        for zero_index in range(start_index, len(raw_lines)):
            raw_line = raw_lines[zero_index]
            line_number = zero_index + 1
            if not raw_line.strip():
                continue
            event = _json_object(raw_line)
            if event is None:
                return False, f"audit line {line_number} is not a JSON object", [], ""

            prev_hash = event.get("prev_hash")
            entry_hash = event.get("entry_hash")
            if not (_is_hash(prev_hash) and _is_hash(entry_hash)):
                return False, f"audit line {line_number} is unchained after trusted start", [], ""

            expected_prev = (
                hashlib.sha256(sealed_legacy_prefix).hexdigest()
                if previous_entry_hash is None and sealed_legacy_prefix
                else (GENESIS_HASH if previous_entry_hash is None else previous_entry_hash)
            )
            if str(prev_hash).lower() != expected_prev:
                return False, f"audit line {line_number} prev_hash mismatch", [], ""

            expected_entry = hashlib.sha256(_canonical_event(event)).hexdigest()
            if str(entry_hash).lower() != expected_entry:
                return False, f"audit line {line_number} entry_hash mismatch", [], ""

            previous_entry_hash = expected_entry
            chained_events.append(event)

        if not chained_events or previous_entry_hash is None:
            return False, "audit snapshot has no trusted chained entries", [], ""
        if chained_events[0].get("chain_boundary") != TRUSTED_START_MARKER:
            return False, "first trusted event is not the anchored boundary", [], ""
        if str(chained_events[0].get("entry_hash", "")).lower() != str(expected_start_hash).lower():
            return False, "trusted start identity mismatch", [], ""
        if previous_entry_hash != str(expected_head_hash).lower():
            return (
                False,
                "audit terminal hash does not match trusted external anchor",
                [],
                previous_entry_hash,
            )
        return (
            True,
            f"anchored hash chain valid across {len(chained_events)} trusted entrie(s)",
            chained_events,
            previous_entry_hash,
        )

    @classmethod
    def verify_chain_file(
        cls,
        log_path: str | Path,
        expected_start_hash: str | None = None,
        expected_head_hash: str | None = None,
    ) -> tuple[bool, str]:
        ok, reason, _events, _head = cls.verify_snapshot_file(
            log_path,
            expected_start_hash,
            expected_head_hash,
        )
        return ok, reason