from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict


@dataclass
class Balance:
    cash: float
    equity: float
    timestamp: datetime


@dataclass
class AccountState:
    balance: Balance
    positions: Dict[str, float] = field(default_factory=dict)
    min_cash_floor: float = 5.0

    def safe_to_trade(self) -> bool:
        """The $5 floor. Load-bearing rule."""
        return self.balance.cash >= self.min_cash_floor
