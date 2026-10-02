import pytest

from risk.latched_halt import EvidenceState, HaltState, LatchedRiskHalt, RecoveryNotice, RiskSignal


def signal(name="liquidity", *, evidence=EvidenceState.VERIFIED, risk=2.0, gain=5.0):
    return RiskSignal(name=name, evidence=evidence, risk_score=risk, gain_score=gain)


def test_risk_greater_than_gain_latches_and_keeps_observation_alive():
    gate = LatchedRiskHalt("mom8")
    receipt = gate.observe((signal(risk=8.0, gain=3.0),))
    assert receipt.state is HaltState.HALTED
    assert receipt.execution_authority is False
    assert receipt.observation_authority is True
    assert receipt.human_reauthorization_required is True


def test_unknown_and_blocked_are_not_safe():
    for evidence in (EvidenceState.UNKNOWN, EvidenceState.BLOCKED):
        gate = LatchedRiskHalt("outside-token")
        receipt = gate.observe((signal(evidence=evidence, risk=None, gain=None),))
        assert receipt.state is HaltState.HALTED
        assert receipt.execution_authority is False


def test_recovery_notifies_but_does_not_self_resume():
    gate = LatchedRiskHalt("mom8", recovery_observations=3)
    gate.observe((signal(risk=9.0, gain=1.0),))
    assert gate.execution_authority is False

    assert gate.observe((signal(),)) is None
    assert gate.observe((signal(),)) is None
    notice = gate.observe((signal(),))
    assert isinstance(notice, RecoveryNotice)
    assert notice.classification == "RECOVERY_CANDIDATE"
    assert notice.execution_authority is False
    assert notice.human_reauthorization_required is True
    assert gate.state is HaltState.HALTED


def test_human_cannot_reauthorize_before_persistent_recovery():
    gate = LatchedRiskHalt("mom8", recovery_observations=2)
    gate.observe((signal(risk=7.0, gain=1.0),))
    gate.observe((signal(),))
    with pytest.raises(PermissionError):
        gate.human_reauthorize(approved=True)


def test_explicit_human_reauthorization_after_recovery_reopens_execution():
    gate = LatchedRiskHalt("mom8", recovery_observations=2)
    gate.observe((signal(risk=7.0, gain=1.0),))
    gate.observe((signal(),))
    gate.observe((signal(),))
    receipt = gate.human_reauthorize(approved=True)
    assert receipt.state is HaltState.ACTIVE
    assert receipt.execution_authority is True


def test_new_red_signal_resets_recovery_streak():
    gate = LatchedRiskHalt("mom8", recovery_observations=2)
    gate.observe((signal(risk=7.0, gain=1.0),))
    gate.observe((signal(),))
    gate.observe((signal(name="concentration", risk=9.0, gain=2.0),))
    assert gate.observe((signal(),)) is None
    notice = gate.observe((signal(),))
    assert isinstance(notice, RecoveryNotice)
