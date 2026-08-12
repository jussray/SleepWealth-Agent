from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List


@dataclass
class Position:
    """An open position."""
    symbol: str
    qty: float
    avg_price: float


@dataclass
class Order:
    """An order to submit."""
    symbol: str
    qty: float
    side: str  # "buy" | "sell"
    asset_class: str = "stocks"  # "stocks" | "crypto"


class BaseBroker(ABC):
    """Abstract broker contract. Every adapter implements these 8 methods."""

    @abstractmethod
    async def connect(self) -> bool:
        """Authenticate and test connection."""

    @abstractmethod
    async def get_account_summary(self) -> dict:
        """Return {'cash', 'equity', 'timestamp'}."""

    @abstractmethod
    async def get_positions(self) -> List[Position]:
        """Return open positions."""

    @abstractmethod
    async def submit_order(self, order: Order) -> dict:
        """Return {'order_id', 'status', ...} or {'status': 'rejected', 'reason'}."""

    @abstractmethod
    async def cancel_order(self, order_id: str) -> bool:
        """Cancel by id."""

    @abstractmethod
    async def get_order_status(self, order_id: str) -> dict:
        """Return current order state."""

    @abstractmethod
    async def get_market_data(self, symbol: str) -> dict:
        """Return {'symbol', 'price', 'bid', 'ask', 'timestamp'}."""

    @abstractmethod
    def is_paper_only(self) -> bool:
        """True if this adapter can never touch real money."""
