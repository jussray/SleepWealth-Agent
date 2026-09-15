from __future__ import annotations

import os
import re
from collections.abc import Mapping

from backend import runtime_bundle_identity

_SHA_RE = re.compile(r"^[0-9a-fA-F]{40}$")


def runtime_identity(env: Mapping[str, str] | None = None) -> dict[str, object]:
    """Return non-secret runtime/source identity without granting authority."""

    values = os.environ if env is None else env
    candidates = (
        ("render", values.get("RENDER_GIT_COMMIT")),
        ("sleepwealth-runtime", values.get("SLEEPWEALTH_RUNTIME_SHA")),
        ("github-actions", values.get("GITHUB_SHA")),
    )

    provider = "unknown"
    source_sha: str | None = None
    for candidate_provider, candidate_sha in candidates:
        normalized = str(candidate_sha or "").strip()
        if normalized:
            provider = candidate_provider
            source_sha = normalized.lower()
            break

    if source_sha is None:
        bundled = str(runtime_bundle_identity.SOURCE_SHA or "").strip().lower()
        if bundled:
            provider = runtime_bundle_identity.SOURCE_PROVIDER
            source_sha = bundled

    exact_source_known = bool(source_sha and _SHA_RE.fullmatch(source_sha))
    if not exact_source_known:
        source_sha = None
        provider = "unknown"

    repository = values.get("RENDER_GIT_REPO_SLUG") or values.get("GITHUB_REPOSITORY") or "unknown"
    branch = values.get("RENDER_GIT_BRANCH") or values.get("GITHUB_REF_NAME") or "unknown"

    return {
        "source_sha": source_sha,
        "source_provider": provider,
        "exact_source_known": exact_source_known,
        "repository": repository,
        "branch": branch,
        "render_service_id": values.get("RENDER_SERVICE_ID"),
        "execution_authorized": False,
        "truth": (
            "Runtime identity is observation evidence only. It does not grant, renew, or expand "
            "trading, funding, transfer, signing, or real-money authority."
        ),
    }
