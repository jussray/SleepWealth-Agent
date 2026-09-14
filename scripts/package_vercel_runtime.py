from __future__ import annotations

import ast
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
    "backend/pump_sandbox_receipts.py",
    "backend/runtime_identity.py",
    "backend/runtime_server.py",
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
    "gate/pump_practice_graduation.py",
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

FORBIDDEN_RUNTIME_PATHS = (
    "broker/alpaca.py",
    "broker/ibkr.py",
    "backend/crypto_sandbox_server.py",
)

VERCEL_FUNCTION_ENTRYPOINT = "api/index.py"
VERCEL_ROUTE = {"src": "/(.*)", "dest": "/api/index?__sw_path=$1"}
FORBIDDEN_VERCEL_CONFIG_KEYS = ("buildCommand", "outputDirectory")


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


def validate_vercel_config(config: dict) -> dict:
    if "framework" not in config or config["framework"] is not None:
        raise RuntimeError("Vercel runtime must explicitly use the Other framework preset")

    for key in FORBIDDEN_VERCEL_CONFIG_KEYS:
        if key in config:
            raise RuntimeError(
                f"Vercel runtime must use automatic function build settings; remove {key}"
            )

    routes = config.get("routes")
    if not isinstance(routes, list) or VERCEL_ROUTE not in routes:
        raise RuntimeError("Vercel runtime is missing the canonical api/index.py route")

    return {
        "framework": "other",
        "function_entrypoint": VERCEL_FUNCTION_ENTRYPOINT,
        "build_command": "auto",
        "output_directory": "auto",
        "route_destination": VERCEL_ROUTE["dest"],
    }


def vercel_deployment_contract(root: Path) -> dict:
    config_path = root / "vercel.json"
    try:
        config = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Vercel runtime requires a valid vercel.json") from exc

    entrypoint = root / VERCEL_FUNCTION_ENTRYPOINT
    if not entrypoint.is_file():
        raise RuntimeError(
            f"Vercel runtime entrypoint is missing: {VERCEL_FUNCTION_ENTRYPOINT}"
        )

    return validate_vercel_config(config)


def _local_module_paths(root: Path, module: str) -> tuple[str, ...]:
    if not module:
        return ()
    relative = module.replace(".", "/")
    candidates = (f"{relative}.py", f"{relative}/__init__.py")
    return tuple(path for path in candidates if (root / path).is_file())


def missing_runtime_imports(root: Path, runtime_files: tuple[str, ...] = RUNTIME_FILES) -> list[str]:
    """Return first-party Python imports present in the repo but absent from the bundle."""
    packaged = set(runtime_files)
    missing: set[str] = set()
    for relative in runtime_files:
        if not relative.endswith(".py"):
            continue
        source = root / relative
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=relative)
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules.extend(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                modules.append(node.module)
            for module in modules:
                local_paths = _local_module_paths(root, module)
                if local_paths and not any(path in packaged for path in local_paths):
                    missing.update(local_paths)
    return sorted(missing)


def validate_runtime_import_closure(root: Path, runtime_files: tuple[str, ...] = RUNTIME_FILES) -> None:
    missing = missing_runtime_imports(root, runtime_files)
    if missing:
        raise RuntimeError(
            "Vercel runtime is missing first-party import dependencies: " + ", ".join(missing)
        )


def package_runtime(root: Path, output: Path, source_sha: str | None = None) -> dict:
    root = root.resolve()
    output = output.resolve()
    source_sha = (source_sha or git_head_sha(root)).strip().lower()
    if len(source_sha) != 40 or any(ch not in "0123456789abcdef" for ch in source_sha):
        raise ValueError("runtime bundle requires an exact 40-character git SHA")

    deployment_contract = vercel_deployment_contract(root)
    validate_runtime_import_closure(root)

    allowed = set(RUNTIME_FILES)
    forbidden = set(FORBIDDEN_RUNTIME_PATHS)
    if allowed & forbidden:
        raise RuntimeError("runtime allowlist overlaps forbidden executable adapters")

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

    for relative in FORBIDDEN_RUNTIME_PATHS:
        if (output / relative).exists():
            raise RuntimeError(f"forbidden runtime path was packaged: {relative}")

    payload = {
        "schema": "sleepwealth-vercel-runtime-bundle-v1",
        "source_sha": source_sha,
        "files": sorted(entries, key=lambda row: str(row["path"])),
        "deployment_contract": deployment_contract,
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
