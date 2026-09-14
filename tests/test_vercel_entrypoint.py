import os

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


def test_pump_live_box_is_namespaced_on_vercel_without_widening_main_api():
    from api import index

    assert isinstance(index._PUMP_LIVE_BOX_SESSION, PumpLiveBoxSession)
    assert index.pump_live_box_relative_path("/pump-live-box") == ""
    assert index.pump_live_box_relative_path("/pump-live-box/") == "/"
    assert (
        index.pump_live_box_relative_path("/pump-live-box/api/wallet")
        == "/api/wallet"
    )
    assert index.pump_live_box_relative_path("/api/wallet") is None
    assert index.pump_live_box_relative_path("/pump-live-boxer") is None


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
