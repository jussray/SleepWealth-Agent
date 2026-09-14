import hashlib
from pathlib import Path

from scripts.package_vercel_runtime import (
    FORBIDDEN_RUNTIME_PATHS,
    REQUIRED_STATIC_ASSETS,
    RUNTIME_FILES,
    package_runtime,
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

    packaged = {row["path"] for row in manifest["files"]}
    assert packaged == set(RUNTIME_FILES)
    assert packaged.isdisjoint(FORBIDDEN_RUNTIME_PATHS)

    required_public = set(REQUIRED_STATIC_ASSETS)
    assert manifest["required_static_assets"] == list(REQUIRED_STATIC_ASSETS)
    assert required_public.issubset(packaged)
    assert all((output / path).is_file() for path in required_public)
    assert all((output / path).stat().st_size > 0 for path in required_public)

    for row in manifest["files"]:
        path = output / row["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == row["sha256"]
        assert path.stat().st_size == row["size"]


def test_runtime_bundle_excludes_live_broker_and_server_paths():
    packaged = set(RUNTIME_FILES)
    assert "broker/alpaca.py" not in packaged
    assert "broker/ibkr.py" not in packaged
    assert "backend/crypto_sandbox_server.py" not in packaged
    assert "broker/mock.py" in packaged
    assert "broker/crypto_sandbox.py" in packaged
    assert "backend/pump_live_box_server.py" in packaged
