from pathlib import Path


def test_main_push_ci_fails_closed_on_provenance():
    workflow = Path(".github/workflows/ci.yml").read_text(encoding="utf-8")

    assert "pull-requests: read" in workflow
    assert "Gate main pushes by merged-PR provenance" in workflow
    assert "if: github.event_name == 'push'" in workflow
    assert "python governance/main_provenance.py" in workflow
    assert "MAIN_PROVENANCE_RECEIPT: artifacts/main-provenance-ci.json" in workflow
    assert "Upload CI provenance receipt" in workflow
    assert "ci-main-provenance-receipt" in workflow

    gate_index = workflow.index("Gate main pushes by merged-PR provenance")
    install_index = workflow.index("- name: Install")
    assert gate_index < install_index


def test_render_waits_for_all_github_checks():
    blueprint = Path("render.yaml").read_text(encoding="utf-8")

    assert "autoDeployTrigger: checksPass" in blueprint
    assert "buildCommand: pip install -e ." in blueprint
    assert "ibkr-readonly" not in blueprint
