from __future__ import annotations

import argparse
import os
from http import HTTPStatus
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from backend.runtime_identity import runtime_identity
from backend.server import SleepWealthHandler
from engine.capital_ladder import CapitalLadder, FlipCycle
from engine.truth_mode import (
    TRUTH_DECISION_CONTRACT,
    build_capital_truth_receipt,
    build_paper_cycle_truth_receipt,
)
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
        "truth_decision_loop": TRUTH_DECISION_CONTRACT,
        "runtime_identity": runtime_identity(),
    }


def _cycle_evidence(cycle: FlipCycle) -> dict[str, object]:
    return {
        "buy_cost": float(cycle.buy_cost),
        "sale_proceeds": float(cycle.sale_proceeds),
        "fees": float(cycle.fees),
        "other_costs": float(cycle.other_costs),
        "days_held": cycle.days_held,
    }


def capital_truth_payload(payload: dict[str, object]) -> dict[str, object]:
    """Recompute paper compounding truth from caller-supplied cycle evidence."""

    raw_cycles = payload.get("cycles")
    if not isinstance(raw_cycles, list):
        raise ValueError("cycles must be a JSON list")

    cycles: list[FlipCycle] = []
    for item in raw_cycles:
        if not isinstance(item, dict):
            raise ValueError("every cycle must be a JSON object")
        cycles.append(FlipCycle(**item))

    rules = load_rules()
    history = CapitalLadder(rules).assess_history(cycles)
    current_fingerprint = payload.get("current_fingerprint")
    if current_fingerprint is not None and not isinstance(current_fingerprint, str):
        raise ValueError("current_fingerprint must be a string when supplied")

    history["truthmode"] = build_capital_truth_receipt(
        history,
        [_cycle_evidence(cycle) for cycle in cycles],
        rules,
        current_fingerprint=current_fingerprint,
    )
    return {
        "status": "ok",
        "mode": "paper",
        "broker": "mock",
        "live_execution": False,
        "capital_ladder": history,
    }


class RuntimeIdentityHandler(SleepWealthHandler):
    server_version = "SleepWealthPaperRuntime/1.1"

    def _send_json(self, payload, status=HTTPStatus.OK):
        if (
            isinstance(payload, dict)
            and "truthmode" not in payload
            and payload.get("mode") == "paper"
            and payload.get("status") in {"executed", "blocked"}
            and isinstance(payload.get("continuity"), dict)
            and payload.get("lane") in {"stock-market", "crypto"}
        ):
            payload = {
                **payload,
                "truthmode": build_paper_cycle_truth_receipt(payload),
            }
        return super()._send_json(payload, status)

    def do_GET(self):
        if urlparse(self.path).path == "/health":
            return self._send_json(health_payload())
        return super().do_GET()

    def do_POST(self):
        if urlparse(self.path).path == "/api/capital/truth":
            try:
                return self._send_json(capital_truth_payload(self._read_json_object()))
            except (TypeError, ValueError) as exc:
                return self._send_json(
                    {
                        "status": "blocked",
                        "mode": "paper",
                        "broker": "mock",
                        "live_execution": False,
                        "reason": str(exc),
                    },
                    HTTPStatus.BAD_REQUEST,
                )
        return super().do_POST()


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
