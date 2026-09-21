from dataclasses import replace

from portfolio.money_router import (
    Evidence,
    FinancialState,
    MoneyPath,
    Opportunity,
    decide,
    deployable_cash,
    rank_opportunities,
)


def evidence(*, verified=True, identity="e1"):
    return Evidence(
        id=identity,
        kind="payment",
        verified=verified,
        source="test",
        timestamp="2026-09-20T00:00:00+00:00",
    )


def opportunity(**overrides):
    base = Opportunity(
        id="offer-1",
        name="Test offer",
        project="SleepWealth",
        stage="TEST",
        evidence=(evidence(),),
        capital_required=10,
        founder_hours_required=2,
        max_loss=10,
        reversibility_risk=0.1,
        compounding_value=0.8,
        successful_cycles=1,
        repeated_cycles=1,
        kill_after_failures=3,
        failures=0,
        money_path=MoneyPath(
            payer="customer",
            offer="bounded service",
            price=100,
            unit_cost=20,
            conversion_probability=0.5,
            repeatable=True,
            proven=True,
            cycle_days=7,
        ),
    )
    return replace(base, **overrides)


def finances(**overrides):
    base = FinancialState(
        liquid_cash=1000,
        survival_floor=700,
        safety_buffer=200,
        experiment_budget=50,
    )
    return replace(base, **overrides)


def test_deployable_cash_protects_floor_and_buffer():
    assert deployable_cash(finances()) == 100


def test_zero_cost_discovery_is_not_blocked_when_no_cash_is_deployable():
    item = opportunity(capital_required=0, money_path=None, evidence=())
    receipt = decide(item, finances(liquid_cash=900))
    assert receipt.decision == "DISCOVER"
    assert receipt.authorizes_spending is False
    assert receipt.authorizes_execution is False
    assert receipt.real_money is False


def test_protected_cash_blocks_capitalized_test():
    receipt = decide(opportunity(capital_required=25), finances(liquid_cash=900))
    assert receipt.decision == "BLOCK"
    assert "protected cash" in " ".join(receipt.reasons)


def test_borrowing_leverage_or_loss_chasing_is_blocked():
    assert decide(opportunity(uses_borrowing=True), finances()).decision == "BLOCK"
    assert decide(opportunity(uses_leverage=True), finances()).decision == "BLOCK"
    assert decide(opportunity(chasing_loss=True), finances()).decision == "BLOCK"


def test_missing_verified_evidence_returns_verify():
    item = opportunity(evidence=(evidence(verified=False),))
    receipt = decide(item, finances())
    assert receipt.decision == "VERIFY"


def test_failure_threshold_kills_before_more_testing():
    item = opportunity(failures=3, kill_after_failures=3)
    assert decide(item, finances()).decision == "KILL"


def test_one_cycle_does_not_grant_compound():
    assert decide(opportunity(repeated_cycles=1), finances()).decision == "TEST"


def test_non_positive_margin_kills_even_with_repeated_cycles():
    bad_path = replace(opportunity().money_path, price=20, unit_cost=20)
    item = opportunity(money_path=bad_path, repeated_cycles=3, successful_cycles=3)
    assert decide(item, finances()).decision == "KILL"


def test_repeated_positive_path_can_recommend_compound_without_authority():
    item = opportunity(repeated_cycles=2, successful_cycles=2)
    receipt = decide(item, finances())
    assert receipt.decision == "COMPOUND"
    assert receipt.authority == "decision-support-only"
    assert receipt.authorizes_spending is False
    assert receipt.authorizes_execution is False
    assert receipt.real_money is False
    assert len(receipt.fingerprint) == 64
    assert len(receipt.continuity_cookie_hash) == 64


def test_fingerprint_changes_when_evidence_changes():
    item = opportunity(repeated_cycles=2, successful_cycles=2)
    first = decide(item, finances())
    changed = replace(item, evidence=(evidence(identity="e2"),))
    second = decide(changed, finances(), previous_cookie_hash=first.continuity_cookie_hash)
    assert first.fingerprint != second.fingerprint
    assert second.previous_cookie_hash == first.continuity_cookie_hash


def test_rank_prefers_compound_over_test_when_both_are_allowed():
    compound = opportunity(id="compound", repeated_cycles=2, successful_cycles=2)
    test = opportunity(id="test", repeated_cycles=1, successful_cycles=1)
    ranked = rank_opportunities((test, compound), finances())
    assert ranked[0][0].id == "compound"
    assert ranked[0][1].decision == "COMPOUND"
