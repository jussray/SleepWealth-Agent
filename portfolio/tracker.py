from datetime import datetime, timezone

from broker.base import BaseBroker

from .models import AccountState, Balance


class PortfolioTracker:
    """Single source of truth for account state."""

    def __init__(self, broker: BaseBroker, min_cash_floor: float = 5.0):
        self.broker = broker
        self.min_cash_floor = min_cash_floor
        self.high_water_mark = 0.0
        self.last_update: AccountState | None = None

    async def refresh(self) -> AccountState:
        account = await self.broker.get_account_summary()
        positions = {p.symbol: p.qty for p in await self.broker.get_positions()}

        equity = float(account.get("equity", 0))
        self.high_water_mark = max(self.high_water_mark, equity)

        state = AccountState(
            balance=Balance(
                cash=float(account.get("cash", 0)),
                equity=equity,
                timestamp=datetime.now(timezone.utc),
            ),
            positions=positions,
            min_cash_floor=self.min_cash_floor,
        )
        self.last_update = state
        return state

    def max_drawdown_pct(self) -> float:
        if not self.high_water_mark or not self.last_update:
            return 0.0
        current = self.last_update.balance.equity
        return ((self.high_water_mark - current) / self.high_water_mark) * 100.0
