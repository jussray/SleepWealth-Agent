import json
from pathlib import Path


MANIFEST = Path(__file__).resolve().parents[1] / "identity" / "mom8-public-token.json"


def load_manifest() -> dict:
    return json.loads(MANIFEST.read_text(encoding="utf-8"))


def test_mom8_public_identity_is_canonical() -> None:
    manifest = load_manifest()

    assert manifest["public_name"] == "MOM OF 8"
    assert manifest["ticker"] == "MOM8"
    assert manifest["identity_type"] == "public-token-branding"
    assert manifest["target_surface"] == "pump.fun"
    assert manifest["status"] == "approved-branding-only"


def test_branding_approval_cannot_expand_financial_authority() -> None:
    manifest = load_manifest()
    authority = manifest["authority"]

    assert manifest["paper_only"] is True
    assert authority["branding"] is True
    assert authority["launch"] is False
    assert authority["mint"] is False
    assert authority["wallet"] is False
    assert authority["trade"] is False
    assert authority["spend"] is False
    assert authority["transfer"] is False


def test_continuity_markers_are_non_secret_and_non_authorizing() -> None:
    continuity = load_manifest()["continuity"]

    assert continuity["public_identity_fingerprint"] == "MOM-OF-8::MOM8::public-token-branding::v1"
    assert continuity["proof_cookie"] == "mom8-branding-approved-v1"
    assert continuity["non_secret"] is True
    assert continuity["creates_authority"] is False
    assert continuity["renews_authority"] is False
