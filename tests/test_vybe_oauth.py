from http.cookies import SimpleCookie
from urllib.parse import parse_qs, urlparse

import httpx
import pytest

from backend.vybe_oauth import (
    VYBE_OAUTH_RESOURCE,
    VybeOAuthConfig,
    begin_authorization,
    consent_html,
    finish_authorization,
    session_status,
)


SOURCE_SHA = "a" * 40
SESSION_KEY = "s" * 48
PERMISSION_KEY = "p" * 48


def _config(*, prepare=False, client_id="client-static"):
    return VybeOAuthConfig(
        public_origin="https://sleepwealth.example",
        session_secret=SESSION_KEY,
        permission_issuer="permission-issuer",
        permission_key=PERMISSION_KEY,
        source_sha=SOURCE_SHA,
        allow_prepare_write_consent=prepare,
        client_id=client_id,
    )


def _cookie_header(*set_cookie_headers):
    pairs = []
    for value in set_cookie_headers:
        jar = SimpleCookie()
        jar.load(value)
        for key, morsel in jar.items():
            pairs.append(f"{key}={morsel.value}")
    return "; ".join(pairs)


def test_consent_page_declares_oauth_scopes_and_human_boundary():
    html = consent_html(_config(prepare=True))

    assert "mcp:read mcp:write" in html
    assert "HUMAN AUTHORIZATION FIRST" in html
    assert "prepare_write" in html
    assert "No signing or broadcast" in html


def test_prepare_write_option_is_hidden_when_deployment_gate_is_off():
    html = consent_html(_config(prepare=False))

    assert "mcp:read mcp:write" in html
    assert "prepare_write" not in html


def test_begin_authorization_uses_pkce_resource_and_sealed_preauth_cookie():
    redirect, set_cookie = begin_authorization(
        _config(prepare=True),
        prepare_write=True,
        now=1_000,
    )

    parsed = urlparse(redirect)
    query = parse_qs(parsed.query)
    assert parsed.path == "/authorize"
    assert query["scope"] == ["openid email mcp:read mcp:write"]
    assert query["resource"] == [VYBE_OAUTH_RESOURCE]
    assert query["code_challenge_method"] == ["S256"]
    assert len(query["code_challenge"][0]) >= 43
    assert query["redirect_uri"] == [
        "https://sleepwealth.example/connect/vybe/callback"
    ]
    assert "__Host-sw-vybe-preauth=" in set_cookie
    assert "HttpOnly" in set_cookie
    assert "Secure" in set_cookie
    assert "SameSite=Lax" in set_cookie
    assert query["state"][0] not in set_cookie


def test_prepare_write_cannot_be_requested_when_deployment_gate_is_off():
    with pytest.raises(PermissionError, match="prepare-write"):
        begin_authorization(
            _config(prepare=False),
            prepare_write=True,
            now=1_000,
        )


def test_dynamic_registration_uses_public_client_contract():
    seen = {}

    def handler(request):
        if request.url.path == "/register":
            seen["registration"] = request
            return httpx.Response(201, json={"client_id": "dynamic-client"})
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    redirect, _ = begin_authorization(
        _config(prepare=False, client_id=None),
        prepare_write=False,
        client=client,
        now=1_000,
    )

    body = seen["registration"].read().decode()
    assert '"token_endpoint_auth_method":"none"' in body
    assert '"grant_types":["authorization_code"]' in body
    assert '"response_types":["code"]' in body
    assert "dynamic-client" in redirect


