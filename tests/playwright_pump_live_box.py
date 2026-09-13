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
                assert data["real_money"] is False
                return
        except Exception:
            time.sleep(0.25)
    raise RuntimeError("Pump Live Box failed health check")


def main():
    ARTIFACT_DIR.mkdir(exist_ok=True)
    env = os.environ.copy()
    env["SLEEPWEALTH_APPROVAL_STATE"] = "/tmp/pump-live-box-approvals.json"
    Path(env["SLEEPWEALTH_APPROVAL_STATE"]).unlink(missing_ok=True)
    server = subprocess.Popen(
        [sys.executable, "-m", "backend.pump_live_box_server", "--host", "127.0.0.1", "--port", "8768"],
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
    )
    try:
        wait_for_health()
        proof = {"source_sha": SOURCE_SHA, "surface": "pump-live-box", "checks": [], "real_money": False, "live_execution": False}
        with sync_playwright() as p:
            browser = p.chromium.launch()
            page = browser.new_page(viewport={"width": 1440, "height": 1000})
            response = page.goto(BASE_URL, wait_until="networkidle")
            assert response and response.ok
            assert page.get_by_role("heading", name="Evidence in. Authority stays out.").is_visible()
            assert page.get_by_text("PUBLIC EVIDENCE · READ-ONLY").is_visible()
            assert page.get_by_text("SIMULATED EXECUTION ONLY").is_visible()
            assert page.locator("#cash").inner_text() == "$100.00"
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
            assert page.locator("#cash").inner_text() == "$95.00"
            proof["checks"].append("evidence_bound_approval_simulates_only")
            page.screenshot(path=str(ARTIFACT_DIR / "pump-live-box-desktop.png"), full_page=True)
            mobile = browser.new_page(viewport={"width": 390, "height": 844})
            assert mobile.goto(BASE_URL, wait_until="networkidle").ok
            assert mobile.get_by_text("PUMP LIVE BOX").is_visible()
            overflow = mobile.evaluate("() => document.documentElement.scrollWidth > document.documentElement.clientWidth")
            assert overflow is False
            mobile.screenshot(path=str(ARTIFACT_DIR / "pump-live-box-mobile.png"), full_page=True)
            proof["checks"].append("mobile_surface")
            browser.close()
        (ARTIFACT_DIR / "pump-live-box-playwright-proof.json").write_text(json.dumps(proof, indent=2, sort_keys=True) + "\n")
        print(json.dumps(proof, indent=2, sort_keys=True))
    finally:
        server.terminate()
        try:
            server.wait(timeout=5)
        except subprocess.TimeoutExpired:
            server.kill()


if __name__ == "__main__":
    main()
