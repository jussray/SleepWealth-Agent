import hashlib
import json
import os
import subprocess
from pathlib import Path

from authority import (
    AuthorityGrant,
    AuthorityRequest,
    AuthorityRuntime,
    ConsequenceTier,
    EffectClass,
)
from evidence import EvidenceArtifact, EvidenceObjectV1
from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("SLEEPWEALTH_BASE_URL", "http://127.0.0.1:8765")
ARTIFACT_DIR = Path(os.getenv("SLEEPWEALTH_ARTIFACT_DIR", "artifacts"))
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def write_debug(page, prefix, stage):
    safe_stage = stage.replace("/", "-").replace(" ", "-")
    page.screenshot(
        path=str(ARTIFACT_DIR / f"debug-{prefix}-{safe_stage}.png"),
        full_page=True,
    )
    (ARTIFACT_DIR / f"debug-{prefix}-{safe_stage}.html").write_text(
        page.content(), encoding="utf-8"
    )
    (ARTIFACT_DIR / f"debug-{prefix}-{safe_stage}.txt").write_text(
        page.locator("body").inner_text(), encoding="utf-8"
    )


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
    expect(result).not_to_contain_text('"approved_symbols"')
    expect(result).to_contain_text("paper simulation only; no real money moved")


def prove(context, prefix):
    page = context.new_page()
    stage = "open"
    try:
        response = page.goto(BASE_URL, wait_until="networkidle")
        assert response is not None and response.ok
        stage = "initial-render"
        write_debug(page, prefix, stage)

        expect(page.get_by_role("heading", name="Sleep Wealth")).to_be_visible()
        expect(page.get_by_text("NIGHT MINERAL", exact=False)).to_be_visible()
        expect(page.locator(".topline .badge")).to_contain_text("SEPARATE LANES")
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
        stage = "stock-cards"
        assert_cards(page, ("AAPL", "MSFT", "VTI"), "stock-market")

        stage = "stock-submit"
        page.get_by_role("button", name="Observe + run paper test").click()
        assert_paper_receipt(page, "stock-market")
        page.screenshot(
            path=str(ARTIFACT_DIR / f"sleepwealth-stock-{prefix}.png"), full_page=True
        )

        stage = "crypto-switch"
        crypto_tab.click()
        expect(page.locator("#app")).to_have_attribute("data-lane", "crypto")
        expect(stock_tab).to_have_attribute("aria-pressed", "false")
        expect(crypto_tab).to_have_attribute("aria-pressed", "true")
        expect(page.get_by_label("Search U.S. listed market")).to_be_hidden()
        expect(page.locator("#symbol")).to_have_value("BTC-USD")
        assert_cards(page, ("BTC-USD", "ETH-USD", "SOL-USD"), "crypto")

        stage = "crypto-submit"
        page.get_by_role("button", name="Observe + run paper test").click()
        assert_paper_receipt(page, "crypto")
        expect(page.locator("#result")).to_contain_text('"crypto_native": true')
        page.screenshot(
            path=str(ARTIFACT_DIR / f"sleepwealth-crypto-{prefix}.png"), full_page=True
        )
    except Exception:
        try:
            write_debug(page, prefix, f"failure-{stage}")
        except Exception:
            pass
        raise


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head_sha():
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def write_proof_manifest():
    github_actions = os.getenv("GITHUB_ACTIONS") == "true"
    tested_sha = git_head_sha()
    source_sha = os.getenv("SLEEPWEALTH_PROOF_SOURCE_SHA", tested_sha)
    event_sha = os.getenv("GITHUB_SHA")
    if github_actions:
        for sha in (tested_sha, source_sha, event_sha):
            assert sha is not None and len(sha) == 40
            assert all(char in "0123456789abcdef" for char in sha.lower())
        assert tested_sha == source_sha

    screenshots = [
        "sleepwealth-stock-desktop.png",
        "sleepwealth-crypto-desktop.png",
        "sleepwealth-stock-mobile.png",
        "sleepwealth-crypto-mobile.png",
    ]
    artifacts = tuple(
        EvidenceArtifact(name=name, sha256=sha256_file(ARTIFACT_DIR / name))
        for name in screenshots
    )
    evidence = EvidenceObjectV1(
        subject="sleepwealth-paper-ui-runtime",
        evidence_type="playwright-ui-runtime",
        source_sha=source_sha,
        tested_sha=tested_sha,
        authority_ceiling="paper-only; read-only market observation; no real-money execution",
        claims=(
            "stock-lane UI runtime rendered",
            "crypto-lane UI runtime rendered",
            "paper execution paths exercised",
            "read-only market observation semantics displayed",
        ),
        does_not_prove=(
            "live execution authority",
            "external broker connectivity",
            "real-money movement",
        ),
        artifacts=artifacts,
    )
    proof_claim_grant = AuthorityGrant(
        grant_id="ci-proof-claim-v1",
        subject="sleepwealth-paper-ui-runtime",
        allowed_actions=("assert_runtime_truth",),
        allowed_effects=(EffectClass.READ_ONLY,),
        max_consequence=ConsequenceTier.INFORMATIONAL,
    )
    authority_runtime = AuthorityRuntime((proof_claim_grant,))
    authority_decision = authority_runtime.evaluate(
        AuthorityRequest(
            action="assert_runtime_truth",
            subject="sleepwealth-paper-ui-runtime",
            consequence=ConsequenceTier.INFORMATIONAL,
            effect=EffectClass.READ_ONLY,
            evidence=evidence,
            current_source_sha=tested_sha,
            execution_mode="practice",
            grant_id="ci-proof-claim-v1",
        )
    )
    assert authority_decision.allowed is True

    manifest = {
        "schema": "sleepwealth-playwright-proof-v1",
        "tested_sha": tested_sha,
        "source_sha": source_sha,
        "github_event_sha": event_sha,
        "github_event_name": os.getenv("GITHUB_EVENT_NAME"),
        "github_run_id": os.getenv("GITHUB_RUN_ID"),
        "repository": os.getenv("GITHUB_REPOSITORY"),
        "proof_type": "playwright-ui-runtime",
        "execution_mode": "practice",
        "live_execution": False,
        "market_observation": "read-only",
        "authority": "non-authorizing evidence",
        "claim_scope": list(evidence.claims),
        "does_not_prove": list(evidence.does_not_prove),
        "screenshots": [artifact.to_dict() for artifact in artifacts],
        "evidence": evidence.to_dict(),
        "authority_decision": authority_decision.to_dict(),
    }
    (ARTIFACT_DIR / "proof-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


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

write_proof_manifest()
