import hashlib
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from backend.pump_live_box_server import PumpLiveBoxSession


def evidence(price=0.5):
    return {
        "source_url": "https://pump.fun/coin/MOM8",
        "symbol": "MOM8",
        "mint": "MOM8-DEMO-MINT",
        "price": price,
        "observed_at": "2026-09-14T03:30:00Z",
    }


class StateRelayHandler(BaseHTTPRequestHandler):
    token = "test-scoped-token"
    body = None
    etag = None

    def _authorized(self):
        return self.headers.get("Authorization") == f"Bearer {self.token}"

    def do_GET(self):
        if not self._authorized():
            self.send_response(401)
            self.end_headers()
            return
        if type(self).body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("ETag", type(self).etag)
        self.end_headers()
        self.wfile.write(type(self).body)

    def do_PUT(self):
        if not self._authorized():
            self.send_response(401)
            self.end_headers()
            return
        if type(self).body is None:
            if self.headers.get("If-None-Match") != "*":
                self.send_response(412)
                self.end_headers()
                return
        elif self.headers.get("If-Match") != type(self).etag:
            self.send_response(412)
            self.end_headers()
            return
        raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
        value = json.loads(raw.decode("utf-8"))
        assert isinstance(value, dict)
        type(self).body = raw
        type(self).etag = f'"{hashlib.sha256(raw).hexdigest()}"'
        self.send_response(204)
        self.send_header("ETag", type(self).etag)
        self.end_headers()

    def log_message(self, fmt, *args):
        pass


def start_relay():
    StateRelayHandler.body = None
    StateRelayHandler.etag = None
    server = ThreadingHTTPServer(("127.0.0.1", 0), StateRelayHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}/state"


@pytest.mark.asyncio
async def test_remote_practice_state_survives_host_replacement_and_conflict_fails_closed(
    tmp_path, monkeypatch
):
    relay, url = start_relay()
    monkeypatch.setenv("SLEEPWEALTH_PUMP_PRACTICE_STATE_URL", url)
    monkeypatch.setenv("SLEEPWEALTH_PUMP_PRACTICE_STATE_TOKEN", StateRelayHandler.token)
    try:
        first = PumpLiveBoxSession(
            100,
            state_path=None,
            session_id="remote-host-a",
            audit_path=str(tmp_path / "host-a-audit.jsonl"),
            practice_state_path=str(tmp_path / "ignored-local-a.json"),
            minimum_practice_executions=2,
            minimum_practice_round_trips=1,
        )
        buy = await first.propose(evidence(0.5), 10, "buy")
        bought = await first.approve(buy["proposal_id"])
        assert bought["practice_state"]["persisted"] is True
        assert bought["practice_state"]["transport"] == "remote-http"

        sell = await first.propose(evidence(0.75), 10, "sell")
        sold = await first.approve(sell["proposal_id"])
        assert sold["practice_state"]["persisted"] is True
        assert sold["practice_state"]["transport"] == "remote-http"
        ready = await first.graduation()
        assert ready["classification"] == "READY_FOR_ELIGIBILITY_REVIEW"
        assert ready["metrics"]["durable_state_persisted"] is True
        assert ready["metrics"]["durable_state_transport"] == "remote-http"
        assert ready["execution_authorized"] is False
        assert ready["real_money"] is False

        second = PumpLiveBoxSession(
            100,
            state_path=None,
            session_id="remote-host-b",
            audit_path=str(tmp_path / "host-b-audit.jsonl"),
            practice_state_path=str(tmp_path / "ignored-local-b.json"),
            minimum_practice_executions=2,
            minimum_practice_round_trips=1,
        )
        restored_wallet = await second.wallet()
        restored = await second.graduation()
        assert restored_wallet["cash"] == pytest.approx(102.5)
        assert restored_wallet["equity"] == pytest.approx(102.5)
        assert restored_wallet["pnl_total"] == pytest.approx(2.5)
        assert restored["metrics"]["execution_count"] == 2
        assert restored["metrics"]["completed_round_trips"] == 1
        assert restored["metrics"]["durable_state_transport"] == "remote-http"
        assert restored["classification"] == "READY_FOR_ELIGIBILITY_REVIEW"
        assert restored["platform_eligibility_verified"] is False
        assert restored["live_execution"] is False

        writer_a = PumpLiveBoxSession(
            100,
            state_path=None,
            session_id="remote-writer-a",
            audit_path=str(tmp_path / "writer-a-audit.jsonl"),
            minimum_practice_executions=2,
            minimum_practice_round_trips=1,
        )
        writer_b = PumpLiveBoxSession(
            100,
            state_path=None,
            session_id="remote-writer-b",
            audit_path=str(tmp_path / "writer-b-audit.jsonl"),
            minimum_practice_executions=2,
            minimum_practice_round_trips=1,
        )
        await writer_a.wallet()
        await writer_b.wallet()

        proposal_a = await writer_a.propose(evidence(0.5), 1, "buy")
        executed_a = await writer_a.approve(proposal_a["proposal_id"])
        assert executed_a["practice_state"]["persisted"] is True

        proposal_b = await writer_b.propose(evidence(0.5), 1, "buy")
        executed_b = await writer_b.approve(proposal_b["proposal_id"])
        assert executed_b["status"] == "executed"
        assert executed_b["practice_state"]["classification"] == "BLOCKED"
        assert executed_b["practice_state"]["persisted"] is False
        assert executed_b["practice_state"]["transport"] == "remote-http"
        assert executed_b["real_money"] is False
        assert executed_b["live_execution"] is False

        demoted = await writer_b.graduation()
        assert demoted["classification"] == "PRACTICE_REQUIRED"
        assert "DURABLE_STATE_PERSISTENCE" in demoted["blockers"]
        assert demoted["execution_authorized"] is False
        assert demoted["real_money"] is False
    finally:
        relay.shutdown()
        relay.server_close()


def test_remote_practice_state_requires_https_outside_loopback(monkeypatch):
    monkeypatch.setenv("SLEEPWEALTH_PUMP_PRACTICE_STATE_URL", "http://example.com/state")
    with pytest.raises(ValueError, match="requires HTTPS"):
        PumpLiveBoxSession(100, state_path=None, session_id="insecure-remote-state")
