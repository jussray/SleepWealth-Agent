"""Execution-mode contract for Sleep Wealth.

Practice mode is the only executable simulation mode. Live mode exists so the
product can observe and label real market state without being able to submit,
spend, transfer, or authorize real-money actions.
"""

from dataclasses import dataclass

PRACTICE_MODE = "practice"
LIVE_MODE = "live"
SUPPORTED_MODES = (PRACTICE_MODE, LIVE_MODE)


@dataclass(frozen=True, slots=True)
class ExecutionMode:
    name: str
    market_observation: str
    simulated_execution_enabled: bool
    real_execution_enabled: bool
    authority_ceiling: str


MODES = {
    PRACTICE_MODE: ExecutionMode(
        name=PRACTICE_MODE,
        market_observation="read-only",
        simulated_execution_enabled=True,
        real_execution_enabled=False,
        authority_ceiling="simulation-only",
    ),
    LIVE_MODE: ExecutionMode(
        name=LIVE_MODE,
        market_observation="read-only",
        simulated_execution_enabled=False,
        real_execution_enabled=False,
        authority_ceiling="observation-only; no real-money execution",
    ),
}


def get_execution_mode(value: str | None) -> ExecutionMode:
    name = str(value or PRACTICE_MODE).strip().lower()
    if name not in SUPPORTED_MODES:
        raise ValueError(f"unsupported execution mode: {name}")
    return MODES[name]


def require_simulated_execution(value: str | None) -> ExecutionMode:
    mode = get_execution_mode(value)
    if not mode.simulated_execution_enabled:
        raise PermissionError(f"{mode.name} mode is observation-only")
    return mode


def require_real_execution(value: str | None) -> ExecutionMode:
    mode = get_execution_mode(value)
    raise PermissionError(
        f"real execution is disabled in {mode.name} mode; authority ceiling is {mode.authority_ceiling}"
    )
