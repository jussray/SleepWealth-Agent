import math

import pytest

from engine.capital_ladder import CapitalLadder, FlipCycle


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
        "ceiling": {"current": 20.0, "max": 100.0, "can_auto_increase": False},
        "capital_ladder": ladder,
    }


@pytest.mark.parametrize("value", [math.nan, math.inf, -math.inf])
def test_flip_cycle_rejects_non_finite_money_evidence(value):
    with pytest.raises(ValueError, match="must be finite"):
        FlipCycle(buy_cost=value, sale_proceeds=10.0)

    with pytest.raises(ValueError, match="must be finite"):
        FlipCycle(buy_cost=10.0, sale_proceeds=value)

    with pytest.raises(ValueError, match="must be finite"):
        FlipCycle(buy_cost=10.0, sale_proceeds=12.0, fees=value)

    with pytest.raises(ValueError, match="must be finite"):
        FlipCycle(buy_cost=10.0, sale_proceeds=12.0, other_costs=value)


def test_flip_cycle_rejects_boolean_numeric_evidence():
    with pytest.raises(TypeError, match="must be numeric"):
        FlipCycle(buy_cost=True, sale_proceeds=10.0)

    with pytest.raises(TypeError, match="days_held must be an integer"):
        FlipCycle(buy_cost=10.0, sale_proceeds=12.0, days_held=True)


@pytest.mark.parametrize(
    ("path", "value"),
    [
        ("current", math.nan),
        ("current", math.inf),
        ("max", math.inf),
    ],
)
def test_capital_ladder_rejects_non_finite_ceiling(path, value):
    policy_rules = rules()
    policy_rules["ceiling"][path] = value

    with pytest.raises(ValueError, match="must be finite"):
        CapitalLadder(policy_rules)


@pytest.mark.parametrize(
    "field",
    [
        "min_net_margin_pct",
        "protected_profit_pct",
        "max_step_multiplier",
        "max_cycle_loss_pct",
    ],
)
def test_capital_ladder_rejects_non_finite_policy_rates(field):
    with pytest.raises(ValueError, match="must be finite"):
        CapitalLadder(rules(**{field: math.nan}))


def test_prior_qualified_wins_rejects_boolean_shortcut():
    policy = CapitalLadder(rules())

    with pytest.raises(ValueError, match="non-negative integer"):
        policy.assess(FlipCycle(10.0, 15.0), prior_qualified_wins=True)
