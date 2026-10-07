"""Vercel entry point for Sleep Wealth paper and sandbox-only public surfaces."""

import asyncio
import json
import os

import httpx
from http import HTTPStatus
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse

# Vercel functions may write only to temporary storage. These receipts remain
# paper-simulation evidence and do not create persistent trading or account
# authority. Approval state survives requests inside one warm function instance,
# but /tmp is not claimed to survive a cold start, redeploy, or instance change.
os.environ.setdefault("SLEEPWEALTH_AUDIT_LOG", "/tmp/sleepwealth-audit.log")
os.environ.setdefault(
    "SLEEPWEALTH_APPROVAL_STATE", "/tmp/sleepwealth-paper-approvals.json"
)
os.environ.setdefault("SLEEPWEALTH_APPROVAL_STATE_SCOPE", "vercel-instance-ephemeral")

from api.mom8_assets import mom8_asset_response
from backend.practice_state_store import practice_state_identity
from backend.pump_live_box_server import HTML as PUMP_LIVE_BOX_HTML
from backend.pump_live_box_server import PumpLiveBoxSession
from backend.runtime_identity import runtime_identity
from backend.runtime_server import RuntimeIdentityHandler
from backend.vybe_oauth import (
    begin_authorization,
    clear_oauth_cookies,
    config_from_env,
    consent_html,
    finish_authorization,
    session_context,
    session_status,
)
from backend.vybe_proof import deployed_vybe_proof


_PUMP_LIVE_BOX_PREFIX = "/pump-live-box"
_PUMP_LIVE_BOX_HTML = PUMP_LIVE_BOX_HTML.replace("fetch('/api/", "fetch('api/")
_PUMP_LIVE_BOX_SESSION = PumpLiveBoxSession(
    float(os.getenv("SLEEPWEALTH_CRYPTO_SANDBOX_CASH", "100"))
)


def pump_live_box_relative_path(path: str) -> str | None:
    """Return the Pump Live Box subpath without widening the main API namespace."""
    if path == _PUMP_LIVE_BOX_PREFIX:
        return ""
    if path.startswith(_PUMP_LIVE_BOX_PREFIX + "/"):
        return path[len(_PUMP_LIVE_BOX_PREFIX) :] or "/"
    return None


def pump_live_box_health_payload() -> dict[str, object]:
    """Expose non-authorizing deployed identity and money-boundary evidence."""
    state_store = _PUMP_LIVE_BOX_SESSION.receipts.state_store
    return {
        "status": "ok",
        "pump_network_access": "none",
        "evidence_authority": "none",
        "authority": "sandbox-simulation-only",
        "real_money": False,
        "live_execution": False,
        "state_scope": os.environ["SLEEPWEALTH_APPROVAL_STATE_SCOPE"],
        "practice_state_transport": state_store.kind if state_store is not None else "none",
        "durable_state_required": state_store is not None,
        "runtime_identity": runtime_identity(),
        "money_boundary": _PUMP_LIVE_BOX_SESSION.boundary(),
    }


