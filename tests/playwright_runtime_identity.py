import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright

BASE_URL = os.getenv("SLEEPWEALTH_BASE_URL", "http://127.0.0.1:8765")
EXPECTED_SHA = os.getenv("SLEEPWEALTH_PROOF_SOURCE_SHA", "")
ARTIFACT_DIR = Path(os.getenv("SLEEPWEALTH_ARTIFACT_DIR", "artifacts"))
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)

assert len(EXPECTED_SHA) == 40
assert all(char in "0123456789abcdef" for char in EXPECTED_SHA.lower())

with sync_playwright() as p:
    request = p.request.new_context(base_url=BASE_URL)
    try:
        response = request.get("/health")
        assert response.ok
        payload = response.json()
    finally:
        request.dispose()

identity = payload["runtime_identity"]
assert payload["status"] == "ok"
assert payload["mode"] == "paper"
assert payload["broker"] == "mock"
assert payload["market_observation"] == "read-only"
assert payload["live_execution"] is False
assert identity["exact_source_known"] is True
assert identity["source_sha"] == EXPECTED_SHA.lower()
assert identity["execution_authorized"] is False

receipt = {
    "schema": "sleepwealth-runtime-identity-proof-v1",
    "expected_source_sha": EXPECTED_SHA.lower(),
    "observed_source_sha": identity["source_sha"],
    "exact_match": identity["source_sha"] == EXPECTED_SHA.lower(),
    "runtime_identity": identity,
    "runtime_safety": {
        "mode": payload["mode"],
        "broker": payload["broker"],
        "market_observation": payload["market_observation"],
        "live_execution": payload["live_execution"],
    },
    "execution_authorized": False,
    "truth": (
        "This Playwright receipt proves runtime/source identity for the paper lab only. "
        "It does not prove or grant live-money execution authority."
    ),
}

(ARTIFACT_DIR / "runtime-identity-proof.json").write_text(
    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
