import hashlib
import json
import os
import subprocess
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

BASE_URL = os.getenv("MOM8_BASE_URL", "http://127.0.0.1:8766/mom8/")
ARTIFACT_DIR = Path(os.getenv("SLEEPWEALTH_ARTIFACT_DIR", "artifacts"))
ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head_sha() -> str:
    return subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()


def prove(context, prefix: str) -> None:
    page = context.new_page()
    response = page.goto(BASE_URL, wait_until="networkidle")
    assert response is not None and response.ok

    expect(page.get_by_role("heading", name="MOM OF 8 MOM8")).to_be_visible()
    expect(page.get_by_text("REAL PEOPLE · REAL PROGRESS · BUILD IN PUBLIC")).to_be_visible()
    expect(page.get_by_text("PRELAUNCH BRAND PREVIEW · NO EXECUTION AUTHORITY")).to_be_visible()
    expect(page.get_by_text("Brand-ready does not mean launch-authorized.")).to_be_visible()
    expect(page.get_by_text("Wallet, mint, launch & trade authority")).to_be_visible()
    expect(page.get_by_text("LOCKED", exact=True)).to_be_visible()
    expect(page.get_by_text("MOM8::prelaunch-brand-assets::v1")).to_be_visible()
    expect(page.get_by_text("mom8-prelaunch-brand-assets-v1", exact=False)).to_be_visible()

    logo = page.get_by_role("img", name="MOM8 sunrise-ring identity mark")
    expect(logo).to_be_visible()

    page.screenshot(path=str(ARTIFACT_DIR / f"mom8-preview-{prefix}.png"), full_page=True)
    page.close()


def write_manifest() -> None:
    tested_sha = git_head_sha()
    source_sha = os.getenv("SLEEPWEALTH_PROOF_SOURCE_SHA", tested_sha)
    if os.getenv("GITHUB_ACTIONS") == "true":
        assert tested_sha == source_sha

    names = ["mom8-preview-desktop.png", "mom8-preview-mobile.png"]
    manifest = {
        "schema": "mom8-public-preview-proof-v1",
        "tested_sha": tested_sha,
        "source_sha": source_sha,
        "proof_type": "playwright-static-runtime",
        "identity": {"public_name": "MOM OF 8", "ticker": "MOM8"},
        "asset_fingerprint": "MOM8::prelaunch-brand-assets::v1",
        "proof_cookie": "mom8-prelaunch-brand-assets-v1",
        "authority": {
            "branding": True,
            "wallet": False,
            "mint": False,
            "launch": False,
            "trade": False,
            "spend": False,
            "transfer": False,
        },
        "screenshots": [
            {"name": name, "sha256": sha256_file(ARTIFACT_DIR / name)} for name in names
        ],
    }
    (ARTIFACT_DIR / "mom8-proof-manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
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

write_manifest()
