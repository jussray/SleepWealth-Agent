from broker.base import BaseBroker
from portfolio.tracker import PortfolioTracker


class RiskGates:
    """REDTEAM layer. Runs before every execution. Can veto, never spend."""

    def __init__(
        self,
        broker: BaseBroker,
        portfolio_tracker: PortfolioTracker,
        max_daily_loss: float = 100.0,
        max_drawdown_pct: float = 10.0,
    ):
        self.broker = broker
        self.portfolio_tracker = portfolio_tracker
        self.max_daily_loss = max_daily_loss
        self.max_drawdown_pct = max_drawdown_pct
        self.session_start_equity: float | None = None

    async def preflight_check(self) -> dict:
        account = await self.portfolio_tracker.refresh()

        if self.session_start_equity is None:
            self.session_start_equity = account.balance.equity

        if account.balance.cash < account.min_cash_floor:
            return {
                "passed": False,
                "reason": f"cash floor breached: ${account.balance.cash:.2f} < ${account.min_cash_floor:.2f}",
            }

        daily_loss = self.session_start_equity - account.balance.equity
        if daily_loss > self.max_daily_loss:
            return {
                "passed": False,
                "reason": f"daily loss limit hit: ${daily_loss:.2f} > ${self.max_daily_loss:.2f}",
            }

        drawdown = self.portfolio_tracker.max_drawdown_pct()
        if drawdown > self.max_drawdown_pct:
            return {
                "passed": False,
                "reason": f"max drawdown exceeded: {drawdown:.1f}% > {self.max_drawdown_pct:.1f}%",
            }

        return {
            "passed": True,
            "reason": "all risk gates clear",
            "cash": account.balance.cash,
            "equity": account.balance.equity,
            "drawdown_pct": round(drawdown, 2),
        }

    async def kill_switch(self) -> bool:
        """Emergency halt. True means stop everything."""
        account = await self.portfolio_tracker.refresh()
        if account.balance.cash < account.min_cash_floor * 0.5:
            return True
        if self.portfolio_tracker.max_drawdown_pct() > 20.0:
            return True
        return False
