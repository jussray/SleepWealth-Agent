import os

from backend.server import SleepWealthHandler


def test_vercel_entrypoint_uses_the_existing_paper_handler(monkeypatch):
    monkeypatch.delenv("SLEEPWEALTH_AUDIT_LOG", raising=False)

    from api.index import handler

    assert issubclass(handler, SleepWealthHandler)
    assert os.environ["SLEEPWEALTH_AUDIT_LOG"] == "/tmp/sleepwealth-audit.log"
