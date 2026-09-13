"""External broker compatibility modules must remain unusable."""

import pytest

from broker.ibkr import ExternalBrokerDisabled, IBKRBroker, PAPER_PORTS


def test_ibkr_constructor_is_disabled():
    with pytest.raises(ExternalBrokerDisabled):
        IBKRBroker()


def test_ibkr_has_no_allowed_ports():
    assert PAPER_PORTS == frozenset()


def test_factory_does_not_expose_ibkr():
    from broker.factory import KNOWN_BROKERS

    assert "ibkr" not in KNOWN_BROKERS
