import os
from contextlib import contextmanager

from backend.pump_live_box_server import PumpLiveBoxSession
from backend.runtime_server import RuntimeIdentityHandler


def test_vercel_entrypoint_uses_runtime_identity_paper_handler(monkeypatch):
    monkeypatch.delenv("SLEEPWEALTH_AUDIT_LOG", raising=False)
    monkeypatch.delenv("SLEEPWEALTH_APPROVAL_STATE", raising=False)
    monkeypatch.delenv("SLEEPWEALTH_APPROVAL_STATE_SCOPE", raising=False)

    from api.index import handler

    assert issubclass(handler, RuntimeIdentityHandler)
    assert os.environ["SLEEPWEALTH_AUDIT_LOG"] == "/tmp/sleepwealth-audit.log"
    assert (
        os.environ["SLEEPWEALTH_APPROVAL_STATE"]
        == "/tmp/sleepwealth-paper-approvals.json"
    )
    assert (
        os.environ["SLEEPWEALTH_APPROVAL_STATE_SCOPE"]
        == "vercel-instance-ephemeral"
    )


def test_pump_vercel_handler_binds_request_oidc_without_exposing_it(monkeypatch):
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
    assert "request-oidc-token" not in str(index.pump_live_box_health_payload())


def test_pump_live_box_is_namespaced_on_vercel_without_widening_main_api():
    from api import index

    assert isinstance(index._PUMP_LIVE_BOX_SESSION, PumpLiveBoxSession)
    assert index.pump_live_box_relative_path("/pump-live-box") == ""
    assert index.pump_live_box_relative_path("/pump-live-box/") == "/"
    assert (
        index.pump_live_box_relative_path("/pump-live-box/api/wallet")
        == "/api/wallet"
    )
    assert (
        index.pump_live_box_relative_path("/pump-live-box/api/money-boundary")
        == "/api/money-boundary"
    )
    assert index.pump_live_box_relative_path("/api/wallet") is None
    assert index.pump_live_box_relative_path("/api/money-boundary") is None
    assert index.pump_live_box_relative_path("/pump-live-boxer") is None


def test_pump_live_box_vercel_health_binds_runtime_and_money_boundary(monkeypatch):
    from api import index

    source_sha = "a" * 40
    monkeypatch.setenv("SLEEPWEALTH_RUNTIME_SHA", source_sha)
    payload = index.pump_live_box_health_payload()

    assert payload["status"] == "ok"
    assert payload["authority"] == "sandbox-simulation-only"
    assert payload["real_money"] is False
    assert payload["live_execution"] is False
    assert payload["runtime_identity"]["source_sha"] == source_sha
    assert payload["runtime_identity"]["source_provider"] == "sleepwealth-runtime"
    assert payload["runtime_identity"]["exact_source_known"] is True
    assert payload["runtime_identity"]["execution_authorized"] is False
    assert payload["money_boundary"]["classification"] == "BLOCKED"
    assert payload["money_boundary"]["execution_authorized"] is False
    assert payload["money_boundary"]["real_money"] is False
    assert payload["money_boundary"]["live_execution"] is False


def test_pump_live_box_browser_calls_stay_inside_the_namespaced_surface():
    from api import index

    html = index._PUMP_LIVE_BOX_HTML
    assert "PUMP LIVE BOX" in html
    assert "PUBLIC EVIDENCE · READ-ONLY" in html
    assert "SIMULATED EXECUTION ONLY" in html
    assert "fetch('api/wallet')" in html
    assert "fetch('api/proposals'" in html
    assert "fetch('/api/wallet')" not in html
    assert "fetch('/api/proposals'" not in html
