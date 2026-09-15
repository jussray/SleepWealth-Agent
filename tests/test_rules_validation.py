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


def test_checked_in_schema_rejects_version_type_drift():
    rules = deepcopy(load_rules())
    rules["version"] = 4

    ok, errors = RulesValidator().validate(rules)

    assert not ok
    assert any(
        error.startswith("schema version:") and "not of type 'string'" in error
        for error in errors
    )


def test_checked_in_schema_rejects_unknown_lane_fields():
    rules = deepcopy(load_rules())
    rules["lanes"]["crypto"]["execution_adapter"] = "external"

    ok, errors = RulesValidator().validate(rules)

    assert not ok
    assert any(
        error.startswith("schema lanes.crypto:") and "Additional properties" in error
        for error in errors
    )


def test_closed_schema_rejects_unknown_authority_shaped_fields():
    cases = (
        ((), "live_execution", True, "schema $:"),
        (("capital_ladder",), "wallet", "external", "schema capital_ladder:"),
        (("modes",), "broker", "external", "schema modes:"),
        (("ceiling",), "auto_execute", True, "schema ceiling:"),
    )

    for path, key, value, prefix in cases:
        rules = deepcopy(load_rules())
        target = rules
        for segment in path:
            target = target[segment]
        target[key] = value

        ok, errors = RulesValidator().validate(rules)

        assert not ok
        assert any(
            error.startswith(prefix) and "Additional properties" in error
            for error in errors
        )


def test_schema_rejects_non_object_root_without_policy_crash():
    ok, errors = RulesValidator().validate([])

    assert not ok
    assert any(error.startswith("schema $:") and "not of type 'object'" in error for error in errors)


def test_invalid_schema_definition_fails_closed():
    validator = RulesValidator(schema={"$schema": "http://json-schema.org/draft-07/schema#", "type": 42})

    ok, errors = validator.validate(load_rules())

    assert not ok
    assert len(errors) == 1
    assert errors[0].startswith("rules schema is invalid:")
