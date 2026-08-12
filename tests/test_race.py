"""Tests for the race layer. These encode the load-bearing rules."""
import asyncio
import pytest

from audit.logger import AuditLogger
from race.engines.base import EngineState, MarketSnapshot, Tick
from race.engines.gates import GatesEngine
from race.engines.musk import MuskEngine
from race.harness import RaceHarness
from race.ledger import BASE_STAKE, StakeLedger, VaultBreach
from race.modes import Decision, FutureYou, Mode

SYMS = ["AAPL", "MSFT", "VTI"]


def fy(durable=True):
    return FutureYou(enables="x", breaks="y", durable=durable)


def test_decision_requires_futureyou():
    """/futureyou is enforced, not documented."""
    with pytest.raises(TypeError):
        Decision(engine="Musk", action="buy", symbol="AAPL", qty=1.0,
                 confidence=50, risk_score=10, reasoning="r", futureyou=None)


def test_futureyou_rejects_empty_fields():
    with pytest.raises(ValueError):
        FutureYou(enables="", breaks="y", durable=True)


def test_futureyou_always_tagged_on_decision():
    d = Decision(engine="Gates", action="hold", symbol=None, qty=0,
                 confidence=0, risk_score=0, reasoning="r", futureyou=fy())
    assert Mode.FUTUREYOU.value in d.mode_tags()


def test_both_engines_have_redteam():
    """Musk is governed, not ungoverned. Different threshold, same contract."""
    musk, gates = MuskEngine(SYMS), GatesEngine(SYMS)
    assert musk.risk_threshold > gates.risk_threshold
    assert hasattr(musk, "redteam") and hasattr(gates, "redteam")


def test_redteam_vetoes_over_threshold():
    gates = GatesEngine(SYMS)
    snap = MarketSnapshot(0, {"AAPL": Tick("AAPL", 100.0, 100.0)})
    state = EngineState(cash=5.0, stake=5.0)
    d = Decision(engine="Gates", action="buy", symbol="AAPL", qty=0.01,
                 confidence=90, risk_score=99, reasoning="too hot", futureyou=fy())
    out = gates.redteam(d, state, snap)
    assert out.vetoed_by == "Gates:REDTEAM"
    assert not out.executed


def test_non_durable_futureyou_is_vetoed():
    """A move you wouldn't repeat in 3 races doesn't execute."""
    musk = MuskEngine(SYMS)
    snap = MarketSnapshot(0, {"AAPL": Tick("AAPL", 100.0, 100.0)})
    state = EngineState(cash=5.0, stake=5.0)
    d = Decision(engine="Musk", action="buy", symbol="AAPL", qty=0.01,
                 confidence=90, risk_score=10, reasoning="r", futureyou=fy(durable=False))
    out = musk.redteam(d, state, snap)
    assert out.vetoed_by == "Musk:/futureyou"


def test_vault_cannot_be_spent():
    ledger = StakeLedger()
    with pytest.raises(VaultBreach):
        ledger.spend_from_vault(1.0)


def test_stake_never_starts_below_five():
    ledger = StakeLedger()
    ledger.settle_race(1, "Musk", ending_balance=0.10, is_winner=False)
    assert ledger.stake_for("Musk") == BASE_STAKE
    ok, _ = ledger.can_start_race("Musk")
    assert ok


def test_losses_do_not_compound_across_races():
    ledger = StakeLedger()
    for i in range(1, 4):
        ledger.settle_race(i, "Musk", ending_balance=0.01, is_winner=False)
        assert ledger.stake_for("Musk") == BASE_STAKE


def test_profit_sweeps_to_vault():
    ledger = StakeLedger()
    ledger.settle_race(1, "Gates", ending_balance=9.00, is_winner=False)
    assert ledger.vault == 4.00
    assert ledger.stake_for("Gates") == BASE_STAKE


def test_winner_bonus_is_capped_by_vault():
    ledger = StakeLedger()
    ledger.settle_race(1, "Gates", ending_balance=5.50, is_winner=True)
    # $0.50 profit swept, bonus can only draw what exists
    assert ledger.vault == 0.0
    assert ledger.stake_for("Gates") == pytest.approx(5.50)


def test_race_runs_and_scores():
    async def go():
        engines = [MuskEngine(SYMS), GatesEngine(SYMS)]
        h = RaceHarness(engines, StakeLedger(), AuditLogger("/tmp/test_race.log"))
        r = await h.run_race(duration="5m", seed=1, verbose=False)
        assert len(r.scores) == 2
        assert all(s.stake == BASE_STAKE for s in r.scores)
        return r, h
    r, h = asyncio.run(go())
    assert r.race_id == 1


def test_cross_learning_reads_moves_not_outcomes():
    async def go():
        engines = [MuskEngine(SYMS), GatesEngine(SYMS)]
        h = RaceHarness(engines, StakeLedger(), AuditLogger("/tmp/test_race2.log"))
        r = await h.run_race(duration="15m", seed=3, verbose=False)
        patches = h.cross_learn(r, verbose=False)
        return patches
    patches = asyncio.run(go())
    assert "Musk" in patches and "Gates" in patches
    # Both learn, including the winner — a win can be luck.
    assert any(patches.values())


def test_every_logged_decision_carries_futureyou():
    async def go():
        engines = [MuskEngine(SYMS), GatesEngine(SYMS)]
        h = RaceHarness(engines, StakeLedger(), AuditLogger("/tmp/test_race3.log"))
        await h.run_race(duration="5m", seed=9, verbose=False)
        return [d for e in engines for d in e.decisions]
    decisions = asyncio.run(go())
    assert decisions
    for d in decisions:
        assert d.futureyou is not None
        assert Mode.FUTUREYOU.value in d.mode_tags()