class handler(RuntimeIdentityHandler):
    """Serve SleepWealth, MOM8 preview, and sandbox-only Pump Live Box on Vercel."""

    def _restore_sleepwealth_path(self) -> None:
        parsed = urlparse(self.path)
        original_path = None
        remaining_query = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key == "__sw_path" and original_path is None:
                original_path = value
            else:
                remaining_query.append((key, value))
        if original_path is None:
            return
        path = "/" + original_path.lstrip("/")
        query = urlencode(remaining_query, doseq=True)
        self.path = f"{path}?{query}" if query else path

    def _send_mom8_asset(self, content_type: str, body: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "public, max-age=300")
        self.send_header("X-MOM8-Authority", "brand-preview-only")
        self.end_headers()
        self.wfile.write(body)

    def _redirect(self, location: str) -> None:
        self.send_response(HTTPStatus.PERMANENT_REDIRECT)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.end_headers()

    def _read_json_object(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        payload = json.loads(raw.decode())
        if not isinstance(payload, dict):
            raise TypeError("request body must be a JSON object")
        return payload

    def _request_origin(self) -> str:
        proto = str(self.headers.get("x-forwarded-proto") or "https").split(",")[0].strip()
        host = str(
            self.headers.get("x-forwarded-host")
            or self.headers.get("host")
            or ""
        ).split(",")[0].strip()
        if not host:
            raise ValueError("request host is required")
        return f"{proto}://{host}".rstrip("/")

    def _read_form_object(self) -> dict[str, list[str]]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b""
        return parse_qs(raw.decode("utf-8"), keep_blank_values=True)

    def _temporary_redirect(
        self,
        location: str,
        *,
        cookies: tuple[str, ...] = (),
    ) -> None:
        self.send_response(HTTPStatus.SEE_OTHER)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        for cookie in cookies:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def _send_oauth_html(self, html: str, *, status=HTTPStatus.OK) -> None:
        body = html.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.end_headers()
        self.wfile.write(body)

    def _oauth_config(self):
        return config_from_env(self._request_origin())

    def _serve_pump_get(self, relative_path: str) -> None:
        if relative_path == "":
            return self._redirect(_PUMP_LIVE_BOX_PREFIX + "/")
        if relative_path == "/":
            return self._send_html(_PUMP_LIVE_BOX_HTML)
        if relative_path == "/health":
            return self._send_json(pump_live_box_health_payload())
        if relative_path == "/api/wallet":
            try:
                return self._send_json(asyncio.run(_PUMP_LIVE_BOX_SESSION.wallet()))
            except (RuntimeError, PermissionError, ValueError) as exc:
                return self._send_json(
                    {
                        "status": "blocked",
                        "reason": str(exc),
                        "real_money": False,
                        "live_execution": False,
                    },
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )
        if relative_path == "/api/money-boundary":
            return self._send_json(_PUMP_LIVE_BOX_SESSION.boundary())
        return self._send_json(
            {"status": "not_found", "real_money": False, "live_execution": False},
            HTTPStatus.NOT_FOUND,
        )

    def _serve_pump_post(self, relative_path: str) -> None:
        try:
            payload = self._read_json_object()
            if relative_path == "/api/proposals":
                result = asyncio.run(
                    _PUMP_LIVE_BOX_SESSION.propose(
                        payload.get("evidence", {}),
                        payload.get("qty", 10),
                        payload.get("side", "buy"),
                    )
                )
                return self._send_json(
                    result,
                    HTTPStatus.CREATED
                    if result.get("status") == "pending"
                    else HTTPStatus.OK,
                )
            if relative_path.startswith("/api/proposals/") and relative_path.endswith(
                "/approve"
            ):
                proposal_id = (
                    relative_path.removeprefix("/api/proposals/")
                    .removesuffix("/approve")
                    .strip("/")
                )
                return self._send_json(
                    asyncio.run(_PUMP_LIVE_BOX_SESSION.approve(proposal_id))
                )
        except (
            UnicodeDecodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
            RuntimeError,
            PermissionError,
        ) as exc:
            return self._send_json(
                {
                    "status": "invalid",
                    "reason": str(exc),
                    "real_money": False,
                    "live_execution": False,
                },
                HTTPStatus.BAD_REQUEST,
            )
        return self._send_json(
            {"status": "not_found", "real_money": False, "live_execution": False},
            HTTPStatus.NOT_FOUND,
        )

    def do_GET(self):
        self._restore_sleepwealth_path()
        parsed = urlparse(self.path)
        pump_path = pump_live_box_relative_path(parsed.path)
        if pump_path is not None:
            with practice_state_identity(self.headers.get("x-vercel-oidc-token")):
                return self._serve_pump_get(pump_path)
        if parsed.path == "/connect/vybe":
            try:
                return self._send_oauth_html(consent_html(self._oauth_config()))
            except (RuntimeError, ValueError) as exc:
                return self._send_json(
                    {
                        "status": "blocked",
                        "classification": "VYBE_OAUTH_NOT_CONFIGURED",
                        "reason": str(exc),
                        "provider": "vybe-solana-mcp",
                        "execution_authorized": False,
                    },
                    HTTPStatus.SERVICE_UNAVAILABLE,
                )

        if parsed.path == "/connect/vybe/callback":
            query = parse_qs(parsed.query, keep_blank_values=True)
            if query.get("error"):
                return self._send_json(
                    {
                        "status": "blocked",
                        "classification": "VYBE_OAUTH_DENIED",
                        "reason": str(query.get("error_description", query["error"])[0]),
                        "provider": "vybe-solana-mcp",
                        "execution_authorized": False,
                    },
                    HTTPStatus.BAD_REQUEST,
                )
            try:
                code = str(query.get("code", [""])[0]).strip()
                state = str(query.get("state", [""])[0]).strip()
                if not code or not state:
                    raise ValueError("OAuth callback requires code and state")
                payload, cookies = finish_authorization(
                    self._oauth_config(),
                    code=code,
                    state=state,
                    cookie_header=self.headers.get("cookie"),
                )
                if payload.get("access_token_exposed") is not False:
                    raise RuntimeError("OAuth callback attempted to expose token material")
                return self._temporary_redirect(
                    "/connect/vybe/status",
                    cookies=cookies,
                )
            except (httpx.HTTPError, PermissionError, RuntimeError, ValueError) as exc:
                return self._send_json(
                    {
                        "status": "blocked",
                        "classification": "VYBE_OAUTH_CALLBACK_BLOCKED",
                        "reason": f"{type(exc).__name__}: {exc}",
                        "provider": "vybe-solana-mcp",
                        "execution_authorized": False,
                    },
                    HTTPStatus.BAD_REQUEST,
                )

        if parsed.path == "/connect/vybe/status":
            try:
                return self._send_json(
                    session_status(
                        self._oauth_config(),
                        cookie_header=self.headers.get("cookie"),
                    )
                )
            except (RuntimeError, ValueError) as exc:
                return self._send_json(
                    {
                        "status": "disconnected",
                        "classification": "VYBE_OAUTH_SESSION_UNAVAILABLE",
                        "reason": str(exc),
                        "provider": "vybe-solana-mcp",
                        "execution_authorized": False,
                    },
                    HTTPStatus.UNAUTHORIZED,
                )

        if parsed.path == "/connect/vybe/proof":
            try:
                config = self._oauth_config()
                session, grant = session_context(
                    config,
                    cookie_header=self.headers.get("cookie"),
                )
                token = str(session.get("access_token", ""))
                status, payload = asyncio.run(
                    deployed_vybe_proof(
                        bearer_token=token,
                        human_permission_grant=grant,
                        allow_session_production=True,
                    )
                )
                return self._send_json(payload, status)
            except (RuntimeError, ValueError) as exc:
                return self._send_json(
                    {
                        "status": "blocked",
                        "classification": "VYBE_OAUTH_PROOF_BLOCKED",
                        "reason": str(exc),
                        "provider": "vybe-solana-mcp",
                        "raw_market_data_exposed": False,
                        "execution_authorized": False,
                    },
                    HTTPStatus.UNAUTHORIZED,
                )

        if parsed.path == "/internal/vybe-proof":
            try:
                status, payload = asyncio.run(deployed_vybe_proof())
            except (RuntimeError, ValueError) as exc:
                status, payload = (
                    HTTPStatus.SERVICE_UNAVAILABLE,
                    {
                        "status": "blocked",
                        "classification": "VYBE_PROOF_ERROR",
                        "reason": f"{type(exc).__name__}: {exc}",
                        "provider": "vybe-solana-mcp",
                        "authorizes": False,
                        "allocation_authorized": False,
                        "execution_authorized": False,
                        "money_moving": False,
                        "raw_market_data_exposed": False,
                    },
                )
            return self._send_json(payload, status)

        asset = mom8_asset_response(parsed.path)
        if asset is not None:
            content_type, body = asset
            return self._send_mom8_asset(content_type, body)
        return super().do_GET()

    def do_POST(self):
        self._restore_sleepwealth_path()
        parsed = urlparse(self.path)

        if parsed.path == "/connect/vybe/start":
            try:
                config = self._oauth_config()
                origin = str(self.headers.get("origin") or "").rstrip("/")
                if origin != config.public_origin:
                    raise PermissionError("OAuth consent POST origin is not trusted")
                form = self._read_form_object()
                if "yes" not in form.get("approve", []):
                    raise PermissionError("explicit human capability approval is required")
                prepare_write = "yes" in form.get("prepare_write", [])
                location, preauth_cookie = begin_authorization(
                    config,
                    prepare_write=prepare_write,
                )
                return self._temporary_redirect(
                    location,
                    cookies=(preauth_cookie,),
                )
            except (
                httpx.HTTPError,
                PermissionError,
                RuntimeError,
                UnicodeDecodeError,
                ValueError,
            ) as exc:
                return self._send_json(
                    {
                        "status": "blocked",
                        "classification": "VYBE_OAUTH_START_BLOCKED",
                        "reason": f"{type(exc).__name__}: {exc}",
                        "provider": "vybe-solana-mcp",
                        "execution_authorized": False,
                    },
                    HTTPStatus.BAD_REQUEST,
                )

        if parsed.path == "/connect/vybe/logout":
            return self._temporary_redirect(
                "/connect/vybe",
                cookies=clear_oauth_cookies(),
            )

        pump_path = pump_live_box_relative_path(parsed.path)
        if pump_path is not None:
            with practice_state_identity(self.headers.get("x-vercel-oidc-token")):
                return self._serve_pump_post(pump_path)
        return super().do_POST()
