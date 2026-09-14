"""Provider-neutral durable state transport for sandbox practice evidence.

The transport stores simulation snapshots only. It never grants broker, wallet,
signing, funding, transfer, minting, or real-money authority.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


class PracticeStateConflict(RuntimeError):
    """Raised when another writer advanced durable practice state first."""


@dataclass(frozen=True, slots=True)
class PracticeStateRecord:
    snapshot: dict[str, object]
    version: str


class FilePracticeStateStore:
    kind = "local-file"

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def read(self) -> PracticeStateRecord | None:
        if not self.path.exists():
            return None
        try:
            value = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"practice state is unreadable: {exc}") from exc
        if not isinstance(value, dict):
            raise RuntimeError("practice state must be a JSON object")
        version = str(value.get("state_fingerprint") or "").lower()
        return PracticeStateRecord(dict(value), version)

    def write(self, snapshot: dict[str, object], expected_version: str | None) -> str:
        current = self.read()
        if expected_version is None:
            if current is not None:
                raise PracticeStateConflict("practice state appeared after restore; refusing overwrite")
        elif current is None or current.version != expected_version:
            raise PracticeStateConflict("practice state changed since restore; refusing stale overwrite")

        version = str(snapshot.get("state_fingerprint") or "").lower()
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}.tmp")
        encoded = (json.dumps(snapshot, sort_keys=True, default=str) + "\n").encode("utf-8")
        try:
            with open(tmp, "wb") as fh:
                fh.write(encoded)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            try:
                tmp.unlink(missing_ok=True)
            except OSError:
                pass
        return version


class HttpPracticeStateStore:
    """GET/conditional-PUT state endpoint with standard ETag concurrency control."""

    kind = "remote-http"

    def __init__(self, url: str, bearer_token: str | None = None, timeout: float = 5.0):
        parsed = urlparse(str(url).strip())
        host = (parsed.hostname or "").lower()
        loopback = host in {"localhost", "127.0.0.1", "::1"}
        if parsed.scheme not in ({"http", "https"} if loopback else {"https"}):
            raise ValueError("remote practice state requires HTTPS outside loopback test hosts")
        if not parsed.netloc:
            raise ValueError("remote practice state URL must include a host")
        self.url = str(url).strip()
        self.bearer_token = str(bearer_token).strip() if bearer_token else None
        self.timeout = float(timeout)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Cache-Control": "no-store"}
        if self.bearer_token:
            headers["Authorization"] = f"Bearer {self.bearer_token}"
        return headers

    def read(self) -> PracticeStateRecord | None:
        request = Request(self.url, method="GET", headers=self._headers())
        try:
            with urlopen(request, timeout=self.timeout) as response:  # nosec B310 - URL is validated above
                raw = response.read()
                etag = response.headers.get("ETag")
        except HTTPError as exc:
            if exc.code == 404:
                return None
            raise RuntimeError(f"remote practice state read failed with HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError("remote practice state read failed") from exc
        if not etag:
            raise RuntimeError("remote practice state response is missing ETag")
        try:
            value = json.loads(raw.decode("utf-8"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("remote practice state returned invalid JSON") from exc
        if not isinstance(value, dict):
            raise RuntimeError("remote practice state must be a JSON object")
        return PracticeStateRecord(dict(value), str(etag))

    def write(self, snapshot: dict[str, object], expected_version: str | None) -> str:
        headers = self._headers()
        headers["Content-Type"] = "application/json"
        if expected_version is None:
            headers["If-None-Match"] = "*"
        else:
            headers["If-Match"] = expected_version
        request = Request(
            self.url,
            data=json.dumps(snapshot, sort_keys=True, default=str).encode("utf-8"),
            method="PUT",
            headers=headers,
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:  # nosec B310 - URL is validated above
                etag = response.headers.get("ETag")
        except HTTPError as exc:
            if exc.code in {409, 412}:
                raise PracticeStateConflict(
                    "remote practice state changed since restore; refusing stale overwrite"
                ) from exc
            raise RuntimeError(f"remote practice state write failed with HTTP {exc.code}") from exc
        except URLError as exc:
            raise RuntimeError("remote practice state write failed") from exc
        if not etag:
            raise RuntimeError("remote practice state write response is missing ETag")
        return str(etag)


def practice_state_store(path: str | None):
    """Prefer a remote conditional object endpoint when explicitly configured."""

    remote_url = os.getenv("SLEEPWEALTH_PUMP_PRACTICE_STATE_URL", "").strip()
    if remote_url:
        return HttpPracticeStateStore(
            remote_url,
            bearer_token=os.getenv("SLEEPWEALTH_PUMP_PRACTICE_STATE_TOKEN") or None,
            timeout=float(os.getenv("SLEEPWEALTH_PUMP_PRACTICE_STATE_TIMEOUT", "5")),
        )
    if path:
        return FilePracticeStateStore(path)
    return None
