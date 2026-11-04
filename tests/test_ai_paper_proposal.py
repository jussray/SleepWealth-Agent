import asyncio

import pytest

from gate.ai_paper_proposal import (
    CONTRACT,
    MAX_PAPER_QTY,
    evaluate_paper_proposal,
    run_ai_paper_proposal,
)

GOOD = {"action": "paper_cycle", "lane": "stock-market", "symbol": "aapl", "side": "buy", "qty": 0.5}


def _fake_run(calls):
    async def run(**kwargs):
        calls.append(kwargs)
        return {"paper_only": True, "live_execution": False}

    return run


def test_valid_paper_proposal_is_accepted_and_normalized():
    r = evaluate_paper_proposal(GOOD)
    assert r["status"] == "ACCEPTED_FOR_PAPER_CYCLE"
    assert r["contract"] == CONTRACT
    assert r["live_execution_authorized"] is False
    assert r["authorizes_real_money"] is False
    assert r["normalized"] == {"lane": "stock-market", "symbol": "AAPL", "side": "buy", "qty": 0.5}


@pytest.mark.parametrize(
    "field",
    ["mode", "broker", "live", "approval", "human_approved", "wallet", "api_key"],
)
def test_proposal_cannot_smuggle_live_broker_or_approval_fields(field):
    r = evaluate_paper_proposal({**GOOD, field: "x"})
    assert r["status"] == "REJECTED"
    assert f"unexpected_field:{field}" in r["errors"]


def test_only_allowlisted_action_is_accepted():
    r = evaluate_paper_proposal({**GOOD, "action": "live_order"})
    assert r["status"] == "REJECTED"
    assert "action_not_allowlisted" in r["errors"]


@pytest.mark.parametrize("lane", ["forex", "live-market"])
def test_unsupported_lane_is_rejected(lane):
    r = evaluate_paper_proposal({**GOOD, "lane": lane})
    assert "unsupported_lane" in r["errors"]


@pytest.mark.parametrize("lane", ["", "   ", None])
def test_blank_or_missing_lane_is_rejected_not_defaulted(lane):
    # normalize_lane() would silently default these to stock-market; the AI seam must not.
    r = evaluate_paper_proposal({**GOOD, "lane": lane})
    assert r["status"] == "REJECTED"
    assert "lane_required" in r["errors"]


@pytest.mark.parametrize("qty", [0, -1, MAX_PAPER_QTY + 0.01, True, float("nan"), "1", float("inf")])
def test_qty_outside_paper_cap_or_non_numeric_is_rejected(qty):
    r = evaluate_paper_proposal({**GOOD, "qty": qty})
    assert r["status"] == "REJECTED"
    assert any(e.startswith("qty_") for e in r["errors"])


def test_non_mapping_proposal_is_rejected():
    assert evaluate_paper_proposal("buy AAPL")["errors"] == ["proposal_must_be_object"]
    assert evaluate_paper_proposal(None)["status"] == "REJECTED"


def test_without_human_approval_no_paper_cycle_runs():
    calls = []
    r = asyncio.run(run_ai_paper_proposal(GOOD, human_approved=False, run=_fake_run(calls)))
    assert r["status"] == "HOLD_HUMAN_APPROVAL_REQUIRED"
    assert r["cycle"] is None
    assert calls == []


def test_rejected_proposal_never_reaches_runner_even_if_human_approved():
    calls = []
    r = asyncio.run(
        run_ai_paper_proposal({**GOOD, "side": "short"}, human_approved=True, run=_fake_run(calls))
    )
    assert r["status"] == "REJECTED"
    assert calls == []


def test_human_approved_proposal_runs_exactly_one_paper_cycle_with_normalized_inputs():
    calls = []
    r = asyncio.run(run_ai_paper_proposal(GOOD, human_approved=True, run=_fake_run(calls)))
    assert r["status"] == "PAPER_CYCLE_COMPLETE"
    assert r["cycle"]["live_execution"] is False
    assert calls == [{"symbol": "AAPL", "qty": 0.5, "side": "buy", "lane": "stock-market"}]


def test_fingerprint_is_stable_and_changes_with_content():
    a = evaluate_paper_proposal(GOOD)["fingerprint"]
    assert a == evaluate_paper_proposal(dict(GOOD))["fingerprint"]
    assert a != evaluate_paper_proposal({**GOOD, "qty": 0.25})["fingerprint"]
