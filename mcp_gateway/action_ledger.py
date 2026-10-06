from __future__ import annotations

import hashlib
import hmac
import json
import os
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

MIN_LEDGER_KEY_BYTES = 32
STATE_VERSION = 1


def _key(value: object) -> bytes:
    if isinstance(value, bytes):
        result = value
    elif isinstance(value, str):
        result = value.encode("utf-8")
    else:
        return b""
    return result if len(result) >= MIN_LEDGER_KEY_BYTES else b""


def _canonical(payload: Mapping[str, object]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


class ProductActionLedger:
    """HMAC-sealed kill/revocation/idempotency ledger for MCP provider actions."""

    def __init__(self, state_path: str | Path, state_key: str | bytes) -> None:
        self.path = Path(state_path)
        self.key = _key(state_key)
        if not self.key:
            raise ValueError("product action ledger requires a 32+ byte state key")
        if fcntl is None:
            raise RuntimeError("persistent product action state requires POSIX file locking")
        if self.path.parent != Path("."):
            self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _locked(self):
        lock_path = self.path.with_name(self.path.name + ".lock")
        with open(lock_path, "a+b") as lock_file:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _empty(self) -> dict[str, object]:
        return {
            "version": STATE_VERSION,
            "kill_switch": False,
            "revoked_authority_receipts": [],
            "idempotency": {},
        }

    def _seal(self, payload: Mapping[str, object]) -> str:
        return hmac.new(self.key, _canonical(payload), hashlib.sha256).hexdigest()

    def _read_locked(self) -> dict[str, object]:
        if not self.path.exists():
            return self._empty()
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"product action ledger is unreadable: {exc}") from exc
        if not isinstance(stored, dict):
            raise RuntimeError("product action ledger shape is invalid")
        supplied = stored.get("seal")
        payload = {key: value for key, value in stored.items() if key != "seal"}
        if not isinstance(supplied, str) or len(supplied) != 64:
            raise RuntimeError("product action ledger authentication seal is missing")
        expected = self._seal(payload)
        if not hmac.compare_digest(supplied.lower(), expected.lower()):
            raise RuntimeError("product action ledger authentication failed")
        if payload.get("version") != STATE_VERSION:
            raise RuntimeError("product action ledger version is unsupported")
        if not isinstance(payload.get("kill_switch"), bool):
            raise RuntimeError("product action kill switch state is invalid")
        if not isinstance(payload.get("revoked_authority_receipts"), list):
            raise RuntimeError("product action revocation state is invalid")
        if not isinstance(payload.get("idempotency"), dict):
            raise RuntimeError("product action idempotency state is invalid")
        return payload

    def _write_locked(self, payload: Mapping[str, object]) -> None:
        stored = {**payload, "seal": self._seal(payload)}
        encoded = (json.dumps(stored, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")
        temp = self.path.with_name(f".{self.path.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
        try:
            with open(temp, "wb") as fh:
                fh.write(encoded)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(temp, self.path)
        finally:
            if temp.exists():
                temp.unlink()

    def set_kill_switch(self, engaged: bool) -> None:
        with self._locked():
            payload = self._read_locked()
            payload["kill_switch"] = bool(engaged)
            self._write_locked(payload)

    def revoke(self, receipt_id: str) -> None:
        receipt_id = str(receipt_id or "").strip()
        if not receipt_id:
            raise ValueError("receipt_id is required")
        with self._locked():
            payload = self._read_locked()
            revoked = {str(value) for value in payload["revoked_authority_receipts"]}
            revoked.add(receipt_id)
            payload["revoked_authority_receipts"] = sorted(revoked)
            self._write_locked(payload)

    def reserve(
        self,
        *,
        provider: str,
        receipt_id: str,
        idempotency_key: str,
        resource_fingerprint: str,
    ) -> tuple[bool, str]:
        values = (provider, receipt_id, idempotency_key, resource_fingerprint)
        if not all(str(value or "").strip() for value in values):
            return False, "provider, receipt, idempotency, and resource fingerprint are required"
        compound_key = f"{provider.strip().lower()}:{idempotency_key.strip()}"
        with self._locked():
            payload = self._read_locked()
            if payload["kill_switch"] is True:
                return False, "product action kill switch is engaged"
            if receipt_id in {str(value) for value in payload["revoked_authority_receipts"]}:
                return False, "product action authority receipt is revoked"
            idempotency = payload["idempotency"]
            assert isinstance(idempotency, dict)
            if compound_key in idempotency:
                return False, "idempotency key has already crossed the provider boundary"
            idempotency[compound_key] = {
                "provider": provider.strip().lower(),
                "receipt_id": receipt_id,
                "resource_fingerprint": resource_fingerprint.lower(),
                "state": "reserved",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write_locked(payload)
            return True, "reserved"

    def classify(self, provider: str, idempotency_key: str, state: str) -> None:
        if state not in {"completed", "blocked", "reconcile_required"}:
            raise ValueError("unsupported product action terminal state")
        compound_key = f"{provider.strip().lower()}:{idempotency_key.strip()}"
        with self._locked():
            payload = self._read_locked()
            idempotency = payload["idempotency"]
            assert isinstance(idempotency, dict)
            existing = idempotency.get(compound_key)
            if not isinstance(existing, dict):
                raise RuntimeError("product action idempotency key was not reserved")
            existing["state"] = state
            existing["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_locked(payload)

    def reservation_is_active(
        self,
        *,
        provider: str,
        receipt_id: str,
        idempotency_key: str,
        resource_fingerprint: str,
    ) -> tuple[bool, str]:
        compound_key = f"{provider.strip().lower()}:{idempotency_key.strip()}"
        with self._locked():
            payload = self._read_locked()
            if payload["kill_switch"] is True:
                return False, "product action kill switch changed after reservation"
            if receipt_id in {str(value) for value in payload["revoked_authority_receipts"]}:
                return False, "product action authority was revoked after reservation"
            idempotency = payload["idempotency"]
            assert isinstance(idempotency, dict)
            existing = idempotency.get(compound_key)
            if not isinstance(existing, dict):
                return False, "product action reservation disappeared"
            if existing.get("receipt_id") != receipt_id:
                return False, "product action reservation receipt changed"
            if existing.get("resource_fingerprint") != resource_fingerprint.lower():
                return False, "product action reservation resource changed"
            if existing.get("state") != "reserved":
                return False, "product action reservation is no longer executable"
            return True, "reserved action remains active"

    def snapshot(self) -> dict[str, object]:
        with self._locked():
            return json.loads(json.dumps(self._read_locked()))
