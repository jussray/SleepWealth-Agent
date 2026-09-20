import pytest

from broker.provider_identity import provider_account_fingerprint


def test_provider_account_fingerprint_is_deterministic_and_order_independent():
    first = provider_account_fingerprint(
        "Alpaca",
        {"account_number": "010203ABCD", "account_id": "uuid-123"},
    )
    second = provider_account_fingerprint(
        "alpaca",
        {"account_id": "uuid-123", "account_number": "010203ABCD"},
    )

    assert first == second
    assert len(first) == 64


def test_provider_and_account_changes_invalidate_fingerprint():
    base = provider_account_fingerprint("alpaca", {"account_id": "uuid-123"})
    other_provider = provider_account_fingerprint("ibkr", {"account_id": "uuid-123"})
    other_account = provider_account_fingerprint("alpaca", {"account_id": "uuid-456"})

    assert base != other_provider
    assert base != other_account


def test_provider_account_fingerprint_requires_nonempty_subject():
    with pytest.raises(ValueError):
        provider_account_fingerprint("", {"account_id": "uuid-123"})
    with pytest.raises(ValueError):
        provider_account_fingerprint("alpaca", {})
    with pytest.raises(ValueError):
        provider_account_fingerprint("alpaca", {"account_id": ""})
