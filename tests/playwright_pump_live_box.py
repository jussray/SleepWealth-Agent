import json
import os
from pathlib import Path
import subprocess
import sys
import time
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

BASE_URL = os.getenv("PUMP_LIVE_BOX_BASE_URL", "http://127.0.0.1:8768/")
SOURCE_SHA = os.getenv("SLEEPWEALTH_PROOF_SOURCE_SHA", "unknown")
ARTIFACT_DIR = Path("artifacts")


def wait_for_health():
    for _ in range(40):
        try:
            with urlopen(BASE_URL.rstrip("/") + "/health", timeout=1) as response:  # nosec B310
                data = json.loads(response.read().decode())
            if data["status"] == "ok":
                assert data["pump_network_access"] == "none"
                assert data["evidence_authority"] == "none"
                assert data["practice_graduation"] == "review-only"
                assert data["real_money"] is False
                assert data["live_execution"] is False
                return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("Pump Live Box failed health check")


def start_server(env):
    server = subprocess.Popen(
        [sys.executable, "-m", "backend.pump_live_box_server", "--host", "127.0.0.1", "--port", "8768"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    wait_for_health()
    return server


def stop_server(server):
    if server is None or server.poll() is not None:
        return
    server.terminate()
    try:
        server.wait(timeout=5)
    except subprocess.TimeoutExpired:
        server.kill()
        server.wait(timeout=5)


def pump_evidence(price):
    return {
        "source_url": "https://pump.fun/coin/TEST-OBSERVATION",
        "symbol": "TEST",
        "mint": "TEST-DEMO-MINT",
        "price": price,
        "observed_at": "2026-09-13T23:05:00Z",
    }


def main():
    ARTIFACT_DIR.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["SLEEPWEALTH_APPROVAL_STATE"] = "/tmp/pump-live-box-approvals.json"
    env["SLEEPWEALTH_PUMP_AUDIT_LOG"] = "/tmp/pump-live-box-audit.jsonl"
    env["SLEEPWEALTH_PUMP_PRACTICE_STATE"] = "/tmp/pump-live-box-practice-state.json"
    env["SLEEPWEALTH_PUMP_MIN_PRACTICE_EXECUTIONS"] = "2"
    env["SLEEPWEALTH_PUMP_MIN_PRACTICE_ROUND_TRIPS"] = "1"
    Path(env["SLEEPWEALTH_APPROVAL_STATE"]).unlink(missing_ok=True)
    Path(env["SLEEPWEALTH_PUMP_AUDIT_LOG"]).unlink(missing_ok=True)
    Path(env["SLEEPWEALTH_PUMP_PRACTICE_STATE"]).unlink(missing_ok=True)
    server = start_server(env)
    try:
        proof = {"source_sha": SOURCE_SHA, "surface": "pump-live-box", "checks": [], "real_money": False, "live_execution": False}
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            response = page.goto(BASE_URL, wait_until="networkidle")
            assert response and response.ok
            assert page.get_by_role("heading", name="Evidence in. Authority stays out.").is_visible()
            assert page.get_by_text("PUBLIC EVIDENCE · READ-ONLY").is_visible()
            assert page.get_by_text("SIMULATED EXECUTION ONLY").is_visible()
            identity_text = page.locator(".identity").inner_text()
            assert "MOM8" in identity_text
            assert "External contracts are observation targets only" in identity_text
            assert page.locator("#symbol").input_value() == "TEST"
            assert page.locator("#mint").input_value() == "TEST-DEMO-MINT"
            proof["checks"].append("mom8_identity_separate_from_local_test_fixture")
            assert page.locator("#cash").inner_text() == "$100.00"
            assert page.locator("#equity").inner_text() == "$100.00"
            assert page.locator("#pnl").inner_text() == "+$0.00"
            page.wait_for_function("() => document.querySelector('#practice-samples').textContent === '0 / 2'")
            assert page.locator("#graduation").inner_text() == "PRACTICE_REQUIRED"
            initial_graduation = page.request.get(BASE_URL.rstrip("/") + "/api/graduation").json()
            assert initial_graduation["review_ready"] is False
            assert initial_graduation["live_review_ready"] is False
            assert initial_graduation["platform_eligibility_verified"] is False
            assert initial_graduation["execution_authorized"] is False
            assert initial_graduation["money_movement_capability"] is False
            proof["checks"].append("practice_gate_starts_fail_closed")

            stale_response = page.request.post(
                BASE_URL.rstrip("/") + "/api/proposals",
                data={"evidence": pump_evidence(0.5), "qty": 10, "side": "buy"},
            )
            assert stale_response.ok
            stale = stale_response.json()
            current_response = page.request.post(
                BASE_URL.rstrip("/") + "/api/proposals",
                data={"evidence": pump_evidence(0.75), "qty": 10, "side": "buy"},
            )
            assert current_response.ok
            current = current_response.json()
            assert stale["proposal_id"] != current["proposal_id"]
            stale_approval = page.request.post(
                BASE_URL.rstrip("/") + f"/api/proposals/{stale['proposal_id']}/approve",
                data={},
            )
            assert stale_approval.ok
            stale_block = stale_approval.json()
            assert stale_block["status"] == "blocked"
            assert stale_block["stale_evidence"] is True
            assert stale_block["bound_price"] == 0.5
            assert stale_block["current_price"] == 0.75
            assert stale_block["real_money"] is False
            assert stale_block["live_execution"] is False
            wallet_after_stale = page.request.get(BASE_URL.rstrip("/") + "/api/wallet").json()
            assert wallet_after_stale["cash"] == 100.0
            proof["checks"].append("stale_proposal_blocked_on_price_drift")

            page.locator("#observed-at").fill("2026-09-13T23:05:00Z")
            page.get_by_role("button", name="1 · Bind evidence + propose").click()
            page.wait_for_function("() => document.querySelector('#result').textContent.includes('\\\"status\\\": \\\"pending\\\"')")
            bound = json.loads(page.locator("#result").inner_text())
            assert bound["evidence"]["authority"] == "none"
            assert bound["evidence"]["read_only"] is True
            assert bound["real_money"] is False
            assert bound["live_execution"] is False
            assert len(bound["evidence"]["fingerprint"]) == 64
            assert len(bound["proposal_fingerprint"]) == 64
            assert page.locator("#cash").inner_text() == "$100.00"
            proof["checks"].append("public_evidence_bound_non_mutating")
            proof["observation_fingerprint"] = bound["evidence"]["fingerprint"]
            proof["proposal_fingerprint"] = bound["proposal_fingerprint"]

            page.get_by_role("button", name="2 · Approve + simulate").click()
            page.wait_for_function("() => document.querySelector('#result').textContent.includes('\\\"status\\\": \\\"executed\\\"')")
            executed = json.loads(page.locator("#result").inner_text())
            assert executed["pump_observation_fingerprint"] == bound["evidence"]["fingerprint"]
            assert executed["execution"]["real_money"] is False
            assert executed["execution"]["wallet_mode"] == "sandbox"
            assert executed["receipt"]["classification"] == "SIMULATED_EXECUTION_RECEIPT"
            assert executed["receipt"]["audit"]["classification"] == "OBSERVED_UNANCHORED"
            assert executed["receipt"]["audit"]["trusted"] is False
            assert executed["practice_state"]["classification"] == "PERSISTED_UNANCHORED"
            assert executed["practice_state"]["persisted"] is True
            assert executed["practice_state"]["trusted"] is False
            assert len(executed["receipt"]["receipt_fingerprint"]) == 64
            assert len(executed["practice_state"]["state_fingerprint"]) == 64
            assert page.locator("#cash").inner_text() == "$95.00"
            assert page.locator("#equity").inner_text() == "$100.00"
            assert page.locator("#pnl").inner_text() == "+$0.00"
            assert page.locator("#receipt").inner_text() != "unrecorded"
            page.wait_for_function("() => document.querySelector('#practice-samples').textContent === '1 / 2'")
            assert page.locator("#graduation").inner_text() == "PRACTICE_REQUIRED"
            proof["checks"].append("evidence_bound_approval_simulates_only")
            proof["buy_receipt_fingerprint"] = executed["receipt"]["receipt_fingerprint"]
            proof["buy_audit_entry_hash"] = executed["receipt"]["audit"]["entry_hash"]

            sell_response = page.request.post(
                BASE_URL.rstrip("/") + "/api/proposals",
                data={"evidence": pump_evidence(0.75), "qty": 10, "side": "sell"},
            )
            assert sell_response.ok
            sell = sell_response.json()
            sell_approval = page.request.post(
                BASE_URL.rstrip("/") + f"/api/proposals/{sell['proposal_id']}/approve",
                data={},
            )
            assert sell_approval.ok
            sold = sell_approval.json()
            assert sold["status"] == "executed"
            assert sold["execution"]["filled_price"] == 0.75
            assert sold["receipt"]["sandbox_pnl_total"] == 2.5
            assert sold["receipt"]["audit"]["classification"] == "OBSERVED_UNANCHORED"
            assert sold["receipt"]["audit"]["trusted"] is False
            assert sold["practice_state"]["classification"] == "PERSISTED_UNANCHORED"
            assert sold["practice_state"]["persisted"] is True
            assert sold["real_money"] is False
            assert sold["live_execution"] is False
            wallet_after_sell = page.request.get(BASE_URL.rstrip("/") + "/api/wallet").json()
            assert wallet_after_sell["cash"] == 102.5
            assert wallet_after_sell["equity"] == 102.5
            assert wallet_after_sell["pnl_total"] == 2.5
            page.evaluate("wallet()")
            page.wait_for_function("() => document.querySelector('#pnl').textContent === '+$2.50'")
            page.wait_for_function("() => document.querySelector('#graduation').textContent === 'READY_FOR_ELIGIBILITY_REVIEW'")
            assert page.locator("#cash").inner_text() == "$102.50"
            assert page.locator("#equity").inner_text() == "$102.50"
            assert page.locator("#practice-samples").inner_text() == "2 / 2"
            graduation = page.request.get(BASE_URL.rstrip("/") + "/api/graduation").json()
            assert graduation["classification"] == "READY_FOR_ELIGIBILITY_REVIEW"
            assert graduation["review_ready"] is True
            assert graduation["practice_evidence_complete"] is True
            assert graduation["live_review_ready"] is False
            assert graduation["platform_eligibility_verified"] is False
            assert graduation["eligibility_review_required"] is True
            assert graduation["eligibility"]["classification"] == "UNVERIFIED"
            assert graduation["metrics"]["completed_round_trips"] == 1
            assert graduation["metrics"]["pnl_total"] == 2.5
            assert graduation["execution_authorized"] is False
            assert graduation["submit_capability"] is False
            assert graduation["money_movement_capability"] is False
            assert graduation["real_money"] is False
            assert graduation["live_execution"] is False
            assert graduation["authority"] == "none"
            proof["checks"].append("practice_evidence_reaches_eligibility_review_only")
            proof["graduation_fingerprint"] = graduation["fingerprint"]
            proof["checks"].append("sandbox_round_trip_pnl_receipted")
            proof["sell_receipt_fingerprint"] = sold["receipt"]["receipt_fingerprint"]
            proof["sell_audit_entry_hash"] = sold["receipt"]["audit"]["entry_hash"]
            proof["practice_state_fingerprint"] = sold["practice_state"]["state_fingerprint"]
            proof["pnl_total"] = wallet_after_sell["pnl_total"]

            audit_records = [
                json.loads(line)
                for line in Path(env["SLEEPWEALTH_PUMP_AUDIT_LOG"]).read_text(encoding="utf-8").splitlines()
            ]
            assert len(audit_records) == 2
            assert audit_records[1]["prev_hash"] == audit_records[0]["entry_hash"]
            assert audit_records[1]["sandbox_pnl_total"] == 2.5
            proof["checks"].append("sandbox_audit_hash_chain")

            persisted = json.loads(Path(env["SLEEPWEALTH_PUMP_PRACTICE_STATE"]).read_text(encoding="utf-8"))
            assert persisted["schema"] == "pump-practice-state-v1"
            assert len(persisted["execution_receipts"]) == 2
            assert persisted["real_money"] is False
            assert persisted["live_execution"] is False
            assert len(persisted["state_fingerprint"]) == 64
            proof["checks"].append("practice_snapshot_persisted")

            stop_server(server)
            server = start_server(env)
            response = page.reload(wait_until="networkidle")
            assert response and response.ok
            page.wait_for_function("() => document.querySelector('#practice-samples').textContent === '2 / 2'")
            page.wait_for_function("() => document.querySelector('#graduation').textContent === 'READY_FOR_ELIGIBILITY_REVIEW'")
            assert page.locator("#cash").inner_text() == "$102.50"
            assert page.locator("#equity").inner_text() == "$102.50"
            assert page.locator("#pnl").inner_text() == "+$2.50"
            restarted_graduation = page.request.get(BASE_URL.rstrip("/") + "/api/graduation").json()
            assert restarted_graduation["metrics"]["execution_count"] == 2
            assert restarted_graduation["metrics"]["completed_round_trips"] == 1
            assert restarted_graduation["metrics"]["pnl_total"] == 2.5
            assert restarted_graduation["platform_eligibility_verified"] is False
            assert restarted_graduation["execution_authorized"] is False
            assert restarted_graduation["real_money"] is False
            assert restarted_graduation["live_execution"] is False
            proof["checks"].append("practice_history_survives_process_restart")

            page.screenshot(path=str(ARTIFACT_DIR / "pump-live-box-desktop.png"), full_page=True)
            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            assert mobile.goto(BASE_URL, wait_until="networkidle").ok
            assert mobile.get_by_text("PUMP LIVE BOX").is_visible()
            assert mobile.locator("#pnl").inner_text() == "+$2.50"
            mobile.wait_for_function("() => document.querySelector('#graduation').textContent === 'READY_FOR_ELIGIBILITY_REVIEW'")
            assert mobile.locator("#practice-samples").inner_text() == "2 / 2"
            overflow = mobile.evaluate("() => document.documentElement.scrollWidth > document.documentElement.clientWidth")
            assert overflow is False
            mobile.screenshot(path=str(ARTIFACT_DIR / "pump-live-box-mobile.png"), full_page=True)
            proof["checks"].append("mobile_surface")
            browser.close()
        (ARTIFACT_DIR / "pump-live-box-playwright-proof.json").write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
        print(json.dumps(proof, indent=2, sort_keys=True))
    finally:
        stop_server(server)


if __name__ == "__main__":
    main()
