import hashlib
import importlib.util
import json
from pathlib import Path

import pytest

from scripts.package_vercel_runtime import (
    FORBIDDEN_RUNTIME_PATHS,
    RUNTIME_BUNDLE_IDENTITY_FILE,
    RUNTIME_FILES,
    VERCEL_FUNCTION_ENTRYPOINT,
    VERCEL_ROUTE,
    missing_runtime_imports,
    package_runtime,
    validate_runtime_import_closure,
    validate_vercel_config,
)


def test_runtime_bundle_is_exact_head_and_non_authorizing(tmp_path):
    root = Path(__file__).resolve().parents[1]
    source_sha = "a" * 40
    output = tmp_path / "runtime"

    manifest = package_runtime(root, output, source_sha=source_sha)

    assert manifest["source_sha"] == source_sha
    assert manifest["live_execution"] is False
    assert manifest["real_money"] is False
    assert "paper/sandbox simulation only" in manifest["authority_ceiling"]
    assert manifest["fingerprint"].startswith("vercel-runtime-v1:")
    assert (output / "runtime-bundle.json").is_file()

    deployment = manifest["deployment_contract"]
    assert deployment["framework"] == "other"
    assert deployment["function_entrypoint"] == VERCEL_FUNCTION_ENTRYPOINT
    assert deployment["build_command"] == "auto"
    assert deployment["output_directory"] == "auto"
    assert deployment["route_destination"] == VERCEL_ROUTE["dest"]

    packaged = {row["path"] for row in manifest["files"]}
    assert packaged == set(RUNTIME_FILES)
    assert packaged.isdisjoint(FORBIDDEN_RUNTIME_PATHS)

    identity_path = output / RUNTIME_BUNDLE_IDENTITY_FILE
    spec = importlib.util.spec_from_file_location("packaged_runtime_bundle_identity", identity_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    assert module.SOURCE_SHA == source_sha
    assert module.SOURCE_PROVIDER == "vercel-bundle"

    required_public = {
        "public/mom8/index.html",
        "public/mom8/styles.css",
        "public/mom8/logo.svg",
    }
    assert required_public.issubset(packaged)
    public_dir = output / "public"
    assert public_dir.is_dir()
    assert any(path.is_file() and path.stat().st_size > 0 for path in public_dir.rglob("*"))
    assert all((output / path).is_file() for path in required_public)
    assert all((output / path).stat().st_size > 0 for path in required_public)

    for row in manifest["files"]:
        path = output / row["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
        assert path.stat().st_size == row["size"]


def test_source_checkout_bundle_identity_is_non_authorizing_placeholder():
    root = Path(__file__).resolve().parents[1]
    source = (root / RUNTIME_BUNDLE_IDENTITY_FILE).read_text(encoding="utf-8")
    assert "SOURCE_SHA: str | None = None" in source
    assert 'SOURCE_PROVIDER = "vercel-bundle"' in source


def test_runtime_bundle_excludes_live_broker_and_server_paths():
    packaged = set(RUNTIME_FILES)
    assert "broker/alpaca.py" not in packaged
    assert "broker/ibkr.py" not in packaged
    assert "backend/crypto_sandbox_server.py" not in packaged
    assert "broker/mock.py" in packaged
    assert "broker/crypto_sandbox.py" in packaged
    assert "backend/pump_live_box_server.py" in packaged
    assert "backend/pump_sandbox_receipts.py" in packaged
    assert "gate/pump_practice_graduation.py" in packaged


def test_runtime_bundle_first_party_import_graph_is_closed():
    root = Path(__file__).resolve().parents[1]

    assert missing_runtime_imports(root) == []
    validate_runtime_import_closure(root)


def test_runtime_import_closure_rejects_missing_first_party_dependency():
    root = Path(__file__).resolve().parents[1]
    incomplete = tuple(
        path for path in RUNTIME_FILES if path != "backend/pump_sandbox_receipts.py"
    )

    assert "backend/pump_sandbox_receipts.py" in missing_runtime_imports(root, incomplete)
    with pytest.raises(RuntimeError, match="pump_sandbox_receipts"):
        validate_runtime_import_closure(root, incomplete)


def test_packaged_entrypoint_imports_from_bundle_only(tmp_path, monkeypatch):
    root = Path(__file__).resolve().parents[1]
    output = tmp_path / "runtime"
    source_sha = "b" * 40
    package_runtime(root, output, source_sha=source_sha)

    monkeypatch.syspath_prepend(str(output))
    for name in list(__import__("sys").modules):
        if name == "api" or name.startswith("api.") or name == "backend" or name.startswith("backend."):
            __import__("sys").modules.pop(name, None)

    imported = __import__("api.index", fromlist=["handler"])
    assert imported.handler is not None
    identity = __import__("backend.runtime_identity", fromlist=["runtime_identity"])
    receipt = identity.runtime_identity({})
    assert receipt["source_sha"] == source_sha
    assert receipt["source_provider"] == "vercel-bundle"
    assert receipt["execution_authorized"] is False


def test_vercel_config_pins_the_function_runtime_without_static_build_override():
    root = Path(__file__).resolve().parents[1]
    config = json.loads((root / "vercel.json").read_text(encoding="utf-8"))

    contract = validate_vercel_config(config)

    assert config["framework"] is None
    assert "buildCommand" not in config
    assert "outputDirectory" not in config
    assert contract["function_entrypoint"] == "api/index.py"
    assert contract["build_command"] == "auto"
    assert contract["output_directory"] == "auto"


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("buildCommand", "python build.py"),
        ("outputDirectory", "public"),
    ],
)
def test_vercel_config_rejects_custom_build_or_static_output_drift(key, value):
    config = {
        "framework": None,
        "routes": [dict(VERCEL_ROUTE)],
        key: value,
    }

    with pytest.raises(RuntimeError, match=key):
        validate_vercel_config(config)


def test_vercel_config_requires_explicit_other_framework_and_canonical_route():
    with pytest.raises(RuntimeError, match="Other framework"):
        validate_vercel_config({"routes": [dict(VERCEL_ROUTE)]})

    with pytest.raises(RuntimeError, match="api/index.py route"):
        validate_vercel_config({"framework": None, "routes": []})
