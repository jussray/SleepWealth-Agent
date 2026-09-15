from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Callable


_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
DEFAULT_BASE_URL = "https://sleepwealth-paper-lab.vercel.app"


def _canonical_digest(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def fetch_json(url: str) -> tuple[int, dict[str, str], dict[str, object]]:
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/json", "User-Agent": "SleepWealth-Deployment-Proof/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=20) as response:
            status = int(response.status)
            headers = {str(key).lower(): str(value) for key, value in response.headers.items()}
            payload = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"request failed for {url}: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"expected JSON object from {url}")
    return status, headers, payload


def _check(code: str, verified: bool, reason: str, *, source: str) -> dict[str, object]:
    return {
        "code": code,
        "classification": "VERIFIED" if verified else "BLOCKED",
        "blocking": True,
        "reason": reason,
        "source": source,
    }


def _boundary_safe(boundary: object) -> bool:
    if not isinstance(boundary, dict):
        return False
    false_fields = (
        "execution_authorized",
        "real_money",
        "live_execution",
        "wallet_connection",
        "funding",
        "signing",
        "brokerage_order_submission",
    )
    return (
        boundary.get("classification") == "BLOCKED"
        and boundary.get("authority") == "sandbox-simulation-only"
        and boundary.get("override_effect") == "none"
        and all(boundary.get(field) is False for field in false_fields)
    )


def verify_deployment(
    base_url: str,
    expected_sha: str,
    *,
    fetcher: Callable[[str], tuple[int, dict[str, str], dict[str, object]]] = fetch_json,
) -> dict[str, object]:
    expected_sha = expected_sha.strip().lower()
    if not _SHA_RE.fullmatch(expected_sha):
        raise ValueError("expected SHA must be exactly 40 lowercase hexadecimal characters")
    base_url = base_url.rstrip("/")
    checks: list[dict[str, object]] = []

    paper_status = None
    paper_headers: dict[str, str] = {}
    paper_payload: dict[str, object] = {}
    paper_error = None
    try:
        paper_status, paper_headers, paper_payload = fetcher(f"{base_url}/health")
    except Exception as exc:  # receipt must preserve provider/network failure separately
        paper_error = str(exc)
    checks.append(
        _check(
            "PAPER_RUNTIME_REACHABLE",
            paper_status == 200,
            "paper runtime returned HTTP 200" if paper_status == 200 else f"paper runtime unavailable: {paper_error or paper_status}",
            source=f"{base_url}/health",
        )
    )
    observed_header_sha = str(paper_headers.get("x-sleepwealth-source-sha", "")).lower()
    checks.append(
        _check(
            "PAPER_RUNTIME_EXACT_SHA",
            observed_header_sha == expected_sha,
            f"deployed header SHA matches {expected_sha}" if observed_header_sha == expected_sha else f"expected {expected_sha}; observed {observed_header_sha or 'missing'}",
            source="x-sleepwealth-source-sha",
        )
    )
    paper_safe = (
        str(paper_headers.get("x-sleepwealth-live-execution", "")).lower() == "false"
        and str(paper_headers.get("x-sleepwealth-real-money", "")).lower() == "false"
        and paper_payload.get("live_execution") is False
        and paper_payload.get("mode") == "paper"
    )
    checks.append(
        _check(
            "PAPER_RUNTIME_AUTHORITY_CEILING",
            paper_safe,
            "deployed Paper Lab remains paper-only with real-money/live execution disabled" if paper_safe else "deployed Paper Lab safety markers are incomplete or widened",
            source=f"{base_url}/health",
        )
    )

    pump_status = None
    pump_payload: dict[str, object] = {}
    pump_error = None
    try:
        pump_status, _, pump_payload = fetcher(f"{base_url}/pump-live-box/health")
    except Exception as exc:
        pump_error = str(exc)
    checks.append(
        _check(
            "PUMP_RUNTIME_REACHABLE",
            pump_status == 200,
            "Pump namespace returned HTTP 200" if pump_status == 200 else f"Pump namespace unavailable: {pump_error or pump_status}",
            source=f"{base_url}/pump-live-box/health",
        )
    )
    runtime_identity = pump_payload.get("runtime_identity")
    pump_identity_ok = (
        isinstance(runtime_identity, dict)
        and runtime_identity.get("source_sha") == expected_sha
        and runtime_identity.get("exact_source_known") is True
        and runtime_identity.get("execution_authorized") is False
    )
    observed_pump_sha = runtime_identity.get("source_sha") if isinstance(runtime_identity, dict) else None
    checks.append(
        _check(
            "PUMP_RUNTIME_EXACT_SHA",
            pump_identity_ok,
            f"Pump runtime identity matches {expected_sha}" if pump_identity_ok else f"expected {expected_sha}; observed {observed_pump_sha or 'missing/unproved'}",
            source=f"{base_url}/pump-live-box/health#runtime_identity",
        )
    )
    inline_boundary = pump_payload.get("money_boundary")
    checks.append(
        _check(
            "PUMP_INLINE_MONEY_BOUNDARY",
            _boundary_safe(inline_boundary),
            "Pump health exposes a fail-closed sandbox-only money boundary" if _boundary_safe(inline_boundary) else "Pump health money boundary is missing or not fail-closed",
            source=f"{base_url}/pump-live-box/health#money_boundary",
        )
    )

    boundary_status = None
    boundary_payload: dict[str, object] = {}
    boundary_error = None
    try:
        boundary_status, _, boundary_payload = fetcher(
            f"{base_url}/pump-live-box/api/money-boundary"
        )
    except Exception as exc:
        boundary_error = str(exc)
    boundary_ok = boundary_status == 200 and _boundary_safe(boundary_payload)
    checks.append(
        _check(
            "PUMP_MONEY_BOUNDARY_ENDPOINT",
            boundary_ok,
            "namespaced money-boundary endpoint is reachable and fail-closed" if boundary_ok else f"money-boundary endpoint unproved: {boundary_error or boundary_status or 'unsafe payload'}",
            source=f"{base_url}/pump-live-box/api/money-boundary",
        )
    )

    payload: dict[str, object] = {
        "schema": "sleepwealth-vercel-deployed-runtime-v1",
        "base_url": base_url,
        "expected_source_sha": expected_sha,
        "classification": "VERIFIED"
        if all(check["classification"] == "VERIFIED" for check in checks)
        else "BLOCKED",
        "checks": checks,
        "execution_authorized": False,
        "real_money": False,
        "live_execution": False,
        "truth": (
            "This receipt proves deployed identity and sandbox authority markers only. "
            "It cannot grant, renew, or expand trading, wallet, funding, signing, transfer, or real-money authority."
        ),
    }
    payload["fingerprint"] = f"vercel-deployed-runtime-v1:{_canonical_digest(payload)}"
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify canonical Sleep Wealth Vercel runtime truth")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--output")
    args = parser.parse_args()

    receipt = verify_deployment(args.base_url, args.expected_sha)
    rendered = json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    print(rendered, end="")
    if args.output:
        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
    return 0 if receipt["classification"] == "VERIFIED" else 1


if __name__ == "__main__":
    sys.exit(main())
