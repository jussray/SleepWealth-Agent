from __future__ import annotations

import argparse
import os
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from backend.runtime_identity import runtime_identity
from backend.server import SleepWealthHandler
from rules import load_rules


def health_payload() -> dict[str, object]:
    rules = load_rules()
    return {
        "status": "ok",
        "mode": "paper",
        "broker": "mock",
        "market_source": os.getenv("SLEEPWEALTH_MARKET_SOURCE", "yahoo-public"),
        "lanes": rules.get("lanes", {}),
        "market_observation": "read-only",
        "external_crypto_sources": "observation-only",
        "live_execution": False,
        "runtime_identity": runtime_identity(),
    }


class RuntimeIdentityHandler(SleepWealthHandler):
    server_version = "SleepWealthPaperRuntime/1.0"

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            return self._send_json(health_payload())
        return super().do_GET()


def serve(host: str = "127.0.0.1", port: int = 8765) -> None:
    Path(os.getenv("SLEEPWEALTH_AUDIT_LOG", "audit.log")).parent.mkdir(parents=True, exist_ok=True)
    server = ThreadingHTTPServer((host, port), RuntimeIdentityHandler)
    identity = runtime_identity()
    print(f"Sleep Wealth paper backend listening on http://{host}:{port}")
    print(
        "Runtime identity: "
        f"source_sha={identity['source_sha'] or 'unknown'} "
        f"provider={identity['source_provider']} "
        f"known={identity['exact_source_known']} | live execution=disabled | broker=mock"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Sleep Wealth paper runtime identity server")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    serve(args.host, args.port)


if __name__ == "__main__":
    main()
