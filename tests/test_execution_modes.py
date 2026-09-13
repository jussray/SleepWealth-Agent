import pytest

from execution import (
    LIVE_MODE,
    PRACTICE_MODE,
    get_execution_mode,
    require_real_execution,
    require_simulated_execution,
)


def test_practice_mode_allows_simulation_only():
    mode = get_execution_mode(PRACTICE_MODE)

    assert mode.market_observation == "read-only"
    assert mode.simulated_execution_enabled is True
    assert mode.real_execution_enabled is False
    assert mode.authority_ceiling == "simulation-only"


def test_live_mode_exists_but_is_observation_only():
    mode = get_execution_mode(LIVE_MODE)

    assert mode.market_observation == "read-only"
    assert mode.simulated_execution_enabled is False
    assert mode.real_execution_enabled is False
    assert "no real-money execution" in mode.authority_ceiling


def test_live_mode_cannot_reuse_practice_executor():
    with pytest.raises(PermissionError, match="observation-only"):
        require_simulated_execution(LIVE_MODE)


def test_real_execution_is_disabled_in_every_mode():
    for mode in (PRACTICE_MODE, LIVE_MODE):
        with pytest.raises(PermissionError, match="real execution is disabled"):
            require_real_execution(mode)


def test_unknown_mode_fails_closed():
    with pytest.raises(ValueError, match="unsupported execution mode"):
        get_execution_mode("anything-else")
