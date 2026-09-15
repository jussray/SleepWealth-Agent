from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DEPLOY_WORKFLOW = ROOT / ".github/workflows/vercel-production-deploy.yml"
WITNESS_WORKFLOW = ROOT / ".github/workflows/vercel-deployed-runtime.yml"


def test_production_deploy_is_bound_to_canonical_sleepwealth_project():
    workflow = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert 'workflows: ["vercel runtime bundle"]' in workflow
    assert "VERCEL_ORG_ID: team_sf52tzvdJRIApjPJAq3kOc09" in workflow
    assert "VERCEL_PROJECT_ID: prj_caSYNLgnJINUvSHtvWDXSGfrFRc4" in workflow
    assert "VERCEL_PROJECT_NAME: sleepwealth-paper-lab" in workflow
    assert "VERCEL_TEAM_SLUG: raylene-s-projects" in workflow
    assert '--project "$VERCEL_PROJECT_ID"' in workflow
    assert '--scope "$VERCEL_TEAM_SLUG"' in workflow
    assert "--prod" in workflow


def test_production_deploy_consumes_exact_bundle_run_not_moving_main():
    workflow = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert "ref: ${{ github.event.workflow_run.head_sha }}" in workflow
    assert "actions/download-artifact@v4" in workflow
    assert "sleepwealth-vercel-runtime-${{ github.event.workflow_run.head_sha }}" in workflow
    assert "run-id: ${{ github.event.workflow_run.id }}" in workflow
    assert 'manifest["source_sha"] == os.environ["EXPECTED_HEAD_SHA"]' in workflow
    assert "backend/runtime_bundle_identity.py" in workflow


def test_production_deploy_fails_closed_without_secret_and_never_claims_outcome():
    workflow = DEPLOY_WORKFLOW.read_text(encoding="utf-8")

    assert "VERCEL_TOKEN: ${{ secrets.VERCEL_TOKEN }}" in workflow
    assert "VERCEL_TOKEN_MISSING" in workflow
    assert "VERCEL_DEPLOY_COMMAND_FAILED" in workflow
    assert "VERCEL_DEPLOY_URL_UNPROVED" in workflow
    assert "VERCEL_PROVIDER_ACCEPTED" in workflow
    assert '"provider_accepted": False' in workflow
    assert '"outcome_verified": False' in workflow
    assert '"execution_authorized": False' in workflow
    assert '"real_money": False' in workflow
    assert '"live_execution": False' in workflow
    assert "vercel@59.11.7 deploy artifacts/vercel-runtime" in workflow


def test_public_runtime_witness_runs_after_deploy_attempt_even_when_deploy_fails():
    workflow = WITNESS_WORKFLOW.read_text(encoding="utf-8")

    assert 'workflows: ["vercel production deploy"]' in workflow
    assert "if: github.event.workflow_run.head_branch == 'main'" in workflow
    assert "github.event.workflow_run.conclusion == 'success'" not in workflow
    assert "DEPLOY_WORKFLOW_CONCLUSION" in workflow
    assert "scripts/verify_vercel_deployed_runtime.py" in workflow
    assert "https://sleepwealth-paper-lab.vercel.app" in workflow
