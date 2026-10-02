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
    assert manifest["status"] == "capabilities-implemented-authority-gated"


def test_crypto_capabilities_are_implemented() -> None:
    capabilities = load_manifest()["capabilities"]

    for name in ("launch", "mint", "wallet", "trade", "spend", "transfer"):
        assert capabilities[name]["implemented"] is True
        assert capabilities[name]["mode"] == "sandbox"
        assert capabilities[name]["implementation"].startswith(
            "broker.crypto_sandbox.CryptoSandboxBroker."
        )


def test_implemented_capabilities_do_not_self_grant_live_authority() -> None:
    manifest = load_manifest()
    authority = manifest["authority"]

    assert manifest["paper_only"] is True
    assert authority["branding"] is True
    for gated in ("launch", "mint", "wallet", "trade", "spend", "transfer"):
        assert authority[gated] is False


def test_continuity_markers_are_non_secret_and_non_authorizing() -> None:
    continuity = load_manifest()["continuity"]

    assert continuity["public_identity_fingerprint"] == "MOM-OF-8::MOM8::public-token-branding::v1"
    assert continuity["proof_cookie"] == "mom8-branding-approved-v1"
    assert continuity["non_secret"] is True
    assert continuity["creates_authority"] is False
    assert continuity["renews_authority"] is False
