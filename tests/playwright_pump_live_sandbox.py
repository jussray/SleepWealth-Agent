import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = os.getenv("PUMP_SANDBOX_BASE_URL", "http://127.0.0.1:8768/")
SOURCE_SHA = os.getenv("SLEEPWEALTH_PROOF_SOURCE_SHA", "unknown")
ARTIFACT_DIR = Path("artifacts")


def _assert_no_horizontal_overflow(page):
    overflow = page.evaluate(
        "() => document.documentElement.scrollWidth > document.documentElement.clientWidth"
    )
    assert overflow is False


def main():
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    proof = {
        "source_sha": SOURCE_SHA,
        "base_url": BASE_URL,
        "surface": "pump-evidence-practice-sandbox",
        "checks": [],
        "pump_network_access": False,
        "real_money": False,
        "live_execution": False,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        response = page.goto(BASE_URL, wait_until="networkidle")
        assert response and response.ok
        assert page.get_by_role("heading", name="Observe. Bind. Practice.").is_visible()
        assert page.get_by_text("NO WALLET · NO SIGNING · $0 REAL MONEY").is_visible()
        _assert_no_horizontal_overflow(page)
        proof["checks"].append("desktop_surface")

        assert page.locator("#wallet-cash").inner_text() == "$100.00"
        page.locator("#source-url").fill("https://pump.fun/coin/example")
        page.locator("#symbol").fill("MOM8")
        page.locator("#mint").fill("PumpMint111111111111111111111111111111111")
        page.locator("#price").fill("0.50")
        page.locator("#qty").fill("10")
        page.get_by_role("button", name="1 · Bind evidence + create proposal").click()
        page.wait_for_function(
            "() => document.querySelector('#result').textContent.includes('\\\"status\\\": \\\"pending\\\"')"
        )
        pending = json.loads(page.locator("#result").inner_text())
        assert pending["stage"] == "approval"
        assert pending["real_money"] is False
        assert pending["live_execution"] is False
        assert len(pending["public_evidence_fingerprint"]) == 64
        assert len(pending["evidence_observation_fingerprint"]) == 64
        assert len(pending["proposal_fingerprint"]) == 64
        assert pending["pump_shadow"]["mint"].startswith("PumpMint")
        assert pending["pump_shadow"]["mirrored_price"] == 0.5
        assert pending["pump_shadow"]["real_money"] is False
        assert page.locator("#wallet-cash").inner_text() == "$100.00"
        assert page.get_by_role("button", name="2 · Approve + simulate").is_enabled()
        proof["checks"].append("pump_evidence_bound_before_approval")

        page.get_by_role("button", name="2 · Approve + simulate").click()
        page.wait_for_function(
            "() => document.querySelector('#result').textContent.includes('\\\"status\\\": \\\"executed\\\"')"
        )
        executed = json.loads(page.locator("#result").inner_text())
        assert executed["real_money"] is False
        assert executed["live_execution"] is False
        assert executed["public_evidence_fingerprint"] == pending["public_evidence_fingerprint"]
        assert executed["evidence_observation_fingerprint"] == pending["evidence_observation_fingerprint"]
        assert executed["pump_shadow"]["mirror_fingerprint"] == pending["pump_shadow"]["mirror_fingerprint"]
        assert executed["execution"]["real_money"] is False
        assert page.locator("#wallet-cash").inner_text() == "$95.00"
        proof["checks"].append("evidence_bound_approval_simulates_only")

        page.screenshot(
            path=str(ARTIFACT_DIR / "pump-evidence-sandbox-desktop.png"),
            full_page=True,
        )

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        response = mobile.goto(BASE_URL, wait_until="networkidle")
        assert response and response.ok
        assert mobile.get_by_text("PUMP PUBLIC EVIDENCE → PRACTICE").is_visible()
        _assert_no_horizontal_overflow(mobile)
        mobile.screenshot(
            path=str(ARTIFACT_DIR / "pump-evidence-sandbox-mobile.png"),
            full_page=True,
        )
        proof["checks"].append("mobile_surface")
        browser.close()

    (ARTIFACT_DIR / "pump-evidence-sandbox-playwright-proof.json").write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(proof, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
