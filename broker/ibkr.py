"""Disabled external broker adapter.

SleepWealth Agent keeps read-only market observation separate from execution.
This compatibility module cannot connect to Interactive Brokers or submit orders.
"""

from dataclasses import dataclass
from typing import Optional

from .base import BaseBroker, Order


class PaperModeViolation(RuntimeError):
    """Compatibility error retained for older imports."""


class ExternalBrokerDisabled(RuntimeError):
    """Raised when code attempts to use an external broker adapter."""


PAPER_PORTS = frozenset()


@dataclass
class IBKRBroker(BaseBroker):
    """Compatibility stub that cannot connect or submit orders."""

    paper_mode: bool = True
    host: str = "disabled"
    port: int = 0
    client_id: int = 0
    account: Optional[str] = None

    def __post_init__(self) -> None:
        raise ExternalBrokerDisabled(
            "External broker adapters are disabled; use broker='mock' for simulation."
        )

    async def connect(self) -> bool:  # pragma: no cover
        return False

    async def get_account_summary(self) -> dict:  # pragma: no cover
        return {"error": "external broker disabled"}

    async def get_positions(self):  # pragma: no cover
        return []

    async def submit_order(self, order: Order) -> dict:  # pragma: no cover
        return {"status": "rejected", "reason": "external broker disabled"}

    async def cancel_order(self, order_id: str) -> bool:  # pragma: no cover
        return False

    async def cancel_all(self) -> bool:  # pragma: no cover
        return False

    async def get_order_status(self, order_id: str) -> dict:  # pragma: no cover
        return {"status": "not_found"}

    async def get_market_data(self, symbol: str) -> dict:  # pragma: no cover
        return {}

    def is_paper_only(self) -> bool:  # pragma: no cover
        return True

    def paper_proof(self) -> dict:  # pragma: no cover
        return {
            "port": None,
            "managed_accounts": [],
            "configured_paper": False,
            "provably_paper": False,
            "external_broker_disabled": True,
        }
