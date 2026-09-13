from governance.main_provenance import evaluate_associated_prs


def _pr(*, number=1, merged_at="2026-09-13T20:00:00Z", merge_sha="abc123", base="main"):
    return {
        "number": number,
        "html_url": f"https://github.com/jussray/SleepWealth-Agent/pull/{number}",
        "merged_at": merged_at,
        "merge_commit_sha": merge_sha,
        "base": {"ref": base},
        "head": {"ref": "fix/example"},
    }


def test_merged_pr_into_main_is_verified():
    result = evaluate_associated_prs([_pr()], "abc123")
    assert result["verified"] is True
    assert result["classification"] == "VERIFIED_MERGED_PR"
    assert result["pull_request"]["number"] == 1


def test_direct_push_has_separate_no_pr_receipt():
    result = evaluate_associated_prs([], "abc123")
    assert result["verified"] is False
    assert result["classification"] == "NO_ASSOCIATED_PR"


def test_unmerged_pr_has_separate_receipt():
    result = evaluate_associated_prs([_pr(merged_at=None)], "abc123")
    assert result["verified"] is False
    assert result["classification"] == "UNMERGED_PR"


def test_wrong_base_has_separate_receipt():
    result = evaluate_associated_prs([_pr(base="release")], "abc123")
    assert result["verified"] is False
    assert result["classification"] == "WRONG_BASE"


def test_merge_sha_mismatch_has_separate_receipt():
    result = evaluate_associated_prs([_pr(merge_sha="different")], "abc123")
    assert result["verified"] is False
    assert result["classification"] == "MERGE_SHA_MISMATCH"
