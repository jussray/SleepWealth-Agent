from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VISUAL = ROOT / "identity" / "mom8-visual-system.json"
PREVIEW = ROOT / "public" / "mom8" / "index.html"
LOGO = ROOT / "public" / "mom8" / "logo.svg"


def load_visual() -> dict:
    return json.loads(VISUAL.read_text())


def test_mom8_visual_system_preserves_canonical_identity() -> None:
    data = load_visual()
    assert data["public_name"] == "MOM OF 8"
    assert data["ticker"] == "MOM8"
    assert data["status"] == "brand-assets-ready"
    assert data["continuity"]["parent_fingerprint"] == "MOM8::prelaunch-brand-readiness::v1"
    assert data["continuity"]["asset_fingerprint"] == "MOM8::prelaunch-brand-assets::v1"
    assert data["continuity"]["proof_cookie"] == "mom8-prelaunch-brand-assets-v1"


def test_visual_assets_cannot_expand_financial_authority() -> None:
    authority = load_visual()["authority"]
    assert authority["public_brand_assets"] is True
    for denied in ("wallet", "mint", "launch", "trade", "spend", "transfer", "financial_promises"):
        assert authority[denied] is False


def test_continuity_markers_are_non_secret_and_non_authorizing() -> None:
    continuity = load_visual()["continuity"]
    assert continuity["non_secret"] is True
    assert continuity["creates_authority"] is False
    assert continuity["renews_authority"] is False


def test_public_preview_states_the_authority_guardrail() -> None:
    html = PREVIEW.read_text()
    assert "Brand-ready does not mean launch-authorized." in html
    assert "cannot connect a wallet, mint, launch, trade, spend, transfer" in html
    assert "MOM8::prelaunch-brand-assets::v1" in html
    assert "mom8-prelaunch-brand-assets-v1" in html


def test_logo_has_eight_orbit_points_and_accessible_metadata() -> None:
    svg = LOGO.read_text()
    assert "MOM8 public identity mark" in svg
    assert "eight orbiting points" in svg
    orbit_group = svg.split('<g fill="#f6c453">', 1)[1].split("</g>", 1)[0]
    assert orbit_group.count("<circle") == 8
