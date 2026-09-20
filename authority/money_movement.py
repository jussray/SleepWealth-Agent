from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import uuid
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from pathlib import Path
from typing import Mapping

try:
    import fcntl
except ImportError:  # pragma: no cover - persistent mode fails closed below
    fcntl = None


MIN_AUTHORITY_KEY_BYTES = 32
MAX_AUTHORITY_TTL_SECONDS = 5 * 60
MAX_CLOCK_SKEW_SECONDS = 5 * 60
STATE_VERSION = 1


class SandboxMoneyAction(StrEnum):
    ORDER_SUBMIT = "order-submit"


@dataclass(frozen=True, slots=True)
class SandboxAuthorityDecision:
    accepted: bool
    classification: str
    reason: str
    receipt_id: str | None = None
    proposal_id: str | None = None
    provider: str | None = None
    account_fingerprint: str | None = None
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "accepted": self.accepted,
            "classification": self.classification,
            "reason": self.reason,
            "receipt_id": self.receipt_id,
            "proposal_id": self.proposal_id,
            "provider": self.provider,
            "account_fingerprint": self.account_fingerprint,
            "idempotency_key": self.idempotency_key,
            "sandbox_only": True,
            "live_execution_authorized": False,
        }


def _key_bytes(value: object) -> bytes:
    if isinstance(value, bytes):
        key = value
    elif isinstance(value, str):
        key = value.encode("utf-8")
    else:
        return b""
    return key if len(key) >= MIN_AUTHORITY_KEY_BYTES else b""


def _canonical_payload(receipt: Mapping[str, object]) -> bytes:
    payload = dict(receipt)
    payload.pop("fingerprint", None)
    payload.pop("receipt_auth", None)
    return json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _fingerprint(receipt: Mapping[str, object]) -> str:
    return hashlib.sha256(_canonical_payload(receipt)).hexdigest()


def _valid_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and value.isascii()
        and all(char in "0123456789abcdefABCDEF" for char in value)
    )


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _finite_positive(value: object) -> bool:
    if isinstance(value, bool):
        return False
    try:
        number = float(value)
    except (TypeError, ValueError):
        return False
    return math.isfinite(number) and number > 0


def issue_sandbox_money_authority(
    *,
    issuer_id: str,
    issuer_key: str | bytes,
    proposal_id: str,
    subject: str,
    provider: str,
    account_fingerprint: str,
    approval_fingerprint: str,
    action: SandboxMoneyAction,
    symbol: str,
    asset_class: str,
    side: str,
    quantity: float,
    max_notional: float,
    idempotency_key: str | None = None,
    nonce: str | None = None,
    issued_at: datetime | None = None,
    ttl_seconds: int = 120,
) -> dict[str, object]:
    """Issue a trusted, short-lived authority receipt for sandbox execution only.

    The receipt binds one explicit human-approved proposal to one provider/account,
    order shape, notional ceiling, nonce, and idempotency key. It never authorizes
    real-money execution, transfers, funding, withdrawals, or wallet signatures.
    """

    key = _key_bytes(issuer_key)
    if not issuer_id.strip() or not key:
        raise ValueError("trusted issuer id and a 32+ byte key are required")
    if not proposal_id.strip() or not subject.strip() or not provider.strip():
        raise ValueError("proposal_id, subject, and provider are required")
    if not (_valid_sha256(account_fingerprint) and _valid_sha256(approval_fingerprint)):
        raise ValueError("account and approval fingerprints must be SHA-256 values")
    if action is not SandboxMoneyAction.ORDER_SUBMIT:
        raise ValueError("only sandbox order submission is representable")
    if not symbol.strip() or asset_class not in {"stocks", "crypto"}:
        raise ValueError("symbol and supported asset_class are required")
    if side.lower() not in {"buy", "sell"}:
        raise ValueError("side must be buy or sell")
    if not _finite_positive(quantity) or not _finite_positive(max_notional):
        raise ValueError("quantity and max_notional must be finite and positive")
    if not isinstance(ttl_seconds, int) or isinstance(ttl_seconds, bool):
        raise ValueError("ttl_seconds must be an integer")
    if ttl_seconds <= 0 or ttl_seconds > MAX_AUTHORITY_TTL_SECONDS:
        raise ValueError("authority TTL is outside the allowed window")

    now = issued_at or datetime.now(timezone.utc)
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    expires = datetime.fromtimestamp(now.timestamp() + ttl_seconds, tz=timezone.utc)
    receipt = {
        "schema": "sleepwealth-sandbox-money-authority-v1",
        "event": "sandbox_money_authority_issued",
        "classification": "SANDBOX_AUTHORIZED",
        "receipt_id": f"SMA-{uuid.uuid4().hex}",
        "proposal_id": proposal_id,
        "subject": subject,
        "provider": provider.strip().lower(),
        "account_fingerprint": account_fingerprint.lower(),
        "approval_fingerprint": approval_fingerprint.lower(),
        "action": action.value,
        "symbol": symbol.strip().upper(),
        "asset_class": asset_class,
        "side": side.lower(),
        "quantity": float(quantity),
        "max_notional": float(max_notional),
        "idempotency_key": (idempotency_key or f"idem-{uuid.uuid4().hex}").strip(),
        "nonce": (nonce or uuid.uuid4().hex).strip(),
        "issuer_id": issuer_id.strip(),
        "issued_at": now.isoformat(),
        "expires_at": expires.isoformat(),
        "sandbox_only": True,
        "live_execution_authorized": False,
        "funding_authorized": False,
        "transfer_authorized": False,
        "wallet_signature_authorized": False,
    }
    if not receipt["idempotency_key"] or not receipt["nonce"]:
        raise ValueError("idempotency_key and nonce must not be empty")
    receipt["fingerprint"] = _fingerprint(receipt)
    receipt["receipt_auth"] = hmac.new(key, _canonical_payload(receipt), hashlib.sha256).hexdigest()
    return receipt


