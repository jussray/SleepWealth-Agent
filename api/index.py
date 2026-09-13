"""Vercel entry point for Sleep Wealth paper and sandbox-only public surfaces."""

import asyncio
import json
import os
from http import HTTPStatus
from urllib.parse import parse_qsl, urlencode, urlparse

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
from backend.pump_live_box_server import HTML as PUMP_LIVE_BOX_HTML
from backend.pump_live_box_server import PumpLiveBoxSession
from backend.server import SleepWealthHandler


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


class handler(SleepWealthHandler):
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

    def _serve_pump_get(self, relative_path: str) -> None:
        if relative_path == "":
            return self._redirect(_PUMP_LIVE_BOX_PREFIX + "/")
        if relative_path == "/":
            return self._send_html(_PUMP_LIVE_BOX_HTML)
        if relative_path == "/health":
            return self._send_json(
                {
                    "status": "ok",
                    "pump_network_access": "none",
                    "evidence_authority": "none",
                    "authority": "sandbox-simulation-only",
                    "real_money": False,
                    "live_execution": False,
                    "state_scope": os.environ["SLEEPWEALTH_APPROVAL_STATE_SCOPE"],
                }
            )
        if relative_path == "/api/wallet":
            return self._send_json(asyncio.run(_PUMP_LIVE_BOX_SESSION.wallet()))
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
            return self._serve_pump_get(pump_path)
        asset = mom8_asset_response(parsed.path)
        if asset is not None:
            content_type, body = asset
            return self._send_mom8_asset(content_type, body)
        return super().do_GET()

    def do_POST(self):
        self._restore_sleepwealth_path()
        parsed = urlparse(self.path)
        pump_path = pump_live_box_relative_path(parsed.path)
        if pump_path is not None:
            return self._serve_pump_post(pump_path)
        return super().do_POST()
