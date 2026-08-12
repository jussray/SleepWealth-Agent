"""Paper mode must be proven, never assumed."""
import pytest
from broker.ibkr import IBKRBroker, PaperModeViolation, PAPER_PORTS


def test_paper_requires_all_three_signals():
    b = IBKRBroker(paper_mode=True, port=4002)
    b.managed_accounts = ["DU1234567"]
    assert b.is_paper_only() is True

    b.managed_accounts = ["U1234567"]          # live account id
    assert b.is_paper_only() is False

    b.managed_accounts = ["DU1234567", "U999"]  # mixed
    assert b.is_paper_only() is False


def test_live_port_is_never_paper():
    b = IBKRBroker(paper_mode=True, port=4001)  # gateway LIVE
    b.managed_accounts = ["DU1234567"]
    assert b.is_paper_only() is False


def test_paper_proof_is_explicit():
    b = IBKRBroker(paper_mode=True, port=4002)
    b.managed_accounts = ["DU1"]
    proof = b.paper_proof()
    assert proof["provably_paper"] is True
    assert proof["all_accounts_paper"] is True
    assert proof["port_is_paper"] is True


def test_factory_knows_ibkr():
    from broker.factory import KNOWN_BROKERS
    assert "ibkr" in KNOWN_BROKERS
