from backend import runtime_bundle_identity
from backend.runtime_identity import runtime_identity
from backend.runtime_server import health_payload


SHA_A = "a" * 40
SHA_B = "b" * 40
SHA_C = "c" * 40


def test_render_identity_has_priority():
    receipt = runtime_identity(
        {
            "RENDER_GIT_COMMIT": SHA_A,
            "SLEEPWEALTH_RUNTIME_SHA": SHA_B,
            "GITHUB_SHA": SHA_C,
            "RENDER_GIT_REPO_SLUG": "jussray/SleepWealth-Agent",
            "RENDER_GIT_BRANCH": "main",
            "RENDER_SERVICE_ID": "srv-example",
        }
    )
    assert receipt["source_sha"] == SHA_A
    assert receipt["source_provider"] == "render"
    assert receipt["exact_source_known"] is True
    assert receipt["repository"] == "jussray/SleepWealth-Agent"
    assert receipt["branch"] == "main"
    assert receipt["execution_authorized"] is False


def test_explicit_runtime_sha_supports_ci_without_render():
    receipt = runtime_identity({"SLEEPWEALTH_RUNTIME_SHA": SHA_B})
    assert receipt["source_sha"] == SHA_B
    assert receipt["source_provider"] == "sleepwealth-runtime"
    assert receipt["exact_source_known"] is True
    assert receipt["execution_authorized"] is False


def test_packaged_vercel_bundle_proves_identity_without_env(monkeypatch):
    monkeypatch.setattr(runtime_bundle_identity, "SOURCE_SHA", SHA_C)
    receipt = runtime_identity({})
    assert receipt["source_sha"] == SHA_C
    assert receipt["source_provider"] == "vercel-bundle"
    assert receipt["exact_source_known"] is True
    assert receipt["execution_authorized"] is False


def test_invalid_packaged_identity_fails_closed(monkeypatch):
    monkeypatch.setattr(runtime_bundle_identity, "SOURCE_SHA", "not-a-commit")
    receipt = runtime_identity({})
    assert receipt["source_sha"] is None
    assert receipt["source_provider"] == "unknown"
    assert receipt["exact_source_known"] is False
    assert receipt["execution_authorized"] is False


def test_invalid_higher_priority_runtime_sha_does_not_fall_through(monkeypatch):
    monkeypatch.setattr(runtime_bundle_identity, "SOURCE_SHA", SHA_C)
    receipt = runtime_identity({"RENDER_GIT_COMMIT": "not-a-commit"})
    assert receipt["source_sha"] is None
    assert receipt["source_provider"] == "unknown"
    assert receipt["exact_source_known"] is False
    assert receipt["execution_authorized"] is False


def test_invalid_runtime_sha_fails_closed():
    receipt = runtime_identity({"RENDER_GIT_COMMIT": "not-a-commit"})
    assert receipt["source_sha"] is None
    assert receipt["source_provider"] == "unknown"
    assert receipt["exact_source_known"] is False
    assert receipt["execution_authorized"] is False
    assert "does not grant" in receipt["truth"]


def test_health_payload_keeps_paper_only_boundary(monkeypatch):
    monkeypatch.setenv("SLEEPWEALTH_RUNTIME_SHA", SHA_C)
    monkeypatch.setenv("SLEEPWEALTH_MARKET_SOURCE", "mock")
    payload = health_payload()
    assert payload["status"] == "ok"
    assert payload["mode"] == "paper"
    assert payload["broker"] == "mock"
    assert payload["market_observation"] == "read-only"
    assert payload["external_crypto_sources"] == "observation-only"
    assert payload["live_execution"] is False
    assert payload["runtime_identity"]["source_sha"] == SHA_C
    assert payload["runtime_identity"]["execution_authorized"] is False
