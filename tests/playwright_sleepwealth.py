import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("SLEEPWEALTH_BASE_URL", "http://127.0.0.1:8765")
ARTIFACT_DIR = Path(os.getenv("SLEEPWEALTH_ARTIFACT_DIR", "artifacts"))
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def prove(context, name):
    page = context.new_page()
    response = page.goto(BASE_URL, wait_until="networkidle")
    assert response is not None and response.ok

    expect(page.get_by_role("heading", name="Sleep Wealth")).to_be_visible()
    expect(page.get_by_text("NIGHT MINERAL", exact=False)).to_be_visible()
    expect(page.get_by_text("REAL DATA WATCH", exact=False)).to_be_visible()
    expect(page.get_by_text("Live execution stays disabled", exact=False)).to_be_visible()

    steps = page.get_by_label("Paper cycle")
    expect(steps).to_contain_text("Observe")
    expect(steps).to_contain_text("Evaluate")
    expect(steps).to_contain_text("Simulate")
    expect(steps).to_contain_text("Receipt")

    theme = page.evaluate(
        """() => {
            const root = document.documentElement;
            const style = getComputedStyle(root);
            return {
                name: root.dataset.theme,
                lichen: style.getPropertyValue('--lichen').trim(),
                copper: style.getPropertyValue('--copper').trim(),
                bone: style.getPropertyValue('--bone').trim(),
                glacier: style.getPropertyValue('--glacier').trim(),
            };
        }"""
    )
    assert theme == {
        "name": "night-mineral",
        "lichen": "#d6ff45",
        "copper": "#c8784d",
        "bone": "#eee5cc",
        "glacier": "#9ae7df",
    }

    for symbol in ("AAPL", "MSFT", "VTI"):
        card = page.locator(f'[data-symbol="{symbol}"]')
        expect(card).to_be_visible()
        expect(card).to_contain_text(symbol)
        expect(card).to_contain_text("mock-market-observation")
        expect(card).to_contain_text("SIMULATED FEED")
        expect(card).to_contain_text("fp")

    page.get_by_role("button", name="Observe + run paper test").click()
    result = page.locator("#result")
    expect(result).to_contain_text('"status": "executed"')
    expect(result).to_contain_text('"approved_symbols": [')
    expect(result).to_contain_text('"read_only": true')
    expect(result).to_contain_text('"live_execution": false')
    expect(result).to_contain_text('"continuity_cookie": "sw-market-v1:')
    expect(result).to_contain_text('"decision_cookie": "sw-decision-v1:')
    expect(result).to_contain_text('"outcome_cookie": "sw-outcome-v1:')
    expect(result).to_contain_text('"fill_classification": "SIMULATED_AT_OBSERVED_PRICE"')
    expect(result).to_contain_text(
        '"truth": "read-only market observation; paper simulation only; no real money moved"'
    )
    page.screenshot(path=str(ARTIFACT_DIR / name), full_page=True)


with sync_playwright() as p:
    browser = p.chromium.launch()
    try:
        desktop = browser.new_context(viewport={"width": 1440, "height": 1000})
        prove(desktop, "sleepwealth-desktop.png")
        desktop.close()

        mobile = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
        prove(mobile, "sleepwealth-mobile.png")
        mobile.close()
    finally:
        browser.close()
