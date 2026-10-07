from __future__ import annotations

import base64
import hashlib
import json
import os
import secrets
import time
from dataclasses import dataclass
from http.cookies import SimpleCookie
from typing import Mapping, Sequence
from urllib.parse import urlencode

import httpx
from cryptography.fernet import Fernet, InvalidToken

from backend.runtime_identity import runtime_identity
from integrations.vybe_mcp import (
    DEFAULT_VYBE_MCP_ENDPOINT,
    VYBE_OAUTH_SCOPES,
    VYBE_PREPARE_WRITE_TOOLS,
    VYBE_READ_TOOLS,
)
from mcp_gateway.human_permission import issue_human_capability_grant


VYBE_OAUTH_REGISTRATION_URL = "https://mcp.vybenetwork.xyz/register"
VYBE_OAUTH_AUTHORIZATION_URL = "https://mcp.vybenetwork.xyz/authorize"
VYBE_OAUTH_TOKEN_URL = "https://mcp.vybenetwork.xyz/token"
VYBE_OAUTH_USERINFO_URL = "https://mcp.vybenetwork.xyz/userinfo"
VYBE_OAUTH_RESOURCE = DEFAULT_VYBE_MCP_ENDPOINT

_PREAUTH_COOKIE = "__Host-sw-vybe-preauth"
_SESSION_COOKIE = "__Host-sw-vybe-session"
_GRANT_COOKIE = "__Host-sw-vybe-grant"
_DEFAULT_SESSION_SECONDS = 3600
_MAX_SESSION_SECONDS = 3600
_PREAUTH_SECONDS = 600


@dataclass(frozen=True, slots=True)
class VybeOAuthConfig:
    public_origin: str
    session_secret: str
    permission_issuer: str
    permission_key: str
    source_sha: str
    allow_prepare_write_consent: bool = False
    client_id: str | None = None

    @property
    def redirect_uri(self) -> str:
        return self.public_origin.rstrip("/") + "/connect/vybe/callback"


