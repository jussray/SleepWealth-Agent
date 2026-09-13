from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


MAIN_BRANCH = "main"


def evaluate_associated_prs(prs: list[dict[str, Any]], commit_sha: str) -> dict[str, Any]:
    """Classify whether commit_sha is the merge commit of a merged PR into main."""
    if not prs:
        return {
            "verified": False,
            "classification": "NO_ASSOCIATED_PR",
            "reason": "commit has no associated pull request",
            "pull_request": None,
        }

    merged = [pr for pr in prs if pr.get("merged_at")]
    if not merged:
        return {
            "verified": False,
            "classification": "UNMERGED_PR",
            "reason": "associated pull request exists but is not merged",
            "pull_request": None,
        }

    main_merges = [
        pr for pr in merged if (pr.get("base") or {}).get("ref") == MAIN_BRANCH
    ]
    if not main_merges:
        return {
            "verified": False,
            "classification": "WRONG_BASE",
            "reason": "associated merged pull request did not target main",
            "pull_request": None,
        }

    exact = [pr for pr in main_merges if pr.get("merge_commit_sha") == commit_sha]
    if not exact:
        return {
            "verified": False,
            "classification": "MERGE_SHA_MISMATCH",
            "reason": "main commit is not the recorded merge commit for its associated pull request",
            "pull_request": None,
        }

    pr = sorted(exact, key=lambda item: item.get("number", 0))[0]
    return {
        "verified": True,
        "classification": "VERIFIED_MERGED_PR",
        "reason": "commit is the recorded merge commit of a merged pull request into main",
        "pull_request": {
            "number": pr.get("number"),
            "html_url": pr.get("html_url"),
            "merged_at": pr.get("merged_at"),
            "merge_commit_sha": pr.get("merge_commit_sha"),
            "base": (pr.get("base") or {}).get("ref"),
            "head": (pr.get("head") or {}).get("ref"),
        },
    }


def fetch_associated_prs(repository: str, commit_sha: str, token: str) -> list[dict[str, Any]]:
    api_url = os.environ.get("GITHUB_API_URL", "https://api.github.com").rstrip("/")
    url = f"{api_url}/repos/{repository}/commits/{commit_sha}/pulls"
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "sleepwealth-main-provenance-witness",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        payload = json.load(response)
    if not isinstance(payload, list):
        raise ValueError("GitHub associated-pulls response was not a list")
    return payload


def write_receipt(receipt: dict[str, Any]) -> None:
    path = Path(
        os.environ.get(
            "MAIN_PROVENANCE_RECEIPT",
            "artifacts/main-provenance.json",
        )
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> int:
    repository = os.environ.get("GITHUB_REPOSITORY", "")
    commit_sha = os.environ.get("GITHUB_SHA", "")
    token = os.environ.get("GITHUB_TOKEN", "")

    receipt: dict[str, Any] = {
        "event": "main_provenance_checked",
        "repository": repository,
        "commit_sha": commit_sha,
        "target_branch": MAIN_BRANCH,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }

    missing = [
        name
        for name, value in (
            ("GITHUB_REPOSITORY", repository),
            ("GITHUB_SHA", commit_sha),
            ("GITHUB_TOKEN", token),
        )
        if not value
    ]
    if missing:
        receipt.update(
            {
                "verified": False,
                "classification": "MISSING_RUNTIME_CONTEXT",
                "reason": f"missing required runtime context: {', '.join(missing)}",
                "pull_request": None,
            }
        )
        write_receipt(receipt)
        print(json.dumps(receipt, indent=2, sort_keys=True))
        return 2

    try:
        prs = fetch_associated_prs(repository, commit_sha, token)
        receipt.update(evaluate_associated_prs(prs, commit_sha))
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ValueError) as exc:
        receipt.update(
            {
                "verified": False,
                "classification": "GITHUB_API_ERROR",
                "reason": f"provenance lookup failed: {exc}",
                "pull_request": None,
            }
        )

    write_receipt(receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))
    return 0 if receipt.get("verified") else 1


if __name__ == "__main__":
    sys.exit(main())
