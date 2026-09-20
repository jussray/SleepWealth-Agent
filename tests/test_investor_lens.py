from datetime import UTC, datetime

from engine.evaluator import ProposalEvaluator
from market.investor_lens import build_investor_lens_policy_receipt


def _rules() -> dict:
    return {
        "version": "test",
        "floor_cash": 5.0,
        "max_position_size": 1000.0,
        "symbol_scope": "observable-market",
        "approved_symbols": ["AAPL"],
        "ceiling": {"current": 5.0, "can_auto_increase": False},
    }


def test_investor_lens_is_weighted_and_non_authorizing():
    receipt = build_investor_lens_policy_receipt(datetime(2026, 9, 19, tzinfo=UTC))

    assert receipt["schema"] == "sleepwealth-investor-lens-v1"
    assert receipt["fingerprint"].startswith("sw-investor-lens-v1:")
    assert round(sum(lens["weight"] for lens in receipt["lenses"]), 8) == 1.0
    assert receipt["fresh_overlay_ids"] == [
        "ai_modern_mercantilism",
        "credit_expansion_watch",
    ]
    assert receipt["stale_overlay_ids"] == []

    boundaries = receipt["boundaries"]
    assert boundaries == {
        "authority": "none",
        "decision_support_only": True,
        "paper_only": True,
        "real_money": False,
        "live_execution": False,
        "execution_authorized": False,
        "contains_order_instructions": False,
        "can_change_order_allowed": False,
    }


def test_manager_holdings_are_zero_weight_context_only():
    receipt = build_investor_lens_policy_receipt(datetime(2026, 9, 19, tzinfo=UTC))
    copycat = receipt["copycat_context"]

    assert copycat["source_type"] == "SEC Form 13F holdings"
    assert copycat["signal_weight"] == 0.0
    assert "never become a buy, sell" in copycat["rule"]


def test_richest_builders_snapshot_is_descriptive_not_a_trade_signal():
    receipt = build_investor_lens_policy_receipt(datetime(2026, 9, 19, tzinfo=UTC))
    snapshot = receipt["richest_builders_snapshot"]

    assert snapshot["source_date"] == "2026-09-01"
    assert snapshot["ranking_signal_weight"] == 0.0
    assert snapshot["descriptive_only"] is True
    assert [row["name"] for row in snapshot["people"]] == [
        "Elon Musk",
        "Larry Page",
        "Jeff Bezos",
        "Sergey Brin",
        "Michael Dell",
        "Mark Zuckerberg",
        "Larry Ellison",
        "Jensen Huang",
        "Steve Ballmer",
        "Amancio Ortega",
    ]
    assert "never become security selection" in snapshot["rule"]


def test_wealth_formation_patterns_separate_creation_from_portfolio_advice():
    receipt = build_investor_lens_policy_receipt(datetime(2026, 9, 19, tzinfo=UTC))
    patterns = receipt["wealth_formation_patterns"]

    assert round(sum(row["weight"] for row in patterns), 8) == 1.0
    by_id = {row["id"]: row for row in patterns}
    assert "productive operating businesses" in by_id["productive_ownership"]["observation"]
    assert "does not establish" in by_id["creation_vs_preservation"]["observation"]
    assert "diversification" in by_id["creation_vs_preservation"]["application"]


def test_real_money_path_is_readiness_only_and_cannot_execute():
    receipt = build_investor_lens_policy_receipt(datetime(2026, 9, 19, tzinfo=UTC))
    path = receipt["real_money_readiness_path"]

    assert path["schema"] == "sleepwealth-real-money-readiness-v1"
    assert path["status"] == "readiness-only"
    assert path["repo_execution_capability"] == "none"
    assert path["execution_authorized"] is False
    assert path["live_execution"] is False
    assert path["real_money"] is False

    stage_ids = [row["id"] for row in path["stages"]]
    assert stage_ids == [
        "lawful_surplus",
        "survival_liquidity",
        "evidence_backed_ownership_thesis",
        "diversification_and_loss_check",
        "legal_eligibility_and_account_authority",
        "repeated_paper_proof",
        "explicit_external_human_decision",
    ]
    legal_gate = next(
        row["gate"] for row in path["stages"] if row["id"] == "legal_eligibility_and_account_authority"
    )
    assert "never bypass eligibility or supervision rules" in legal_gate
    assert "outside this repository" in path["stages"][-1]["gate"]


def test_regime_overlays_expire_instead_of_becoming_permanent_rules():
    receipt = build_investor_lens_policy_receipt(datetime(2028, 1, 1, tzinfo=UTC))

    assert receipt["fresh_overlay_ids"] == []
    assert receipt["stale_overlay_ids"] == [
        "ai_modern_mercantilism",
        "credit_expansion_watch",
    ]
    assert all(row["fresh"] is False for row in receipt["regime_overlays"])


def test_evaluator_carries_research_receipt_without_widening_authority():
    evaluator = ProposalEvaluator(_rules())
    receipt = evaluator.investor_lens

    assert evaluator.ceiling == 5.0
    assert receipt["boundaries"]["authority"] == "none"
    assert receipt["boundaries"]["can_change_order_allowed"] is False
    assert receipt["boundaries"]["execution_authorized"] is False
    assert receipt["real_money_readiness_path"]["execution_authorized"] is False
