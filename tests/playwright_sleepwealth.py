import os
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("SLEEPWEALTH_BASE_URL", "http://127.0.0.1:8765")
ARTIFACT_DIR = Path(os.getenv("SLEEPWEALTH_ARTIFACT_DIR", "artifacts"))
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def assert_theme(page):
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


def assert_cards(page, symbols, lane):
    for symbol in symbols:
        card = page.locator(f'[data-symbol="{symbol}"]')
        expect(card).to_be_visible()
        expect(card).to_contain_text(symbol)
        expect(card).to_contain_text("mock-market-observation")
        expect(card).to_contain_text("SIMULATED FEED")
        expect(card).to_contain_text(lane)
        expect(card).to_contain_text("fp")


def assert_paper_receipt(page, lane):
    result = page.locator("#result")
    expect(result).to_contain_text('"status": "executed"')
    expect(result).to_contain_text(f'"lane": "{lane}"')
    expect(result).to_contain_text('"read_only": true')
    expect(result).to_contain_text('"live_execution": false')
    expect(result).to_contain_text('"continuity_cookie": "sw-market-v1:')
    expect(result).to_contain_text('"lane_cookie": "sw-lane-v1:')
    expect(result).to_contain_text('"decision_cookie": "sw-decision-v1:')
    expect(result).to_contain_text('"outcome_cookie": "sw-outcome-v1:')
    expect(result).to_contain_text('"fill_classification": "SIMULATED_AT_OBSERVED_PRICE"')
    expect(result).to_contain_text("paper simulation only; no real money moved")


def prove(context, prefix):
    page = context.new_page()
    response = page.goto(BASE_URL, wait_until="networkidle")
    assert response is not None and response.ok

    expect(page.get_by_role("heading", name="Sleep Wealth")).to_be_visible()
    expect(page.get_by_text("NIGHT MINERAL", exact=False)).to_be_visible()
    expect(page.get_by_text("SEPARATE LANES", exact=False)).to_be_visible()
    expect(page.get_by_text("Live execution stays disabled", exact=False)).to_be_visible()
    assert_theme(page)

    steps = page.get_by_label("Paper cycle")
    expect(steps).to_contain_text("Observe")
    expect(steps).to_contain_text("Evaluate")
    expect(steps).to_contain_text("Simulate")
    expect(steps).to_contain_text("Receipt")

    stock_tab = page.get_by_role("button", name="Stocks")
    crypto_tab = page.get_by_role("button", name="Crypto")
    expect(stock_tab).to_have_attribute("aria-pressed", "true")
    expect(crypto_tab).to_have_attribute("aria-pressed", "false")
    expect(page.get_by_label("Search U.S. listed market")).to_be_visible()
    assert_cards(page, ("AAPL", "MSFT", "VTI"), "stock-market")

    page.get_by_role("button", name="Observe + run paper test").click()
    assert_paper_receipt(page, "stock-market")
    page.screenshot(path=str(ARTIFACT_DIR / f"sleepwealth-stock-{prefix}.png"), full_page=True)

    crypto_tab.click()
    expect(page.locator("#app")).to_have_attribute("data-lane", "crypto")
    expect(stock_tab).to_have_attribute("aria-pressed", "false")
    expect(crypto_tab).to_have_attribute("aria-pressed", "true")
    expect(page.get_by_label("Search U.S. listed market")).to_be_hidden()
    expect(page.locator("#symbol")).to_have_value("BTC-USD")
    assert_cards(page, ("BTC-USD", "ETH-USD", "SOL-USD"), "crypto")

    page.get_by_role("button", name="Observe + run paper test").click()
    assert_paper_receipt(page, "crypto")
    expect(page.locator("#result")).to_contain_text('"crypto_native": true')
    page.screenshot(path=str(ARTIFACT_DIR / f"sleepwealth-crypto-{prefix}.png"), full_page=True)


with sync_playwright() as p:
    browser = p.chromium.launch()
    try:
        desktop = browser.new_context(viewport={"width": 1440, "height": 1000})
        prove(desktop, "desktop")
        desktop.close()

        mobile = browser.new_context(viewport={"width": 390, "height": 844}, is_mobile=True)
        prove(mobile, "mobile")
        mobile.close()
    finally:
        browser.close()
