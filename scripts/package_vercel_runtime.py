from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path


RUNTIME_FILES = (
    "vercel.json",
    "pyproject.toml",
    "api/__init__.py",
    "api/index.py",
    "api/mom8_assets.py",
    "approvals/__init__.py",
    "approvals/queue.py",
    "audit/__init__.py",
    "audit/logger.py",
    "backend/__init__.py",
    "backend/server.py",
    "backend/external_observers.py",
    "backend/pump_live_box_server.py",
    "backend/runtime_identity.py",
    "broker/__init__.py",
    "broker/base.py",
    "broker/factory.py",
    "broker/mock.py",
    "broker/crypto_sandbox.py",
    "broker/ibkr_readonly.py",
    "engine/__init__.py",
    "engine/evaluator.py",
    "engine/validator.py",
    "execution/__init__.py",
    "execution/executor.py",
    "execution/modes.py",
    "market/__init__.py",
    "market/external_sources.py",
    "market/lanes.py",
    "market/observation.py",
    "market/providers.py",
    "market/pump_shadow.py",
    "market/universe.py",
    "portfolio/__init__.py",
    "portfolio/models.py",
    "portfolio/tracker.py",
    "risk/__init__.py",
    "risk/gates.py",
    "rules/__init__.py",
    "rules/rules.json",
    "rules/schema.json",
    "public/mom8/index.html",
    "public/mom8/styles.css",
    "public/mom8/logo.svg",
)

REQUIRED_STATIC_ASSETS = (
    "public/mom8/index.html",
    "public/mom8/styles.css",
    "public/mom8/logo.svg",
)

FORBIDDEN_RUNTIME_PATHS = (
    "broker/alpaca.py",
    "broker/ibkr.py",
    "backend/crypto_sandbox_server.py",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git_head_sha(root: Path) -> str:
    return subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=root, text=True
    ).strip()


def canonical_digest(payload: dict) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def package_runtime(root: Path, output: Path, source_sha: str | None = None) -> dict:
    root = root.resolve()
    output = output.resolve()
    source_sha = (source_sha or git_head_sha(root)).strip().lower()
    if len(source_sha) != 40 or any(ch not in "0123456789abcdef" for ch in source_sha):
        raise ValueError("runtime bundle requires an exact 40-character git SHA")

    allowed = set(RUNTIME_FILES)
    required_static = set(REQUIRED_STATIC_ASSETS)
    forbidden = set(FORBIDDEN_RUNTIME_PATHS)
    if allowed & forbidden:
        raise RuntimeError("runtime allowlist overlaps forbidden executable adapters")
    if not required_static.issubset(allowed):
        raise RuntimeError("deployment-critical static assets must be runtime-allowlisted")

    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)

    entries: list[dict[str, object]] = []
    for relative in RUNTIME_FILES:
        source = root / relative
        if not source.is_file():
            raise FileNotFoundError(f"required runtime file is missing: {relative}")
        destination = output / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, destination)
        entries.append(
            {
                "path": relative,
                "sha256": sha256_file(destination),
                "size": destination.stat().st_size,
            }
        )

    for relative in REQUIRED_STATIC_ASSETS:
        destination = output / relative
        if destination.stat().st_size <= 0:
            raise RuntimeError(f"deployment-critical static asset is empty: {relative}")

    for relative in FORBIDDEN_RUNTIME_PATHS:
        if (output / relative).exists():
            raise RuntimeError(f"forbidden runtime path was packaged: {relative}")

    payload = {
        "schema": "sleepwealth-vercel-runtime-bundle-v1",
        "source_sha": source_sha,
        "files": sorted(entries, key=lambda row: str(row["path"])),
        "required_static_assets": list(REQUIRED_STATIC_ASSETS),
        "authority_ceiling": "paper/sandbox simulation only; read-only public market observation",
        "live_execution": False,
        "real_money": False,
        "forbidden_runtime_paths": list(FORBIDDEN_RUNTIME_PATHS),
        "truth": (
            "This bundle is deployment source evidence only. It contains no live broker adapter, "
            "wallet secret, funding authority, signing authority, or real-money execution authority."
        ),
    }
    manifest = {**payload, "fingerprint": f"vercel-runtime-v1:{canonical_digest(payload)}"}
    (output / "runtime-bundle.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    output = root / "artifacts" / "vercel-runtime"
    manifest = package_runtime(root, output)
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
