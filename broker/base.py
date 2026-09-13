from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class Position:
    """An open position."""

    symbol: str
    qty: float
    avg_price: float


@dataclass(frozen=True)
class Order:
    """An immutable order intent.

    Approval is bound to these exact values. Replacing the order on an approved
    proposal is detected by the approval fingerprint before broker submission.
    """

    symbol: str
    qty: float
    side: str
    asset_class: str = "stocks"


class BaseBroker(ABC):
    """Abstract broker contract. Every adapter implements these 8 methods."""

    @abstractmethod
    async def connect(self) -> bool:
        """Authenticate and test connection."""

    @abstractmethod
    async def get_account_summary(self) -> dict:
        """Return account summary data."""

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """Return open positions."""

    @abstractmethod
    async def submit_order(self, order: Order) -> dict:
        """Submit a simulated order to the active broker implementation."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel by id."""

    @abstractmethod
    async def get_order_status(self, order_id: str) -> dict:
        """Return current order state."""

    @abstractmethod
    async def get_market_data(self, symbol: str) -> dict:
        """Return simulated market data."""

    @abstractmethod
    def is_paper_only(self) -> bool:
        """True if this adapter can never touch real money."""
