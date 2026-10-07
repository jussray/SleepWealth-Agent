from types import SimpleNamespace

from api import index


def test_vybe_connect_route_renders_consent_without_execution(monkeypatch):
    seen = {}

    monkeypatch.setattr(index, "consent_html", lambda _config: "<html>consent</html>")

    class FakeHandler:
        path = "/connect/vybe"
        headers = {"host": "sleepwealth.example", "x-forwarded-proto": "https"}

        def _restore_sleepwealth_path(self):
            return None

        def _oauth_config(self):
            return SimpleNamespace(public_origin="https://sleepwealth.example")

        def _send_oauth_html(self, html, status=200):
            seen["html"] = html
            seen["status"] = int(status)
            return "served"

    result = index.handler.do_GET(FakeHandler())

    assert result == "served"
    assert seen == {"html": "<html>consent</html>", "status": 200}


def test_vybe_start_requires_trusted_origin_and_explicit_approval(monkeypatch):
    seen = {}

    def fake_begin(config, *, prepare_write):
        seen["config"] = config
        seen["prepare_write"] = prepare_write
        return "https://mcp.vybenetwork.xyz/authorize?state=abc", "preauth=sealed"

    monkeypatch.setattr(index, "begin_authorization", fake_begin)

    class FakeHandler:
        path = "/connect/vybe/start"
        headers = {
            "origin": "https://sleepwealth.example",
            "host": "sleepwealth.example",
            "x-forwarded-proto": "https",
        }

        def _restore_sleepwealth_path(self):
            return None

        def _oauth_config(self):
            return SimpleNamespace(public_origin="https://sleepwealth.example")

        def _read_form_object(self):
            return {"approve": ["yes"], "prepare_write": ["yes"]}

        def _temporary_redirect(self, location, *, cookies=()):
            seen["location"] = location
            seen["cookies"] = cookies
            return "redirected"

        def _send_json(self, payload, status=200):
            raise AssertionError((payload, status))

    result = index.handler.do_POST(FakeHandler())

    assert result == "redirected"
    assert seen["prepare_write"] is True
    assert seen["location"].startswith("https://mcp.vybenetwork.xyz/authorize")
    assert seen["cookies"] == ("preauth=sealed",)


def test_vybe_start_rejects_cross_origin_before_oauth(monkeypatch):
    called = False
    seen = {}

    def fake_begin(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("OAuth should not start")

    monkeypatch.setattr(index, "begin_authorization", fake_begin)

    class FakeHandler:
        path = "/connect/vybe/start"
        headers = {
            "origin": "https://attacker.example",
            "host": "sleepwealth.example",
            "x-forwarded-proto": "https",
        }

        def _restore_sleepwealth_path(self):
            return None

        def _oauth_config(self):
            return SimpleNamespace(public_origin="https://sleepwealth.example")

        def _read_form_object(self):
            return {"approve": ["yes"]}

        def _send_json(self, payload, status=200):
            seen["payload"] = payload
            seen["status"] = int(status)
            return "blocked"

    result = index.handler.do_POST(FakeHandler())

    assert result == "blocked"
    assert called is False
    assert seen["status"] == 400
    assert seen["payload"]["classification"] == "VYBE_OAUTH_START_BLOCKED"


def test_vybe_callback_sets_only_sealed_session_cookies(monkeypatch):
    seen = {}

    def fake_finish(config, *, code, state, cookie_header):
        assert code == "code-1"
        assert state == "state-1"
        assert cookie_header == "__Host-sw-vybe-preauth=sealed"
        return (
            {
                "status": "connected",
                "access_token_exposed": False,
                "execution_authorized": False,
            },
            ("clear-preauth", "sealed-session", "sealed-grant"),
        )

    monkeypatch.setattr(index, "finish_authorization", fake_finish)

    class FakeHandler:
        path = "/connect/vybe/callback?code=code-1&state=state-1"
        headers = {"cookie": "__Host-sw-vybe-preauth=sealed"}

        def _restore_sleepwealth_path(self):
            return None

        def _oauth_config(self):
            return object()

        def _temporary_redirect(self, location, *, cookies=()):
            seen["location"] = location
            seen["cookies"] = cookies
            return "redirected"

        def _send_json(self, payload, status=200):
            raise AssertionError((payload, status))

    result = index.handler.do_GET(FakeHandler())

    assert result == "redirected"
    assert seen["location"] == "/connect/vybe/status"
    assert seen["cookies"] == ("clear-preauth", "sealed-session", "sealed-grant")


def test_vybe_status_returns_nonsecret_connection_receipt(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        index,
        "session_status",
        lambda _config, *, cookie_header: {
            "status": "connected",
            "scopes": ["mcp:read", "mcp:write"],
            "effects": ["read"],
            "access_token_exposed": False,
            "execution_authorized": False,
        },
    )

    class FakeHandler:
        path = "/connect/vybe/status"
        headers = {"cookie": "sealed-session"}

        def _restore_sleepwealth_path(self):
            return None

        def _oauth_config(self):
            return object()

        def _send_json(self, payload, status=200):
            seen["payload"] = payload
            seen["status"] = int(status)
            return "served"

    result = index.handler.do_GET(FakeHandler())

    assert result == "served"
    assert seen["status"] == 200
    assert seen["payload"]["access_token_exposed"] is False
    assert seen["payload"]["execution_authorized"] is False


def test_vybe_session_proof_uses_sealed_token_and_grant_without_exposing_raw_data(
    monkeypatch,
):
    seen = {}

    monkeypatch.setattr(
        index,
        "session_context",
        lambda _config, *, cookie_header: (
            {"access_token": "secret-token"},
            {"grant_id": "HCG-test", "scope_fingerprint": "a" * 64},
        ),
    )

    async def fake_proof(**kwargs):
        seen["proof_kwargs"] = kwargs
        return 200, {
            "status": "ok",
            "classification": "VERIFIED_LIVE_READ",
            "raw_market_data_exposed": False,
            "execution_authorized": False,
        }

    monkeypatch.setattr(index, "deployed_vybe_proof", fake_proof)

    class FakeHandler:
        path = "/connect/vybe/proof"
        headers = {"cookie": "sealed-session"}

        def _restore_sleepwealth_path(self):
            return None

        def _oauth_config(self):
            return object()

        def _send_json(self, payload, status=200):
            seen["payload"] = payload
            seen["status"] = int(status)
            return "served"

    result = index.handler.do_GET(FakeHandler())

    assert result == "served"
    assert seen["status"] == 200
    assert seen["proof_kwargs"]["bearer_token"] == "secret-token"
    assert seen["proof_kwargs"]["allow_session_production"] is True
    assert seen["payload"]["raw_market_data_exposed"] is False
    assert "secret-token" not in str(seen["payload"])


def test_vybe_logout_clears_session_cookies(monkeypatch):
    seen = {}
    monkeypatch.setattr(
        index,
        "clear_oauth_cookies",
        lambda: ("clear-preauth", "clear-session", "clear-grant"),
    )

    class FakeHandler:
        path = "/connect/vybe/logout"
        headers = {}

        def _restore_sleepwealth_path(self):
            return None

        def _temporary_redirect(self, location, *, cookies=()):
            seen["location"] = location
            seen["cookies"] = cookies
            return "redirected"

    result = index.handler.do_POST(FakeHandler())

    assert result == "redirected"
    assert seen["location"] == "/connect/vybe"
    assert seen["cookies"] == ("clear-preauth", "clear-session", "clear-grant")
