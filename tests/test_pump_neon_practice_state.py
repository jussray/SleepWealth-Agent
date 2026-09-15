import json
from contextlib import contextmanager

import pytest

import backend.practice_state_store as state_module
from backend.practice_state_store import (
    DEFAULT_NEON_PRACTICE_STATE_URL,
    PUMP_LIVE_BOX_VERCEL_PROJECT_ID,
    NeonDataApiPracticeStateStore,
    PracticeStateConflict,
    practice_state_identity,
    practice_state_store,
)
from backend.pump_live_box_server import PumpLiveBoxSession


class FakeResponse:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode("utf-8")

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def read(self):
        return self.payload


def headers(request):
    return {key.lower(): value for key, value in request.header_items()}


def test_exact_pump_vercel_project_selects_neon_without_static_secret(monkeypatch):
    monkeypatch.delenv("SLEEPWEALTH_PUMP_PRACTICE_STATE_URL", raising=False)
    monkeypatch.delenv("SLEEPWEALTH_PUMP_PRACTICE_STATE_DRIVER", raising=False)
    monkeypatch.delenv("SLEEPWEALTH_PUMP_PRACTICE_STATE_TOKEN", raising=False)
    monkeypatch.setenv("VERCEL_PROJECT_ID", PUMP_LIVE_BOX_VERCEL_PROJECT_ID)

    store = practice_state_store(None)

    assert isinstance(store, NeonDataApiPracticeStateStore)
    assert store.kind == "neon-data-api"
    assert store.url == DEFAULT_NEON_PRACTICE_STATE_URL
    assert "token" not in store.__dict__


def test_non_target_vercel_project_does_not_borrow_pump_witness(monkeypatch):
    monkeypatch.delenv("SLEEPWEALTH_PUMP_PRACTICE_STATE_URL", raising=False)
    monkeypatch.delenv("SLEEPWEALTH_PUMP_PRACTICE_STATE_DRIVER", raising=False)
    monkeypatch.setenv("VERCEL_PROJECT_ID", "prj_other_sleepwealth_surface")

    assert practice_state_store(None) is None


@pytest.mark.asyncio
async def test_target_project_missing_oidc_fails_restore_closed(monkeypatch):
    monkeypatch.delenv("SLEEPWEALTH_PUMP_PRACTICE_STATE_URL", raising=False)
    monkeypatch.delenv("SLEEPWEALTH_PUMP_PRACTICE_STATE_DRIVER", raising=False)
    monkeypatch.setenv("VERCEL_PROJECT_ID", PUMP_LIVE_BOX_VERCEL_PROJECT_ID)

    session = PumpLiveBoxSession(
        100,
        state_path=None,
        session_id="missing-oidc",
        practice_state_path=None,
    )

    with pytest.raises(RuntimeError, match="OIDC identity is unavailable"):
        await session.wallet()


def test_neon_read_uses_request_oidc_and_never_stores_it(monkeypatch):
    fingerprint = "a" * 64
    snapshot = {
        "state_fingerprint": fingerprint,
        "state_cookie": f"pump-practice-state-v1:{fingerprint[:24]}",
    }
    seen = []

    def fake_urlopen(request, timeout):
        seen.append((request, timeout))
        return FakeResponse([{"snapshot": snapshot, "version": fingerprint}])

    monkeypatch.setattr(state_module, "urlopen", fake_urlopen)
    store = NeonDataApiPracticeStateStore(DEFAULT_NEON_PRACTICE_STATE_URL, timeout=2.5)

    with practice_state_identity("short-lived-vercel-oidc"):
        record = store.read()

    assert record is not None
    assert record.version == fingerprint
    assert record.snapshot == snapshot
    request, timeout = seen[0]
    request_headers = headers(request)
    assert timeout == 2.5
    assert request.full_url.endswith("/rpc/pump_practice_state_get")
    assert request_headers["authorization"] == "Bearer short-lived-vercel-oidc"
    assert request_headers["accept-profile"] == "sleepwealth_witness"
    assert request_headers["content-profile"] == "sleepwealth_witness"
    assert "short-lived-vercel-oidc" not in repr(store.__dict__)


def test_neon_write_binds_expected_version_and_accepts_compare_and_swap(monkeypatch):
    prior = "a" * 64
    current = "b" * 64
    snapshot = {
        "state_fingerprint": current,
        "state_cookie": f"pump-practice-state-v1:{current[:24]}",
    }
    seen = []

    def fake_urlopen(request, timeout):
        seen.append(request)
        return FakeResponse(
            [{"accepted": True, "version": current, "current_version": prior}]
        )

    monkeypatch.setattr(state_module, "urlopen", fake_urlopen)
    store = NeonDataApiPracticeStateStore(DEFAULT_NEON_PRACTICE_STATE_URL)

    with practice_state_identity("oidc-write-token"):
        version = store.write(snapshot, prior)

    assert version == current
    request = seen[0]
    assert request.full_url.endswith("/rpc/pump_practice_state_put")
    body = json.loads(request.data.decode("utf-8"))
    assert body == {"p_expected_version": prior, "p_snapshot": snapshot}
    assert headers(request)["authorization"] == "Bearer oidc-write-token"


def test_neon_stale_writer_is_a_distinct_conflict_without_token_leak(monkeypatch):
    prior = "a" * 64
    current = "b" * 64
    snapshot = {
        "state_fingerprint": current,
        "state_cookie": f"pump-practice-state-v1:{current[:24]}",
    }

    def fake_urlopen(request, timeout):
        return FakeResponse(
            [{"accepted": False, "version": prior, "current_version": prior}]
        )

    monkeypatch.setattr(state_module, "urlopen", fake_urlopen)
    store = NeonDataApiPracticeStateStore(DEFAULT_NEON_PRACTICE_STATE_URL)

    with practice_state_identity("never-echo-this-token"):
        with pytest.raises(PracticeStateConflict) as exc_info:
            store.write(snapshot, prior)

    assert "never-echo-this-token" not in str(exc_info.value)
    assert "stale overwrite" in str(exc_info.value)


def test_neon_carrier_rejects_non_https_endpoint():
    with pytest.raises(ValueError, match="requires an HTTPS"):
        NeonDataApiPracticeStateStore("http://example.com/rest/v1")


def test_vercel_handler_binds_oidc_header_only_for_pump_request(monkeypatch):
    from api import index

    seen = []

    @contextmanager
    def fake_identity(token):
        seen.append(("token", token))
        yield

    monkeypatch.setattr(index, "practice_state_identity", fake_identity)

    class FakeHandler:
        path = "/pump-live-box/api/money-boundary"
        headers = {"x-vercel-oidc-token": "request-oidc-token"}

        def _restore_sleepwealth_path(self):
            return None

        def _serve_pump_get(self, relative_path):
            seen.append(("path", relative_path))
            return "served"

    result = index.handler.do_GET(FakeHandler())

    assert result == "served"
    assert seen == [
        ("token", "request-oidc-token"),
        ("path", "/api/money-boundary"),
    ]
    assert "request-oidc-token" not in json.dumps(index.pump_live_box_health_payload())
