"""Vercel entry point for the Sleep Wealth paper-only dashboard."""

import os
from urllib.parse import parse_qsl, urlencode, urlparse

# Vercel functions may write only to temporary storage. These audit receipts remain
# paper-simulation evidence and do not create persistent trading or account authority.
os.environ.setdefault("SLEEPWEALTH_AUDIT_LOG", "/tmp/sleepwealth-audit.log")

from backend.server import SleepWealthHandler


class handler(SleepWealthHandler):
    """Serve the existing paper-only handler through Vercel's catch-all route."""

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

    def do_GET(self):
        self._restore_sleepwealth_path()
        return super().do_GET()

    def do_POST(self):
        self._restore_sleepwealth_path()
        return super().do_POST()
