import json
import os
from pathlib import Path

from playwright.sync_api import sync_playwright


BASE_URL = os.getenv("CRYPTO_SANDBOX_BASE_URL", "http://127.0.0.1:8767/")
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
        "surface": "crypto-sandbox-wallet",
        "checks": [],
        "real_money": False,
        "live_execution": False,
    }

    with sync_playwright() as p:
        browser = p.chromium.launch()

        page = browser.new_page(viewport={"width": 1440, "height": 1000})
        response = page.goto(BASE_URL, wait_until="networkidle")
        assert response and response.ok
        assert page.get_by_role("heading", name="Wallet-shaped. Fund-safe.").is_visible()
        assert page.get_by_text("$0 REAL MONEY · LIVE MONEY DISABLED").is_visible()
        assert page.get_by_text("No real money can move from this surface.").is_visible()
        _assert_no_horizontal_overflow(page)
        proof["checks"].append("desktop_surface")

        assert page.locator("#wallet-cash").inner_text() == "$100.00"
        page.locator("#symbol").fill("MOM8")
        page.locator("#qty").fill("10")
        page.locator("#price").fill("0.50")
        page.get_by_role("button", name="1 · Create proposal").click()
        page.wait_for_function(
            "() => document.querySelector('#result').textContent.includes('\"status\": \"pending\"')"
        )
        pending = json.loads(page.locator("#result").inner_text())
        assert pending["stage"] == "approval"
        assert pending["real_money"] is False
        assert pending["live_execution"] is False
        assert len(pending["proposal_fingerprint"]) == 64
        assert page.get_by_role("button", name="2 · Approve + simulate").is_enabled()
        assert page.locator("#wallet-cash").inner_text() == "$100.00"
        proof["checks"].append("proposal_is_non_mutating")

        page.get_by_role("button", name="2 · Approve + simulate").click()
        page.wait_for_function(
            "() => document.querySelector('#result').textContent.includes('\"status\": \"executed\"')"
        )
        executed = json.loads(page.locator("#result").inner_text())
        assert executed["real_money"] is False
        assert executed["live_execution"] is False
        assert executed["execution"]["real_money"] is False
        assert executed["execution"]["wallet_mode"] == "sandbox"
        assert executed["execution"]["continuity_cookie"].startswith("crypto-sandbox:")
        assert executed["approval_cookie"].startswith("crypto-sandbox-approval-v1:")
        assert executed["outcome_cookie"].startswith("crypto-sandbox-outcome-v1:")
        assert page.locator("#wallet-cash").inner_text() == "$95.00"
        proof["checks"].append("approval_bound_simulated_execution")

        page.screenshot(
            path=str(ARTIFACT_DIR / "crypto-sandbox-wallet-desktop.png"),
            full_page=True,
        )

        mobile = browser.new_page(viewport={"width": 390, "height": 844})
        response = mobile.goto(BASE_URL, wait_until="networkidle")
        assert response and response.ok
        assert mobile.get_by_text("CRYPTO SANDBOX WALLET").is_visible()
        _assert_no_horizontal_overflow(mobile)
        mobile.screenshot(
            path=str(ARTIFACT_DIR / "crypto-sandbox-wallet-mobile.png"),
            full_page=True,
        )
        proof["checks"].append("mobile_surface")

        browser.close()

    (ARTIFACT_DIR / "crypto-sandbox-playwright-proof.json").write_text(
        json.dumps(proof, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(proof, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
