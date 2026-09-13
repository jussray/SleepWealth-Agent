"""Disabled external broker adapter.

SleepWealth Agent keeps market observation separate from execution. External
broker network access is intentionally unavailable in this build.
"""

from .base import BaseBroker, Order


class ExternalBrokerDisabled(RuntimeError):
    """Raised when code attempts to use an external broker adapter."""


class AlpacaBroker(BaseBroker):
    """Compatibility stub that cannot connect or submit orders."""

    def __init__(self, *args, **kwargs):
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

    async def get_order_status(self, order_id: str) -> dict:  # pragma: no cover
        return {"status": "not_found"}

    async def get_market_data(self, symbol: str) -> dict:  # pragma: no cover
        return {}

    def is_paper_only(self) -> bool:  # pragma: no cover
        return True
