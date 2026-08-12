"""Interactive Brokers adapter.

Built on `ib_async` (the maintained successor to ib_insync, which was archived
read-only in March 2024) talking to a headless IB Gateway.

The load-bearing safety property: paper mode is PROVEN at runtime, not
configured. After connect, `ib.managedAccounts()` is inspected — IBKR paper
account IDs are prefixed "DU", live individual accounts "U". If any managed
account is not a DU account, this adapter refuses to trade. A config flag is
treated as an assertion to be checked, never as a fact.

Three independent signals must agree:
    1. connected port is a known paper port (7497 TWS / 4002 Gateway)
    2. every managed account ID starts with "DU"
    3. the caller asked for paper mode

Import is lazy so the mock/CI path never requires ib_async to be installed.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import List, Optional

from .base import BaseBroker, Order, Position

TWS_LIVE_PORT = 7496
TWS_PAPER_PORT = 7497
GATEWAY_LIVE_PORT = 4001
GATEWAY_PAPER_PORT = 4002

PAPER_PORTS = {TWS_PAPER_PORT, GATEWAY_PAPER_PORT}
PAPER_ACCOUNT_PREFIX = "DU"

MARKET_DATA_DELAYED = 3   # free ~15-min delayed data; no subscription needed

DONE_STATES = {"Filled", "Cancelled", "ApiCancelled"}


class PaperModeViolation(RuntimeError):
    """Raised when paper mode cannot be proven. Never caught internally."""


@dataclass
class IBKRBroker(BaseBroker):
    """IBKR adapter. Defaults to Gateway paper on 4002."""

    paper_mode: bool = True
    host: str = "127.0.0.1"
    port: int = GATEWAY_PAPER_PORT
    client_id: int = 11
    account: Optional[str] = None
    use_delayed_data: bool = True
    connect_timeout: float = 8.0

    ib: object = field(default=None, init=False, repr=False)
    managed_accounts: List[str] = field(default_factory=list, init=False)
    _connected: bool = field(default=False, init=False)

    # ---- lifecycle ---------------------------------------------------

    async def connect(self) -> bool:
        try:
            from ib_async import IB
        except ImportError as exc:  # pragma: no cover - env dependent
            raise ImportError(
                "ib_async is required for the IBKR adapter.\n"
                "  pip install ib_async\n"
                "It replaces ib_insync, which is unmaintained."
            ) from exc

        if self.paper_mode and self.port not in PAPER_PORTS:
            raise PaperModeViolation(
                f"Paper mode requested but port {self.port} is not a paper port "
                f"{sorted(PAPER_PORTS)}. Refusing to connect."
            )

        self.ib = IB()
        await self.ib.connectAsync(
            self.host, self.port, clientId=self.client_id, timeout=self.connect_timeout
        )

        self.managed_accounts = list(self.ib.managedAccounts())
        if not self.managed_accounts:
            self.ib.disconnect()
            raise PaperModeViolation(
                "No managed accounts returned. Cannot prove paper vs live. Refusing."
            )

        if self.paper_mode and not self.is_paper_only():
            live = [a for a in self.managed_accounts
                    if not a.startswith(PAPER_ACCOUNT_PREFIX)]
            self.ib.disconnect()
            raise PaperModeViolation(
                f"Paper mode requested but these accounts are not paper: {live}. "
                "Disconnected without trading."
            )

        if self.account is None:
            self.account = self.managed_accounts[0]

        if self.use_delayed_data:
            # Free delayed data. Paper accounts do not inherit live subscriptions,
            # so without this most symbols return error 354.
            self.ib.reqMarketDataType(MARKET_DATA_DELAYED)

        self._connected = self.ib.isConnected()
        mode = "PAPER" if self.is_paper_only() else "LIVE"
        print(f"[IBKR] connected {self.host}:{self.port} clientId={self.client_id} "
              f"account={self.account} mode={mode}")
        return self._connected

    async def disconnect(self) -> None:
        if self.ib is not None and getattr(self.ib, "isConnected", lambda: False)():
            self.ib.disconnect()
        self._connected = False

    # ---- reads -------------------------------------------------------

    async def get_account_summary(self) -> dict:
        self._require_connection()
        rows = await self.ib.accountSummaryAsync(self.account)
        cash = equity = 0.0
        for row in rows:
            if row.currency not in ("USD", ""):
                continue
            if row.tag == "TotalCashValue":
                cash = float(row.value)
            elif row.tag == "NetLiquidation":
                equity = float(row.value)
        return {
            "cash": cash,
            "equity": equity,
            "account": self.account,
            "paper": self.is_paper_only(),
            "timestamp": datetime.now(timezone.utc),
        }

    async def get_positions(self) -> List[Position]:
        self._require_connection()
        out = []
        for p in self.ib.positions(self.account):
            if p.position == 0:
                continue
            out.append(Position(
                symbol=p.contract.symbol,
                qty=float(p.position),
                avg_price=float(p.avgCost),
            ))
        return out

    async def get_market_data(self, symbol: str) -> dict:
        import math
        self._require_connection()
        contract = await self._qualify(symbol)
        [ticker] = await self.ib.reqTickersAsync(contract)

        def clean(v):
            # ib_async returns nan for unset fields, not None. 0.0 is falsy, so
            # never truthiness-test these.
            return None if v is None or (isinstance(v, float) and math.isnan(v)) else float(v)

        price = clean(ticker.last) or clean(ticker.close) or clean(ticker.marketPrice())
        return {
            "symbol": symbol,
            "price": price,
            "bid": clean(ticker.bid),
            "ask": clean(ticker.ask),
            "delayed": self.use_delayed_data,
            "timestamp": datetime.now(timezone.utc),
        }

    async def get_order_status(self, order_id: str) -> dict:
        self._require_connection()
        for trade in self.ib.trades():
            if str(trade.order.orderId) == str(order_id) or \
               str(trade.order.permId) == str(order_id):
                st = trade.orderStatus
                return {
                    "order_id": order_id,
                    "status": st.status,
                    "filled": float(st.filled),
                    "remaining": float(st.remaining),
                    "avg_fill_price": float(st.avgFillPrice or 0.0),
                    "done": st.status in DONE_STATES,
                }
        return {"order_id": order_id, "status": "not_found"}

    # ---- writes ------------------------------------------------------

    async def submit_order(self, order: Order, cash_qty: Optional[float] = None) -> dict:
        """Submit a market order.

        `cash_qty` sends a notional dollar amount instead of a share count —
        the natural fit for a $5 ceiling. Requires the account to be permissioned
        for fractional trading; IBKR's own docs are inconsistent on API support,
        so a successful fractional paper fill is a pre-live gate condition.
        """
        self._require_connection()

        if self.paper_mode and not self.is_paper_only():
            raise PaperModeViolation("Paper mode asserted but account is not paper.")

        from ib_async import MarketOrder

        try:
            contract = await self._qualify(order.symbol)
            side = "BUY" if order.side.lower() == "buy" else "SELL"

            if cash_qty is not None:
                ib_order = MarketOrder(side, 0, cashQty=float(cash_qty))
            else:
                if order.qty <= 0:
                    return {"status": "rejected", "reason": "qty must be > 0"}
                ib_order = MarketOrder(side, float(order.qty))

            ib_order.account = self.account
            trade = self.ib.placeOrder(contract, ib_order)
            await self.ib.sleep(0)  # let the first status callback land

            st = trade.orderStatus
            if st.status == "ValidationError":
                return {"status": "rejected", "reason": trade.log[-1].message if trade.log else "validation error"}

            return {
                "order_id": str(trade.order.orderId),
                "perm_id": str(trade.order.permId),
                "status": st.status,
                "filled": float(st.filled),
                "avg_fill_price": float(st.avgFillPrice or 0.0),
                "timestamp": datetime.now(timezone.utc),
            }
        except Exception as exc:
            return {"status": "rejected", "reason": f"{type(exc).__name__}: {exc}"}

    async def cancel_order(self, order_id: str) -> bool:
        self._require_connection()
        for trade in self.ib.trades():
            if str(trade.order.orderId) == str(order_id):
                self.ib.cancelOrder(trade.order)
                return True
        return False

    async def cancel_all(self) -> bool:
        """Kill switch primitive. Pulls every working order at once."""
        self._require_connection()
        self.ib.reqGlobalCancel()
        return True

    # ---- proof -------------------------------------------------------

    def is_paper_only(self) -> bool:
        """Three signals must agree. Any disagreement means 'not provably paper'."""
        port_ok = self.port in PAPER_PORTS
        accounts_ok = bool(self.managed_accounts) and all(
            a.startswith(PAPER_ACCOUNT_PREFIX) for a in self.managed_accounts
        )
        return bool(port_ok and accounts_ok and self.paper_mode)

    def paper_proof(self) -> dict:
        """Evidence for the audit log and the live gate."""
        return {
            "port": self.port,
            "port_is_paper": self.port in PAPER_PORTS,
            "managed_accounts": self.managed_accounts,
            "all_accounts_paper": bool(self.managed_accounts) and all(
                a.startswith(PAPER_ACCOUNT_PREFIX) for a in self.managed_accounts
            ),
            "configured_paper": self.paper_mode,
            "provably_paper": self.is_paper_only(),
        }

    # ---- internals ---------------------------------------------------

    async def _qualify(self, symbol: str):
        from ib_async import Stock
        contract = Stock(symbol, "SMART", "USD")
        await self.ib.qualifyContractsAsync(contract)
        return contract

    def _require_connection(self) -> None:
        if not self._connected or self.ib is None:
            raise RuntimeError("IBKR adapter is not connected. Call connect() first.")