def test_finish_authorization_seals_token_and_mints_human_capability_grant():
    config = _config(prepare=True)
    redirect, preauth_cookie = begin_authorization(
        config,
        prepare_write=True,
        now=1_000,
    )
    state = parse_qs(urlparse(redirect).query)["state"][0]

    seen = {"token": 0, "userinfo": 0}

    def handler(request):
        if request.url.path == "/token":
            seen["token"] += 1
            body = request.read().decode()
            assert "code_verifier=" in body
            assert "client_id=client-static" in body
            assert "resource=https%3A%2F%2Fmcp.vybenetwork.xyz%2Fmcp" in body
            return httpx.Response(
                200,
                json={
                    "access_token": "super-secret-access-token",
                    "refresh_token": "must-not-be-persisted",
                    "token_type": "Bearer",
                    "expires_in": 1800,
                    "scope": "openid email mcp:read mcp:write",
                },
            )
        if request.url.path == "/userinfo":
            seen["userinfo"] += 1
            assert request.headers["authorization"] == "Bearer super-secret-access-token"
            return httpx.Response(
                200,
                json={"sub": "vybe-user-123", "email": "hidden@example.test"},
            )
        raise AssertionError(f"unexpected request: {request.url}")

    client = httpx.Client(transport=httpx.MockTransport(handler))
    payload, cookies = finish_authorization(
        config,
        code="oauth-code",
        state=state,
        cookie_header=_cookie_header(preauth_cookie),
        client=client,
        now=1_010,
    )

    assert seen == {"token": 1, "userinfo": 1}
    assert payload["status"] == "connected"
    assert payload["effects"] == ["read", "prepare-write"]
    assert payload["access_token_exposed"] is False
    assert payload["refresh_token_persisted"] is False
    assert payload["human_capability_grant_id"].startswith("HCG-")
    assert "super-secret-access-token" not in str(payload)
    assert "must-not-be-persisted" not in str(cookies)

    status = session_status(
        config,
        cookie_header=_cookie_header(*cookies[1:]),
        now=1_020,
    )
    assert status["status"] == "connected"
    assert status["effects"] == ["read", "prepare-write"]
    assert "build-vybe-transaction" in status["actions"]
    assert status["access_token_exposed"] is False
    assert status["execution_authorized"] is False
    assert status["signing_authorized"] is False
    assert status["broadcast_authorized"] is False
    assert status["payment_authorized"] is False
    assert "super-secret-access-token" not in str(status)


def test_callback_rejects_state_mismatch_before_token_exchange():
    config = _config()
    _, preauth_cookie = begin_authorization(
        config,
        prepare_write=False,
        now=1_000,
    )
    called = False

    def handler(_request):
        nonlocal called
        called = True
        return httpx.Response(500)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    with pytest.raises(ValueError, match="state"):
        finish_authorization(
            config,
            code="oauth-code",
            state="wrong-state",
            cookie_header=_cookie_header(preauth_cookie),
            client=client,
            now=1_010,
        )

    assert called is False


def test_session_is_source_bound_and_expires():
    config = _config()
    redirect, preauth_cookie = begin_authorization(
        config,
        prepare_write=False,
        now=1_000,
    )
    state = parse_qs(urlparse(redirect).query)["state"][0]

    def handler(request):
        if request.url.path == "/token":
            return httpx.Response(
                200,
                json={
                    "access_token": "token",
                    "token_type": "Bearer",
                    "expires_in": 30,
                    "scope": "openid email mcp:read mcp:write",
                },
            )
        if request.url.path == "/userinfo":
            return httpx.Response(200, json={"sub": "subject"})
        raise AssertionError

    client = httpx.Client(transport=httpx.MockTransport(handler))
    _, cookies = finish_authorization(
        config,
        code="oauth-code",
        state=state,
        cookie_header=_cookie_header(preauth_cookie),
        client=client,
        now=1_010,
    )
    connected = _cookie_header(*cookies[1:])

    with pytest.raises(ValueError, match="expired"):
        session_status(config, cookie_header=connected, now=1_041)

    stale_config = VybeOAuthConfig(
        public_origin=config.public_origin,
        session_secret=config.session_secret,
        permission_issuer=config.permission_issuer,
        permission_key=config.permission_key,
        source_sha="b" * 40,
        client_id=config.client_id,
    )
    with pytest.raises(ValueError, match="source SHA"):
        session_status(stale_config, cookie_header=connected, now=1_020)
