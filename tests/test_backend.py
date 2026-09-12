import pytest

from backend.server import run_paper_dry_run


@pytest.mark.asyncio
async def test_backend_executes_safe_fractional_paper_order(tmp_path):
    result = await run_paper_dry_run(
        symbol="AAPL",
        qty=0.04,
        side="buy",
        audit_log_path=str(tmp_path / "audit.log"),
    )

    assert result["status"] == "executed"
    assert result["mode"] == "paper"
    assert result["broker"] == "mock"
    assert result["live_execution"] is False
    assert result["execution"]["status"] == "filled"
    assert result["account_before"]["cash"] == 10000.0
    assert result["account_after"]["cash"] == 9996.0
    assert result["truth"] == "paper simulation only; no real money moved"


@pytest.mark.asyncio
async def test_backend_preserves_five_dollar_ceiling(tmp_path):
    result = await run_paper_dry_run(
        symbol="AAPL",
        qty=0.06,
        side="buy",
        audit_log_path=str(tmp_path / "audit.log"),
    )

    assert result["status"] == "blocked"
    assert result["stage"] == "evaluator"
    assert "exceeds ceiling $5.00" in result["reason"]
    assert "execution" not in result
