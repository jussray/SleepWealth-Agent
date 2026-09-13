import pytest

from engine.capital_ladder import CapitalLadder, FlipCycle
from engine.validator import RulesValidator


def rules(**ladder_overrides):
    ladder = {
        "enabled": True,
        "paper_only": True,
        "min_net_margin_pct": 20.0,
        "max_days_held": 14,
        "promotion_wins_required": 3,
        "protected_profit_pct": 30.0,
        "max_step_multiplier": 1.5,
        "max_cycle_loss_pct": 20.0,
        "can_auto_promote": False,
    }
    ladder.update(ladder_overrides)
    return {
        "version": "test",
        "floor_cash": 5.0,
        "ceiling": {
            "current": 20.0,
            "max": 100.0,
            "can_auto_increase": False,
        },
        "capital_ladder": ladder,
    }


def test_third_qualified_win_recommends_human_review_without_raising_limit():
    policy_rules = rules()
    before = policy_rules["ceiling"].copy()
    result = CapitalLadder(policy_rules).assess(
        FlipCycle(
            buy_cost=15.0,
            sale_proceeds=22.0,
            fees=1.0,
            days_held=5,
        ),
        prior_qualified_wins=2,
    )

    assert result["status"] == "promotion_ready"
    assert result["qualified"] is True
    assert result["effective_limit"] == 20.0
    assert result["suggested_next_limit"] == 30.0
    assert result["authority"] == "advisory"
    assert result["can_auto_increase"] is False
    assert policy_rules["ceiling"] == before


def test_low_margin_holds_and_does_not_advance_streak():
    result = CapitalLadder(rules()).assess(
        FlipCycle(
            buy_cost=15.0,
            sale_proceeds=18.0,
            fees=1.0,
            days_held=3,
        ),
        prior_qualified_wins=2,
    )

    assert result["status"] == "hold"
    assert result["qualified"] is False
    assert result["qualified_wins"] == 2
    assert "proof threshold" in result["reason"]


def test_loss_threshold_pauses_scaling():
    result = CapitalLadder(rules()).assess(
        FlipCycle(
            buy_cost=20.0,
            sale_proceeds=15.0,
            fees=0.0,
            days_held=2,
        ),
        prior_qualified_wins=8,
    )

    assert result["status"] == "pause"
    assert result["qualified"] is False
    assert result["suggested_next_limit"] == 20.0


def test_cycle_above_human_ceiling_is_blocked_even_if_profitable():
    result = CapitalLadder(rules()).assess(
        FlipCycle(
            buy_cost=21.0,
            sale_proceeds=40.0,
            fees=0.0,
            days_held=1,
        ),
        prior_qualified_wins=10,
    )

    assert result["status"] == "blocked"
    assert result["qualified"] is False
    assert "human-owned" in result["reason"]


def test_profit_split_protects_a_configured_share():
    result = CapitalLadder(rules(protected_profit_pct=25.0)).assess(
        FlipCycle(
            buy_cost=10.0,
            sale_proceeds=20.0,
            fees=2.0,
            days_held=1,
        )
    )

    assert result["cycle"]["net_profit"] == 8.0
    assert result["profit_split"]["protected"] == 2.0
    assert result["profit_split"]["reinvestable"] == 6.0


def test_suggested_step_is_capped_by_human_configured_max():
    policy_rules = rules(max_step_multiplier=3.0)
    policy_rules["ceiling"]["current"] = 40.0
    policy_rules["ceiling"]["max"] = 50.0

    result = CapitalLadder(policy_rules).assess(
        FlipCycle(
            buy_cost=20.0,
            sale_proceeds=30.0,
            fees=0.0,
            days_held=1,
        ),
        prior_qualified_wins=2,
    )

    assert result["status"] == "promotion_ready"
    assert result["suggested_next_limit"] == 50.0
    assert result["effective_limit"] == 40.0


def test_rules_validator_rejects_auto_promotion():
    ok, errors = RulesValidator().validate(rules(can_auto_promote=True))

    assert ok is False
    assert any("capital_ladder.can_auto_promote" in error for error in errors)


