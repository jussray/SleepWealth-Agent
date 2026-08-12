from engine.validator import RulesValidator
from rules import load_rules


def test_shipped_rules_are_valid():
    ok, errors = RulesValidator().validate(load_rules())
    assert ok, errors


def test_negative_floor_rejected():
    ok, errors = RulesValidator().validate(
        {"version": "1", "floor_cash": -5, "ceiling": {"current": 5, "can_auto_increase": False}}
    )
    assert not ok
    assert any("floor_cash" in e for e in errors)


def test_auto_increase_ceiling_rejected():
    """The human-only ladder is load-bearing. Config cannot opt out."""
    ok, errors = RulesValidator().validate(
        {"version": "1", "floor_cash": 5, "ceiling": {"current": 5, "can_auto_increase": True}}
    )
    assert not ok
    assert any("can_auto_increase" in e for e in errors)
