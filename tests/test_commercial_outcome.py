import pytest

from race.commercial_outcome import commercial_outcome_receipt


def test_receipt_never_self_verifies_or_authorizes():
    receipt = commercial_outcome_receipt(
        lane="software", currency="USD", gross_revenue="100.00",
        costs="35.50", payment_evidence_sha256="a" * 64,
        delivery_evidence_sha256="b" * 64,
    )
    assert receipt["net_profit"] == "64.50"
    assert receipt["truth_state"] == "UNVERIFIED"
    assert receipt["profit_verified"] is False
    assert receipt["authorizes"] is False
    assert receipt["allocation_authorized"] is False
    assert receipt["execution_authorized"] is False
    assert receipt["continuity_cookie"].startswith("sw-commercial-v1:")
    assert receipt == commercial_outcome_receipt(
        lane="software", currency="USD", gross_revenue="100.00",
        costs="35.50", payment_evidence_sha256="a" * 64,
        delivery_evidence_sha256="b" * 64,
    )


@pytest.mark.parametrize("amount", ["NaN", "-1", "1.001", 1.5, True])
def test_invalid_amount_rejected(amount):
    with pytest.raises(ValueError):
        commercial_outcome_receipt(lane="service", currency="USD", gross_revenue=amount, costs="0")


def test_untrusted_verification_and_digest_rejected():
    with pytest.raises(ValueError):
        commercial_outcome_receipt(lane="service", currency="USD", gross_revenue="5", costs="0", evidence_verified=True)
    with pytest.raises(ValueError):
        commercial_outcome_receipt(lane="service", currency="USD", gross_revenue="5", costs="0", payment_evidence_sha256="fake")
