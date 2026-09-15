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

capital_cycles = [
    {"buy_cost": 4.0, "sale_proceeds": 6.0, "fees": 0.5, "days_held": 3},
    {"buy_cost": 4.0, "sale_proceeds": 6.0, "fees": 0.5, "days_held": 3},
    {"buy_cost": 4.0, "sale_proceeds": 6.0, "fees": 0.5, "days_held": 3},
]

with sync_playwright() as p:
    request = p.request.new_context(base_url=BASE_URL)
    try:
        response = request.get("/health")
        assert response.ok
        payload = response.json()

        paper_response = request.post(
            "/api/stock/dry-run",
            data={"symbol": "AAPL", "qty": 0.01, "side": "buy"},
        )
        assert paper_response.ok
        paper_payload = paper_response.json()

        capital_response = request.post(
            "/api/capital/truth",
            data={"cycles": capital_cycles},
        )
        assert capital_response.ok
        capital_payload = capital_response.json()
    finally:
        request.dispose()

identity = payload["runtime_identity"]
assert payload["status"] == "ok"
assert payload["mode"] == "paper"
assert payload["broker"] == "mock"
assert payload["market_observation"] == "read-only"
assert payload["live_execution"] is False
assert payload["truth_decision_loop"] == "sleepwealth/truth-decision-loop@v1"
assert identity["exact_source_known"] is True
assert identity["source_sha"] == EXPECTED_SHA.lower()
assert identity["execution_authorized"] is False

paper_truth = paper_payload["truthmode"]
assert paper_payload["status"] == "executed"
assert paper_payload["live_execution"] is False
assert paper_truth["schema"] == "sleepwealth/truth-decision-loop@v1"
assert paper_truth["authority"] == "decision_support_only"
assert paper_truth["authorizes"] is False
assert paper_truth["truth_planes"]["source"]["state"] == "OBSERVED"
assert paper_truth["truth_planes"]["execution"]["state"] == "VERIFIED"
assert paper_truth["truth_planes"]["outcome"]["state"] == "VERIFIED"
assert paper_truth["decision"] == "MEASURE"
assert paper_truth["continuity_cookie"].startswith("sw-truth-cookie-v1:")

capital = capital_payload["capital_ladder"]
capital_truth = capital["truthmode"]
assert capital_payload["mode"] == "paper"
assert capital_payload["live_execution"] is False
assert capital["promotion_ready"] is True
assert capital_truth["schema"] == "sleepwealth/truth-decision-loop@v1"
assert capital_truth["authority"] == "decision_support_only"
assert capital_truth["authorizes"] is False
assert capital_truth["fresh"] is True
assert capital_truth["truth_planes"]["source"]["state"] == "VERIFIED"
assert capital_truth["truth_planes"]["execution"]["state"] == "OBSERVED"
assert capital_truth["truth_planes"]["outcome"]["state"] == "VERIFIED"
assert capital_truth["decision"] == "PROPOSE_PROMOTION_REVIEW"
assert "automatic promotion" in capital_truth["does_not_prove"]

receipt = {
    "schema": "sleepwealth-runtime-identity-proof-v2",
    "expected_source_sha": EXPECTED_SHA.lower(),
    "observed_source_sha": identity["source_sha"],
    "exact_match": identity["source_sha"] == EXPECTED_SHA.lower(),
    "runtime_identity": identity,
    "runtime_safety": {
        "mode": payload["mode"],
        "broker": payload["broker"],
        "market_observation": payload["market_observation"],
        "live_execution": payload["live_execution"],
        "truth_decision_loop": payload["truth_decision_loop"],
    },
    "paper_cycle_truth": paper_truth,
    "capital_truth": capital_truth,
    "execution_authorized": False,
    "truth": (
        "This Playwright receipt proves exact runtime/source identity plus the "
        "paper-only TruthMode decision receipts. It does not prove or grant "
        "live-money execution authority."
    ),
}

(ARTIFACT_DIR / "runtime-identity-proof.json").write_text(
    json.dumps(receipt, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
