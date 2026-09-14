from engine.truth_mode import (
    TRUTH_DECISION_CONTRACT,
    build_capital_truth_receipt,
    build_paper_cycle_truth_receipt,
    capital_decision_fingerprint,
)
from backend.runtime_server import capital_truth_payload


def _paper_result(status="executed", stage="complete"):
    return {
        "status": status,
        "stage": stage,
        "mode": "paper",
        "lane": "stock-market",
        "market_observation": {
            "fingerprint": "market-fp",
            "read_only": True,
        },
        "continuity": {
            "decision_fingerprint": "decision-fp",
            **({"outcome_fingerprint": "outcome-fp"} if status == "executed" else {}),
        },
    }


def _rules():
    return {
        "ceiling": {"current": 20.0, "max": 100.0, "can_auto_increase": False},
        "capital_ladder": {
            "enabled": True,
            "paper_only": True,
            "min_net_margin_pct": 20.0,
            "max_days_held": 14,
            "promotion_wins_required": 3,
            "protected_profit_pct": 30.0,
            "max_step_multiplier": 1.5,
            "max_cycle_loss_pct": 20.0,
            "can_auto_promote": False,
        },
    }


def test_paper_truth_receipt_separates_truth_planes_and_stays_non_authorizing():
    receipt = build_paper_cycle_truth_receipt(_paper_result())

    assert receipt["schema"] == TRUTH_DECISION_CONTRACT
    assert receipt["authority"] == "decision_support_only"
    assert receipt["authorizes"] is False
    assert receipt["truth_planes"]["source"]["state"] == "OBSERVED"
    assert receipt["truth_planes"]["execution"]["state"] == "VERIFIED"
    assert receipt["truth_planes"]["outcome"]["state"] == "VERIFIED"
    assert receipt["decision"] == "MEASURE"
    assert receipt["continuity_cookie"].startswith("sw-truth-cookie-v1:")
    assert "live execution authority" in receipt["does_not_prove"]


def test_blocked_paper_cycle_keeps_failed_execution_separate_from_unknown_outcome():
    receipt = build_paper_cycle_truth_receipt(
        _paper_result(status="blocked", stage="evaluator")
    )

    assert receipt["truth_planes"]["source"]["state"] == "OBSERVED"
    assert receipt["truth_planes"]["execution"]["state"] == "BLOCKED"
    assert receipt["truth_planes"]["outcome"]["state"] == "UNKNOWN"
    assert receipt["decision"] == "HOLD_OR_REVIEW"
    assert receipt["proof"]["stage"] == "evaluator"


def test_changed_capital_fingerprint_invalidates_predecessor_proof():
    cycles = [
        {
            "buy_cost": 10.0,
            "sale_proceeds": 14.0,
            "fees": 1.0,
            "other_costs": 0.0,
            "days_held": 3,
        }
    ]
    history = {
        "cycles": 1,
        "qualified_cycles": 1,
        "failed_cycles": 0,
        "current_qualified_streak": 1,
        "failure_rate_pct": 0.0,
        "win_rate_pct": 100.0,
        "net_roi_pct": 30.0,
        "profit_per_capital_day_pct": 10.0,
        "promotion_ready": False,
        "effective_limit": 20.0,
        "suggested_next_limit": 20.0,
        "latest_status": "hold",
    }
    stale = "sw-capital-subject-v1:" + ("0" * 64)
    receipt = build_capital_truth_receipt(
        history,
        cycles,
        _rules(),
        current_fingerprint=stale,
    )

    assert receipt["fresh"] is False
    assert receipt["decision"] == "REOBSERVE"
    assert receipt["truth_planes"]["source"]["state"] == "BLOCKED"
    assert receipt["truth_planes"]["execution"]["state"] == "UNKNOWN"
    assert receipt["truth_planes"]["outcome"]["state"] == "UNKNOWN"
    assert "historical evidence" in receipt["confess"][0].lower()


def test_capital_truth_fingerprint_is_deterministic_for_same_evidence():
    cycles = [{"buy_cost": 10.0, "sale_proceeds": 14.0, "days_held": 3}]
    first = capital_decision_fingerprint(cycles, _rules())
    second = capital_decision_fingerprint(cycles, _rules())

    assert first == second
    assert first.startswith("sw-capital-subject-v1:")


def test_runtime_capital_truth_proposes_review_after_repeated_paper_proof():
    payload = {
        "cycles": [
            {
                "buy_cost": 4.0,
                "sale_proceeds": 6.0,
                "fees": 0.5,
                "days_held": 3,
            },
            {
                "buy_cost": 4.0,
                "sale_proceeds": 6.0,
                "fees": 0.5,
                "days_held": 3,
            },
            {
                "buy_cost": 4.0,
                "sale_proceeds": 6.0,
                "fees": 0.5,
                "days_held": 3,
            },
        ]
    }

    result = capital_truth_payload(payload)
    ladder = result["capital_ladder"]
    receipt = ladder["truthmode"]

    assert result["mode"] == "paper"
    assert result["live_execution"] is False
    assert ladder["promotion_ready"] is True
    assert receipt["decision"] == "PROPOSE_PROMOTION_REVIEW"
    assert receipt["authority"] == "decision_support_only"
    assert receipt["authorizes"] is False
    assert "automatic promotion" in receipt["does_not_prove"]


def test_runtime_capital_truth_empty_history_measures_instead_of_guessing():
    result = capital_truth_payload({"cycles": []})
    receipt = result["capital_ladder"]["truthmode"]

    assert receipt["decision"] == "MEASURE"
    assert receipt["truth_planes"]["source"]["state"] == "UNKNOWN"
    assert receipt["truth_planes"]["execution"]["state"] == "UNKNOWN"
    assert receipt["truth_planes"]["outcome"]["state"] == "UNKNOWN"
