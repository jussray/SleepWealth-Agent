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
