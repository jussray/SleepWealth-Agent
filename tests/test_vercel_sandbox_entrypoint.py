from backend.pump_live_sandbox import PumpEvidenceSandboxHandler, PumpEvidenceSandboxSession


def test_vercel_sandbox_entrypoint_uses_evidence_bound_practice_handler():
    from api.sandbox import _SESSION, handler

    assert issubclass(handler, PumpEvidenceSandboxHandler)
    assert isinstance(_SESSION, PumpEvidenceSandboxSession)
    assert _SESSION.broker.is_paper_only() is True