def validate_sandbox_money_authority(
    receipt: Mapping[str, object] | None,
    trusted_keys: Mapping[str, object] | None,
    *,
    evaluated_at: datetime | None = None,
) -> SandboxAuthorityDecision:
    if receipt is None:
        return SandboxAuthorityDecision(False, "MISSING", "sandbox authority receipt is required")

    receipt_id = str(receipt.get("receipt_id", "")) or None
    proposal_id = str(receipt.get("proposal_id", "")) or None
    provider = str(receipt.get("provider", "")) or None
    account_fingerprint = str(receipt.get("account_fingerprint", "")) or None
    idempotency_key = str(receipt.get("idempotency_key", "")) or None

    def reject(classification: str, reason: str) -> SandboxAuthorityDecision:
        return SandboxAuthorityDecision(
            False,
            classification,
            reason,
            receipt_id,
            proposal_id,
            provider,
            account_fingerprint,
            idempotency_key,
        )

    invariants_ok = (
        receipt.get("schema") == "sleepwealth-sandbox-money-authority-v1"
        and receipt.get("event") == "sandbox_money_authority_issued"
        and receipt.get("classification") == "SANDBOX_AUTHORIZED"
        and receipt.get("sandbox_only") is True
        and receipt.get("live_execution_authorized") is False
        and receipt.get("funding_authorized") is False
        and receipt.get("transfer_authorized") is False
        and receipt.get("wallet_signature_authorized") is False
        and receipt.get("action") == SandboxMoneyAction.ORDER_SUBMIT.value
        and receipt.get("asset_class") in {"stocks", "crypto"}
        and receipt.get("side") in {"buy", "sell"}
        and isinstance(receipt_id, str)
        and receipt_id.startswith("SMA-")
        and bool(proposal_id)
        and bool(str(receipt.get("subject", "")).strip())
        and bool(provider)
        and _valid_sha256(account_fingerprint)
        and _valid_sha256(receipt.get("approval_fingerprint"))
        and bool(str(receipt.get("symbol", "")).strip())
        and _finite_positive(receipt.get("quantity"))
        and _finite_positive(receipt.get("max_notional"))
        and bool(idempotency_key)
        and bool(str(receipt.get("nonce", "")).strip())
    )
    if not invariants_ok:
        return reject("INVALID", "sandbox authority invariants failed")

    supplied_fingerprint = receipt.get("fingerprint")
    if not _valid_sha256(supplied_fingerprint):
        return reject("INVALID", "authority fingerprint is missing or malformed")
    calculated_fingerprint = _fingerprint(receipt)
    if not hmac.compare_digest(str(supplied_fingerprint).lower(), calculated_fingerprint.lower()):
        return reject("INVALID", "authority fingerprint does not match receipt contents")

    issuer_id = receipt.get("issuer_id")
    if not isinstance(issuer_id, str) or not issuer_id.strip() or not trusted_keys:
        return reject("UNTRUSTED", "trusted authority issuer is required")
    key = _key_bytes(trusted_keys.get(issuer_id))
    provided_auth = receipt.get("receipt_auth")
    if not key or not _valid_sha256(provided_auth):
        return reject("UNTRUSTED", "authority issuer is not trusted by this runtime")
    expected_auth = hmac.new(key, _canonical_payload(receipt), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(str(provided_auth).lower(), expected_auth.lower()):
        return reject("UNTRUSTED", "authority authentication failed")

    issued_at = _parse_timestamp(receipt.get("issued_at"))
    expires_at = _parse_timestamp(receipt.get("expires_at"))
    if not issued_at or not expires_at:
        return reject("INVALID", "authority timestamps are invalid")
    now = evaluated_at or datetime.now(timezone.utc)
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    issued_at = issued_at.astimezone(timezone.utc)
    expires_at = expires_at.astimezone(timezone.utc)
    ttl = (expires_at - issued_at).total_seconds()
    if ttl <= 0 or ttl > MAX_AUTHORITY_TTL_SECONDS:
        return reject("STALE", "authority TTL is outside the allowed window")
    if issued_at.timestamp() - MAX_CLOCK_SKEW_SECONDS > now.timestamp():
        return reject("STALE", "authority receipt was issued too far in the future")
    if now > expires_at:
        return reject("STALE", "authority receipt has expired")

    return SandboxAuthorityDecision(
        True,
        "VERIFIED_SANDBOX_AUTHORITY",
        "trusted, scoped sandbox authority is current",
        receipt_id,
        proposal_id,
        provider,
        account_fingerprint,
        idempotency_key,
    )


class SandboxAuthorityLedger:
    """Persistent replay, revocation, and kill-switch state for sandbox authority.

    This is not an approval queue. It consumes already-issued authority receipts and
    records whether a receipt/idempotency key has crossed the execution boundary.
    State is HMAC-sealed with a runtime key and updated atomically under a file lock.
    """

    def __init__(self, state_path: str | Path, state_key: str | bytes):
        self.path = Path(state_path)
        self.key = _key_bytes(state_key)
        if not self.key:
            raise ValueError("sandbox authority ledger requires a 32+ byte state key")
        if fcntl is None:
            raise RuntimeError("persistent sandbox authority state requires POSIX file locking")
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
            "revoked_receipts": [],
            "idempotency": {},
        }

    def _seal(self, payload: Mapping[str, object]) -> str:
        encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return hmac.new(self.key, encoded, hashlib.sha256).hexdigest()

    def _read_locked(self) -> dict[str, object]:
        if not self.path.exists():
            return self._empty()
        try:
            stored = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"sandbox authority ledger is unreadable: {exc}") from exc
        if not isinstance(stored, dict):
            raise RuntimeError("sandbox authority ledger shape is invalid")
        supplied = stored.get("seal")
        payload = {key: value for key, value in stored.items() if key != "seal"}
        if not _valid_sha256(supplied) or not hmac.compare_digest(str(supplied).lower(), self._seal(payload)):
            raise RuntimeError("sandbox authority ledger authentication failed")
        if payload.get("version") != STATE_VERSION:
            raise RuntimeError("sandbox authority ledger version is unsupported")
        if not isinstance(payload.get("kill_switch"), bool):
            raise RuntimeError("sandbox authority kill-switch state is invalid")
        if not isinstance(payload.get("revoked_receipts"), list):
            raise RuntimeError("sandbox authority revocation state is invalid")
        if not isinstance(payload.get("idempotency"), dict):
            raise RuntimeError("sandbox authority idempotency state is invalid")
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
        if not receipt_id.strip():
            raise ValueError("receipt_id is required")
        with self._locked():
            payload = self._read_locked()
            revoked = set(str(value) for value in payload["revoked_receipts"])
            revoked.add(receipt_id)
            payload["revoked_receipts"] = sorted(revoked)
            self._write_locked(payload)

    def reserve(self, receipt_id: str, idempotency_key: str) -> tuple[bool, str]:
        if not receipt_id.strip() or not idempotency_key.strip():
            return False, "receipt_id and idempotency_key are required"
        with self._locked():
            payload = self._read_locked()
            if payload["kill_switch"] is True:
                return False, "sandbox authority kill switch is engaged"
            if receipt_id in set(str(value) for value in payload["revoked_receipts"]):
                return False, "sandbox authority receipt is revoked"
            idempotency = payload["idempotency"]
            assert isinstance(idempotency, dict)
            existing = idempotency.get(idempotency_key)
            if existing is not None:
                return False, "idempotency key has already crossed the execution boundary"
            idempotency[idempotency_key] = {
                "receipt_id": receipt_id,
                "state": "reserved",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
            self._write_locked(payload)
            return True, "reserved"

    def classify(self, idempotency_key: str, state: str) -> None:
        if state not in {"completed", "blocked", "reconcile_required"}:
            raise ValueError("unsupported sandbox authority terminal state")
        with self._locked():
            payload = self._read_locked()
            idempotency = payload["idempotency"]
            assert isinstance(idempotency, dict)
            existing = idempotency.get(idempotency_key)
            if not isinstance(existing, dict):
                raise RuntimeError("idempotency key was not reserved")
            existing["state"] = state
            existing["updated_at"] = datetime.now(timezone.utc).isoformat()
            self._write_locked(payload)

    def snapshot(self) -> dict[str, object]:
        with self._locked():
            return json.loads(json.dumps(self._read_locked()))