def _bool_env(name: str) -> bool:
    return os.getenv(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _pkce_pair() -> tuple[str, str]:
    verifier = _b64url(secrets.token_bytes(48))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


def _fernet(secret: str) -> Fernet:
    value = str(secret or "")
    if len(value.encode("utf-8")) < 32:
        raise ValueError("SLEEPWEALTH_VYBE_OAUTH_SESSION_KEY must be at least 32 bytes")
    key = base64.urlsafe_b64encode(hashlib.sha256(value.encode("utf-8")).digest())
    return Fernet(key)


def _seal(payload: Mapping[str, object], secret: str) -> str:
    encoded = json.dumps(
        dict(payload),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return _fernet(secret).encrypt(encoded).decode("ascii")


def _open(token: str, secret: str) -> dict[str, object]:
    try:
        decoded = _fernet(secret).decrypt(token.encode("ascii"))
        payload = json.loads(decoded.decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError("sealed OAuth session is invalid") from exc
    if not isinstance(payload, dict):
        raise ValueError("sealed OAuth session must contain an object")
    return payload


def _cookie_value(cookie_header: str | None, name: str) -> str | None:
    if not cookie_header:
        return None
    jar = SimpleCookie()
    jar.load(cookie_header)
    morsel = jar.get(name)
    return morsel.value if morsel is not None else None


def _cookie(name: str, value: str, *, max_age: int) -> str:
    return (
        f"{name}={value}; Path=/; Max-Age={max_age}; "
        "Secure; HttpOnly; SameSite=Lax"
    )


def clear_oauth_cookies() -> tuple[str, str, str]:
    return tuple(
        _cookie(name, "", max_age=0)
        for name in (_PREAUTH_COOKIE, _SESSION_COOKIE, _GRANT_COOKIE)
    )


def config_from_env(public_origin: str) -> VybeOAuthConfig:
    origin = str(public_origin or "").strip().rstrip("/")
    if not origin.startswith("https://"):
        raise ValueError("Vybe OAuth requires an HTTPS public origin")

    expected = os.getenv("SLEEPWEALTH_PUBLIC_ORIGIN", "").strip().rstrip("/")
    if expected and expected != origin:
        raise ValueError("request origin does not match SLEEPWEALTH_PUBLIC_ORIGIN")

    identity = runtime_identity()
    source_sha = str(identity.get("source_sha") or "")
    if not identity.get("exact_source_known") or len(source_sha) != 40:
        raise ValueError("Vybe OAuth requires exact deployed source identity")

    session_secret = os.getenv("SLEEPWEALTH_VYBE_OAUTH_SESSION_KEY", "").strip()
    permission_issuer = os.getenv("SLEEPWEALTH_MCP_PERMISSION_ISSUER", "").strip()
    permission_key = os.getenv("SLEEPWEALTH_MCP_PERMISSION_KEY", "").strip()
    if not session_secret or not permission_issuer or not permission_key:
        raise ValueError("Vybe OAuth runtime secrets are not configured")

    client_id = os.getenv("SLEEPWEALTH_VYBE_OAUTH_CLIENT_ID", "").strip() or None
    return VybeOAuthConfig(
        public_origin=origin,
        session_secret=session_secret,
        permission_issuer=permission_issuer,
        permission_key=permission_key,
        source_sha=source_sha,
        allow_prepare_write_consent=_bool_env(
            "SLEEPWEALTH_VYBE_ALLOW_PREPARE_WRITE_CONSENT"
        ),
        client_id=client_id,
    )


def consent_html(config: VybeOAuthConfig) -> str:
    prepare = ""
    if config.allow_prepare_write_consent:
        prepare = """
        <label class="choice">
          <input type="checkbox" name="prepare_write" value="yes">
          <span><b>Prepare unsigned writes</b><small>Allow unsigned Vybe transaction
          payload construction inside the human-approved scope. No signing or broadcast.</small></span>
        </label>
        """

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Connect Vybe · Sleep Wealth</title>
<style>
body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0b0f0c;color:#eee5cc;
font-family:Inter,system-ui,sans-serif;padding:20px}}main{{width:min(720px,100%);border:1px solid #343b31;
background:#151a15;padding:28px;border-radius:8px 24px 8px 24px}}h1{{margin:.2rem 0 1rem;font-size:2.6rem}}
p,small{{color:#a8ad98;line-height:1.5}}.scope{{font-family:ui-monospace,monospace;background:#0d110d;
padding:12px;border-radius:8px;margin:16px 0}}.choice{{display:flex;gap:12px;border:1px solid #3a4136;
padding:14px;margin:12px 0;border-radius:8px}}.choice input{{margin-top:4px}}.choice span{{display:grid;gap:4px}}
button{{margin-top:14px;padding:13px 16px;background:#d6ff45;color:#12170f;border:0;border-radius:8px;
font-weight:800;cursor:pointer}}.lock{{color:#9ae7df;font-size:.9rem}}
</style>
</head>
<body>
<main>
<p class="lock">HUMAN AUTHORIZATION FIRST · CONNECTION IS NOT AUTHORITY</p>
<h1>Connect Solana MCP by Vybe</h1>
<p>OAuth will request <b>openid email mcp:read mcp:write</b>. Sleep Wealth still uses a
separate bounded human capability grant to decide what it may do after connection.</p>
<div class="scope">Provider: vybe-solana-mcp<br>Environment: mainnet-readonly<br>
Execution: disabled · Signing: disabled · Broadcast: disabled · x402: excluded</div>
<form method="post" action="/connect/vybe/start">
<label class="choice">
<input type="checkbox" checked disabled>
<span><b>Read Solana data</b><small>Allow repeated human-approved Vybe reads inside
the granted resource scope.</small></span>
</label>
<input type="hidden" name="read" value="yes">
{prepare}
<label class="choice">
<input type="checkbox" name="approve" value="yes" required>
<span><b>I authorize this capability envelope</b><small>OAuth connection alone does
not widen the grant.</small></span>
</label>
<button type="submit">Approve and continue to Vybe</button>
</form>
</main>
</body>
</html>"""


def _approved_scope(
    *,
    prepare_write: bool,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    effects = ["read"]
    actions = sorted(VYBE_READ_TOOLS)
    if prepare_write:
        effects.append("prepare-write")
        actions.extend(sorted(VYBE_PREPARE_WRITE_TOOLS))
    return tuple(actions), ("/v4/",), tuple(effects)


def _approval_fingerprint(
    *,
    actions: Sequence[str],
    resource_prefixes: Sequence[str],
    effects: Sequence[str],
) -> str:
    envelope = {
        "provider": "vybe-solana-mcp",
        "environment": "mainnet-readonly",
        "actions": list(actions),
        "resource_prefixes": list(resource_prefixes),
        "effects": list(effects),
        "oauth_scopes": list(VYBE_OAUTH_SCOPES),
        "execution_authorized": False,
        "signing_authorized": False,
        "broadcast_authorized": False,
        "payment_authorized": False,
    }
    return _sha256_text(
        json.dumps(envelope, sort_keys=True, separators=(",", ":"))
    )


def _register_client(
    config: VybeOAuthConfig,
    *,
    client: httpx.Client,
) -> str:
    if config.client_id:
        return config.client_id

    response = client.post(
        VYBE_OAUTH_REGISTRATION_URL,
        json={
            "client_name": "Sleep Wealth",
            "redirect_uris": [config.redirect_uri],
            "grant_types": ["authorization_code"],
            "response_types": ["code"],
            "token_endpoint_auth_method": "none",
        },
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    client_id = str(payload.get("client_id", "")).strip()
    if not client_id:
        raise RuntimeError("Vybe dynamic registration did not return client_id")
    return client_id


def begin_authorization(
    config: VybeOAuthConfig,
    *,
    prepare_write: bool,
    client: httpx.Client | None = None,
    now: int | None = None,
) -> tuple[str, str]:
    if prepare_write and not config.allow_prepare_write_consent:
        raise PermissionError("prepare-write consent is not enabled on this deployment")

    actions, prefixes, effects = _approved_scope(prepare_write=prepare_write)
    approval_fingerprint = _approval_fingerprint(
        actions=actions,
        resource_prefixes=prefixes,
        effects=effects,
    )
    state = secrets.token_urlsafe(32)
    verifier, challenge = _pkce_pair()
    current = int(now if now is not None else time.time())

    owns_client = client is None
    http_client = client or httpx.Client()
    try:
        client_id = _register_client(config, client=http_client)
    finally:
        if owns_client:
            http_client.close()

    preauth = {
        "schema": "sleepwealth-vybe-oauth-preauth-v1",
        "state": state,
        "code_verifier": verifier,
        "client_id": client_id,
        "source_sha": config.source_sha,
        "approval_fingerprint": approval_fingerprint,
        "actions": list(actions),
        "resource_prefixes": list(prefixes),
        "effects": list(effects),
        "issued_at": current,
        "expires_at": current + _PREAUTH_SECONDS,
    }
    sealed = _seal(preauth, config.session_secret)
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": config.redirect_uri,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "scope": " ".join(VYBE_OAUTH_SCOPES),
        "resource": VYBE_OAUTH_RESOURCE,
        "state": state,
    }
    return (
        VYBE_OAUTH_AUTHORIZATION_URL + "?" + urlencode(params),
        _cookie(_PREAUTH_COOKIE, sealed, max_age=_PREAUTH_SECONDS),
    )


def _require_preauth(
    config: VybeOAuthConfig,
    *,
    cookie_header: str | None,
    state: str,
    now: int,
) -> dict[str, object]:
    sealed = _cookie_value(cookie_header, _PREAUTH_COOKIE)
    if not sealed:
        raise ValueError("Vybe OAuth preauthorization cookie is missing")
    payload = _open(sealed, config.session_secret)
    if payload.get("schema") != "sleepwealth-vybe-oauth-preauth-v1":
        raise ValueError("Vybe OAuth preauthorization schema is invalid")
    if str(payload.get("state", "")) != state:
        raise ValueError("Vybe OAuth state does not match")
    if str(payload.get("source_sha", "")) != config.source_sha:
        raise ValueError("Vybe OAuth preauthorization is stale for this source SHA")
    if int(payload.get("expires_at", 0)) <= now:
        raise ValueError("Vybe OAuth preauthorization has expired")
    return payload


def _exchange_token(
    config: VybeOAuthConfig,
    preauth: Mapping[str, object],
    *,
    code: str,
    client: httpx.Client,
) -> dict[str, object]:
    response = client.post(
        VYBE_OAUTH_TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": config.redirect_uri,
            "client_id": str(preauth["client_id"]),
            "code_verifier": str(preauth["code_verifier"]),
            "resource": VYBE_OAUTH_RESOURCE,
        },
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Vybe token response is not an object")
    return payload


def _userinfo(access_token: str, *, client: httpx.Client) -> dict[str, object]:
    response = client.get(
        VYBE_OAUTH_USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=20.0,
    )
    response.raise_for_status()
    payload = response.json()
    if not isinstance(payload, dict):
        raise RuntimeError("Vybe userinfo response is not an object")
    return payload


def finish_authorization(
    config: VybeOAuthConfig,
    *,
    code: str,
    state: str,
    cookie_header: str | None,
    client: httpx.Client | None = None,
    now: int | None = None,
) -> tuple[dict[str, object], tuple[str, str, str]]:
    current = int(now if now is not None else time.time())
    preauth = _require_preauth(
        config,
        cookie_header=cookie_header,
        state=state,
        now=current,
    )

    owns_client = client is None
    http_client = client or httpx.Client()
    try:
        token_payload = _exchange_token(
            config,
            preauth,
            code=code,
            client=http_client,
        )
        access_token = str(token_payload.get("access_token", "")).strip()
        if not access_token:
            raise RuntimeError("Vybe token response is missing access_token")

        granted_scopes = set(
            str(token_payload.get("scope", "")).strip().split()
        )
        required_scopes = set(VYBE_OAUTH_SCOPES)
        if not required_scopes.issubset(granted_scopes):
            raise PermissionError("Vybe OAuth did not grant the required scopes")

        userinfo = _userinfo(access_token, client=http_client)
    finally:
        if owns_client:
            http_client.close()

    subject = str(userinfo.get("sub", "")).strip()
    if not subject:
        raise RuntimeError("Vybe OIDC userinfo is missing subject")

    caller_fingerprint = _sha256_text(
        f"sleepwealth-vercel:{config.source_sha}:{config.public_origin}"
    )
    subject_fingerprint = _sha256_text(f"vybe-oidc-sub:{subject}")

    expires_in = token_payload.get("expires_in", _DEFAULT_SESSION_SECONDS)
    try:
        token_seconds = int(expires_in)
    except (TypeError, ValueError):
        token_seconds = _DEFAULT_SESSION_SECONDS
    ttl = max(1, min(token_seconds, _MAX_SESSION_SECONDS))

    actions = tuple(str(v) for v in preauth.get("actions", []))
    prefixes = tuple(str(v) for v in preauth.get("resource_prefixes", []))
    effects = tuple(str(v) for v in preauth.get("effects", []))
    approval_fingerprint = str(preauth.get("approval_fingerprint", ""))

    grant = issue_human_capability_grant(
        issuer_id=config.permission_issuer,
        issuer_key=config.permission_key,
        source_sha=config.source_sha,
        caller_fingerprint=caller_fingerprint,
        subject_fingerprint=subject_fingerprint,
        provider="vybe-solana-mcp",
        environment="mainnet-readonly",
        allowed_actions=actions,
        allowed_resource_prefixes=prefixes,
        allowed_effects=effects,
        human_approval_fingerprint=approval_fingerprint,
        purpose="browser-oauth-human-approved-solana-capabilities",
        ttl_seconds=ttl,
    )

    session = {
        "schema": "sleepwealth-vybe-oauth-session-v1",
        "source_sha": config.source_sha,
        "provider": "vybe-solana-mcp",
        "environment": "mainnet-readonly",
        "access_token": access_token,
        "token_type": str(token_payload.get("token_type", "Bearer")),
        "scopes": sorted(granted_scopes),
        "client_id": str(preauth["client_id"]),
        "caller_fingerprint": caller_fingerprint,
        "subject_fingerprint": subject_fingerprint,
        "issued_at": current,
        "expires_at": current + ttl,
    }

    cookies = (
        _cookie(_PREAUTH_COOKIE, "", max_age=0),
        _cookie(
            _SESSION_COOKIE,
            _seal(session, config.session_secret),
            max_age=ttl,
        ),
        _cookie(
            _GRANT_COOKIE,
            _seal(grant, config.session_secret),
            max_age=ttl,
        ),
    )

    return (
        {
            "status": "connected",
            "provider": "vybe-solana-mcp",
            "environment": "mainnet-readonly",
            "source_sha": config.source_sha,
            "scopes": sorted(granted_scopes),
            "effects": list(effects),
            "caller_fingerprint": caller_fingerprint,
            "subject_fingerprint": subject_fingerprint,
            "human_capability_grant_id": grant["grant_id"],
            "human_capability_scope_fingerprint": grant["scope_fingerprint"],
            "access_token_exposed": False,
            "refresh_token_persisted": False,
            "signing_authorized": False,
            "broadcast_authorized": False,
            "payment_authorized": False,
            "money_moving_authorized": False,
            "execution_authorized": False,
        },
        cookies,
    )


def session_context(
    config: VybeOAuthConfig,
    *,
    cookie_header: str | None,
    now: int | None = None,
) -> tuple[dict[str, object], dict[str, object]]:
    current = int(now if now is not None else time.time())
    session_token = _cookie_value(cookie_header, _SESSION_COOKIE)
    grant_token = _cookie_value(cookie_header, _GRANT_COOKIE)
    if not session_token or not grant_token:
        raise ValueError("Vybe OAuth session is not connected")

    session = _open(session_token, config.session_secret)
    grant = _open(grant_token, config.session_secret)
    if session.get("schema") != "sleepwealth-vybe-oauth-session-v1":
        raise ValueError("Vybe OAuth session schema is invalid")
    if str(session.get("source_sha", "")) != config.source_sha:
        raise ValueError("Vybe OAuth session is stale for this source SHA")
    if int(session.get("expires_at", 0)) <= current:
        raise ValueError("Vybe OAuth session has expired")
    if str(grant.get("source_sha", "")) != config.source_sha:
        raise ValueError("Vybe capability grant is stale for this source SHA")
    return session, grant


def session_status(
    config: VybeOAuthConfig,
    *,
    cookie_header: str | None,
    now: int | None = None,
) -> dict[str, object]:
    session, grant = session_context(
        config,
        cookie_header=cookie_header,
        now=now,
    )
    return {
        "status": "connected",
        "provider": session["provider"],
        "environment": session["environment"],
        "source_sha": session["source_sha"],
        "scopes": session["scopes"],
        "effects": grant["allowed_effects"],
        "actions": grant["allowed_actions"],
        "resource_prefixes": grant["allowed_resource_prefixes"],
        "caller_fingerprint": session["caller_fingerprint"],
        "subject_fingerprint": session["subject_fingerprint"],
        "human_capability_grant_id": grant["grant_id"],
        "human_capability_scope_fingerprint": grant["scope_fingerprint"],
        "access_token_exposed": False,
        "refresh_token_persisted": False,
        "execution_authorized": False,
        "signing_authorized": False,
        "broadcast_authorized": False,
        "payment_authorized": False,
        "money_moving_authorized": False,
    }
