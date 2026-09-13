from pathlib import Path


def test_render_blueprint_stays_paper_lab_only():
    blueprint = Path("render.yaml").read_text(encoding="utf-8")

    assert "name: sleepwealth-paper-lab" in blueprint
    assert "buildCommand: pip install -e ." in blueprint
    assert "ibkr-readonly" not in blueprint
    assert "startCommand: python -m backend.runtime_server" in blueprint
    assert "healthCheckPath: /health" in blueprint
    assert "autoDeployTrigger: checksPass" in blueprint

    forbidden = (
        "broker.ibkr",
        "submit_order",
        "placeOrder",
        "wallet",
        "private_key",
        "seed_phrase",
        "live-trade",
        "funding",
        "transfer",
    )
    assert not any(term in blueprint for term in forbidden)
