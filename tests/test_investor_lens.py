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
