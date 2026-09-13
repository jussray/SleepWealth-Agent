import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
IDENTITY = ROOT / "identity" / "mom8-public-token.json"
READINESS = ROOT / "identity" / "mom8-launch-readiness.json"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_readiness_matches_canonical_identity() -> None:
    identity = load(IDENTITY)
    readiness = load(READINESS)

    assert readiness["public_name"] == identity["public_name"] == "MOM OF 8"
    assert readiness["ticker"] == identity["ticker"] == "MOM8"
    assert readiness["identity_ref"] == "identity/mom8-public-token.json"
    assert readiness["provenance"]["identity_fingerprint"] == identity["continuity"]["public_identity_fingerprint"]


def test_readiness_does_not_create_financial_authority() -> None:
    readiness = load(READINESS)
    state = readiness["readiness"]

    assert state["financial_promises_allowed"] is False
    assert state["wallet_connected"] is False
    assert state["mint_authorized"] is False
    assert state["launch_authorized"] is False
    assert state["trade_authorized"] is False
    assert state["spend_authorized"] is False
    assert state["transfer_authorized"] is False


def test_readiness_markers_are_non_secret_and_non_authorizing() -> None:
    provenance = load(READINESS)["provenance"]

    assert provenance["readiness_fingerprint"] == "MOM8::prelaunch-brand-readiness::v1"
    assert provenance["proof_cookie"] == "mom8-prelaunch-brand-readiness-v1"
    assert provenance["non_secret"] is True
    assert provenance["creates_authority"] is False
    assert provenance["renews_authority"] is False


def test_public_copy_rejects_financial_hype() -> None:
    copy = load(READINESS)["public_copy"]
    blocked = set(copy["avoid_claims"])

    assert "guaranteed returns" in blocked
    assert "price appreciation promises" in blocked
    assert "investment advice" in blocked
    assert "fake endorsements" in blocked
    assert "fabricated community metrics" in blocked
