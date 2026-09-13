"""Vercel entry point for the Pump public-evidence practice sandbox."""

from urllib.parse import parse_qsl, urlencode, urlparse

from backend.pump_live_sandbox import (
    PumpEvidenceSandboxHandler,
    PumpEvidenceSandboxSession,
)


_SESSION = PumpEvidenceSandboxSession(initial_cash=100.0)


class handler(PumpEvidenceSandboxHandler):
    """Serve the practice-only Pump evidence sandbox on Vercel."""

    @property
    def session(self) -> PumpEvidenceSandboxSession:
        return _SESSION

    def _restore_sandbox_path(self) -> None:
        parsed = urlparse(self.path)
        original_path = None
        remaining_query = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            if key == "__sw_sandbox_path" and original_path is None:
                original_path = value
            else:
                remaining_query.append((key, value))
        if original_path is None:
            return
        path = "/" + original_path.lstrip("/")
        query = urlencode(remaining_query, doseq=True)
        self.path = f"{path}?{query}" if query else path

    def do_GET(self):
        self._restore_sandbox_path()
        return super().do_GET()

    def do_POST(self):
        self._restore_sandbox_path()
        return super().do_POST()