def test_policy_refuses_non_paper_ladder():
    with pytest.raises(ValueError, match="paper_only"):
        CapitalLadder(rules(paper_only=False))


@pytest.mark.parametrize(
    "cycle",
    [
        FlipCycle(buy_cost=10.0, sale_proceeds=15.0, days_held=15),
        FlipCycle(buy_cost=10.0, sale_proceeds=11.0, days_held=1),
    ],
)
def test_slow_or_weak_cycles_do_not_promote(cycle):
    result = CapitalLadder(rules()).assess(cycle, prior_qualified_wins=99)

    assert result["status"] == "hold"
    assert result["qualified"] is False
    assert result["suggested_next_limit"] == result["effective_limit"]


def test_history_requires_three_consecutive_qualified_cycles():
    win = FlipCycle(10.0, 14.0, fees=1.0, days_held=3)
    result = CapitalLadder(rules()).assess_history([win, win, win])

    assert result["promotion_ready"] is True
    assert result["current_qualified_streak"] == 3
    assert result["effective_limit"] == 20.0
    assert result["suggested_next_limit"] == 30.0
    assert result["can_auto_increase"] is False


def test_weak_profitable_cycle_breaks_history_streak():
    win = FlipCycle(10.0, 14.0, fees=1.0, days_held=3)
    weak = FlipCycle(10.0, 11.0, days_held=3)
    result = CapitalLadder(rules()).assess_history([win, weak, win])

    assert result["promotion_ready"] is False
    assert result["current_qualified_streak"] == 1
    assert result["failed_cycles"] == 1
    assert result["failure_rate_pct"] == 33.33
    assert result["win_rate_pct"] == 100.0
    assert result["suggested_next_limit"] == 20.0


def test_history_reports_normalized_compounding_metrics_and_empty_state():
    policy = CapitalLadder(rules())
    empty = policy.assess_history([])

    assert empty["cycles"] == 0
    assert empty["net_roi_pct"] == 0.0
    assert empty["profit_per_capital_day_pct"] == 0.0
    assert empty["ceiling_turns_per_day"] == 0.0
    assert empty["latest_status"] == "no_data"

    result = policy.assess_history(
        [
            FlipCycle(10.0, 14.0, fees=1.0, days_held=2),
            FlipCycle(5.0, 8.0, fees=1.0, days_held=1),
        ]
    )

    assert result["total_deployed"] == 17.0
    assert result["total_net_profit"] == 5.0
    assert result["net_roi_pct"] == 29.41
    assert result["normalized_elapsed_days"] == 3
    assert result["capital_days"] == 28.0
    assert result["deployed_capital_per_day"] == 5.67
    assert result["profit_per_capital_day_pct"] == 17.8571
    assert result["ceiling_turns"] == 0.85
    assert result["ceiling_turns_per_day"] == 0.2833


def test_velocity_rate_is_scale_invariant():
    small_rules = rules()
    large_rules = rules()
    small_rules["ceiling"]["current"] = 20.0
    large_rules["ceiling"]["current"] = 200.0

    small = CapitalLadder(small_rules).assess_history(
        [FlipCycle(10.0, 12.0, days_held=2)]
    )
    large = CapitalLadder(large_rules).assess_history(
        [FlipCycle(100.0, 120.0, days_held=2)]
    )

    assert small["net_roi_pct"] == large["net_roi_pct"] == 20.0
    assert (
        small["profit_per_capital_day_pct"]
        == large["profit_per_capital_day_pct"]
        == 10.0
    )


def test_zero_day_cycle_uses_one_day_floor_for_rate_metrics():
    result = CapitalLadder(rules()).assess_history(
        [FlipCycle(10.0, 12.0, days_held=0)]
    )

    assert result["normalized_elapsed_days"] == 1
    assert result["capital_days"] == 10.0
    assert result["deployed_capital_per_day"] == 10.0
    assert result["profit_per_capital_day_pct"] == 20.0


def test_history_rejects_unvalidated_cycle_evidence():
    with pytest.raises(TypeError, match="FlipCycle"):
        CapitalLadder(rules()).assess_history([{"buy_cost": 1.0}])
