from copy import deepcopy

from engine.validator import RulesValidator
from rules import load_rules


def test_shipped_rules_are_valid():
    ok, errors = RulesValidator().validate(load_rules())
    assert ok, errors


def test_negative_floor_rejected():
    rules = deepcopy(load_rules())
    rules["floor_cash"] = -5
    ok, errors = RulesValidator().validate(rules)
    assert not ok
    assert any("floor_cash" in error for error in errors)


def test_auto_increase_ceiling_rejected():
    """The human-only ladder is load-bearing. Config cannot opt out."""
    rules = deepcopy(load_rules())
    rules["ceiling"]["can_auto_increase"] = True
    ok, errors = RulesValidator().validate(rules)
    assert not ok
    assert any("can_auto_increase" in error for error in errors)


def test_stock_lane_cannot_lose_us_listed_scope():
    rules = deepcopy(load_rules())
    rules["lanes"]["stock-market"]["symbol_scope"] = "classified-observation"
    ok, errors = RulesValidator().validate(rules)
    assert not ok
    assert any("stock-market.symbol_scope" in error for error in errors)


def test_crypto_lane_cannot_merge_into_stock_scope():
    rules = deepcopy(load_rules())
    rules["lanes"]["crypto"]["symbol_scope"] = "us-listed-directory"
    ok, errors = RulesValidator().validate(rules)
    assert not ok
    assert any("crypto.symbol_scope" in error for error in errors)


def test_each_lane_must_remain_paper_only():
    for lane in ("stock-market", "crypto"):
        rules = deepcopy(load_rules())
        rules["lanes"][lane]["paper_only"] = False
        ok, errors = RulesValidator().validate(rules)
        assert not ok
        assert any(f"lanes.{lane}.paper_only" in error for error in errors)
